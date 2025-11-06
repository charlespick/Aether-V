"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

from pypsrp.exceptions import AuthenticationError, PyPSRPError
from pypsrp.powershell import InvocationState, PowerShell, RunspacePool
from pypsrp.wsman import WSMan

from ..core.config import settings

logger = logging.getLogger(__name__)


class WinRMServiceError(RuntimeError):
    """Base exception for WinRM service failures."""


class WinRMAuthenticationError(WinRMServiceError):
    """Raised when authentication to a host fails."""


class WinRMTransportError(WinRMServiceError):
    """Raised for lower-level transport failures."""


@dataclass
class _PSRPStreamCursor:
    """Track consumption of PowerShell pipeline and error streams."""

    hostname: str
    on_chunk: Callable[[str, str], None]
    output_index: int = 0
    error_index: int = 0
    stdout_chunks: int = 0
    stderr_chunks: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    exit_code: Optional[int] = None

    _EXIT_SENTINEL: str = "__AETHER_V_EXIT_CODE__:"

    def drain(self, ps: PowerShell) -> None:
        """Emit new output/error records as text chunks."""

        # Drain pipeline output (treated as stdout)
        output_items = ps.output[self.output_index :]
        if output_items:
            for item in output_items:
                text = self._stringify(item)
                if not text:
                    continue
                if text.startswith(self._EXIT_SENTINEL):
                    parsed = text[len(self._EXIT_SENTINEL) :].strip()
                    try:
                        self.exit_code = int(parsed)
                    except ValueError:
                        logger.warning(
                            "Received malformed exit code sentinel '%s' from %s", parsed, self.hostname
                        )
                    continue

                payload = self._ensure_line_termination(text)
                self.stdout_chunks += 1
                self.stdout_bytes += len(payload.encode("utf-8", errors="ignore"))
                self.on_chunk("stdout", payload)

        self.output_index = len(ps.output)

        # Drain error stream
        error_items = ps.streams.error[self.error_index :]
        if error_items:
            for item in error_items:
                text = self._stringify(item)
                if not text:
                    continue
                if text.startswith(self._EXIT_SENTINEL):
                    parsed = text[len(self._EXIT_SENTINEL) :].strip()
                    try:
                        self.exit_code = int(parsed)
                    except ValueError:
                        logger.warning(
                            "Received malformed exit code sentinel '%s' from %s", parsed, self.hostname
                        )
                    continue

                payload = self._ensure_line_termination(text)
                self.stderr_chunks += 1
                self.stderr_bytes += len(payload.encode("utf-8", errors="ignore"))
                self.on_chunk("stderr", payload)

        self.error_index = len(ps.streams.error)

    @staticmethod
    def _stringify(item: Any) -> str:
        """Best-effort string conversion for PSRP data."""

        if item is None:
            return ""

        formatter = getattr(item, "to_string", None)
        if callable(formatter):
            try:
                return formatter()
            except Exception:  # pragma: no cover - defensive logging
                logger.debug("Failed to format PSRP object via to_string", exc_info=True)

        if hasattr(item, "value") and isinstance(getattr(item, "value"), str):
            return getattr(item, "value")

        return str(item)

    @staticmethod
    def _ensure_line_termination(text: str) -> str:
        """Ensure the streamed payload ends with a newline for readability."""

        if text.endswith("\n"):
            return text
        if text.endswith("\r"):
            return text + "\n"
        return text + "\n"


def _format_output_preview(output: str, *, max_length: int = 400) -> str:
    """Return a newline-prefixed preview of command/script output."""
    if not output:
        return ""

    sanitized = output.replace("\r\n", "\n").strip()
    if not sanitized:
        return ""

    if len(sanitized) > max_length:
        preview = sanitized[: max_length - 3] + "..."
    else:
        preview = sanitized

    return "\n" + preview


class WinRMService:
    """Service for managing WinRM connections to Hyper-V hosts."""

    _EXIT_SENTINEL: str = _PSRPStreamCursor._EXIT_SENTINEL

    @contextmanager
    def _session(self, hostname: str) -> Iterator[RunspacePool]:
        """Yield an opened runspace pool for the target host."""

        wsman = self._create_session(hostname)
        pool = RunspacePool(wsman)
        try:
            pool.open()
            yield pool
        finally:
            try:
                pool.close()
            finally:
                self._dispose_session(wsman)

    def get_session(self, hostname: str) -> RunspacePool:
        """Return a new runspace pool for the caller."""

        logger.debug("Creating new runspace pool for %s", hostname)
        wsman = self._create_session(hostname)
        pool = RunspacePool(wsman)
        pool.open()
        return pool

    def _create_session(self, hostname: str) -> WSMan:
        """Create a new WSMan session using configured credentials."""

        logger.info(
            "Creating WinRM (PSRP) session to %s (port=%s, transport=%s, username=%s)",
            hostname,
            settings.winrm_port,
            settings.winrm_transport,
            settings.winrm_username or "<anonymous>",
        )

        auth = settings.winrm_transport or "ntlm"
        use_ssl = settings.winrm_port == 5986

        try:
            session = WSMan(
                hostname,
                port=settings.winrm_port,
                username=settings.winrm_username,
                password=settings.winrm_password,
                auth=auth,
                ssl=use_ssl,
                cert_validation=False,
            )
        except AuthenticationError as exc:  # pragma: no cover - network heavy
            logger.error("Authentication failed while connecting to %s: %s", hostname, exc)
            raise WinRMAuthenticationError(str(exc)) from exc
        except PyPSRPError as exc:  # pragma: no cover - network heavy
            logger.error("Failed to create WSMan session to %s: %s", hostname, exc)
            raise WinRMTransportError(str(exc)) from exc

        logger.debug("Created WSMan session to %s", hostname)
        return session

    def close_session(self, hostname: str) -> None:
        """Close cached WinRM sessions (no-op for per-operation sessions)."""

        logger.debug("close_session called for %s, but sessions are not cached", hostname)

    def close_all_sessions(self) -> None:
        """Close all WinRM sessions (no-op for per-operation sessions)."""

        logger.debug("close_all_sessions called, but sessions are not cached")

    def execute_ps_script(
        self,
        hostname: str,
        script_path: str,
        parameters: Dict[str, Any],
        environment: Optional[Dict[str, str]] = None,
    ) -> tuple[str, str, int]:
        """Execute a PowerShell script on a remote host."""

        command = self._build_script_invocation(script_path, parameters)
        script = self._wrap_command(command, environment)

        logger.info("Executing PowerShell script on %s", hostname)
        logger.debug(
            "Script invocation on %s -> path=%s params=%s env=%s",
            hostname,
            script_path,
            parameters,
            environment,
        )

        return self._execute(hostname, script)

    def execute_ps_command(
        self, hostname: str, command: str
    ) -> tuple[str, str, int]:
        """Execute an arbitrary PowerShell command on a host."""

        truncated = command.replace("\n", " ")
        if len(truncated) > 120:
            truncated = f"{truncated[:117]}..."
        logger.info("Executing PowerShell command on %s: %s", hostname, truncated)
        logger.debug("Full PowerShell command on %s: %s", hostname, command)

        script = self._wrap_command(command, None)
        return self._execute(hostname, script)

    def stream_ps_command(
        self,
        hostname: str,
        command: str,
        on_chunk: Callable[[str, str], None],
    ) -> int:
        """Execute a PowerShell command and stream output via callback."""

        truncated = command.replace("\n", " ")
        if len(truncated) > 120:
            truncated = f"{truncated[:117]}..."
        logger.info("Streaming PowerShell command on %s: %s", hostname, truncated)
        logger.debug("Full streaming PowerShell command on %s: %s", hostname, command)

        script = self._wrap_command(command, None)

        with self._session(hostname) as pool:
            cursor = _PSRPStreamCursor(hostname=hostname, on_chunk=on_chunk)
            exit_code, duration = self._invoke(pool, hostname, script, cursor)

        logger.info(
            "Streaming command on %s completed in %.2fs with exit code %s (stdout=%d bytes in %d chunks, stderr=%d bytes in %d chunks)",
            hostname,
            duration,
            exit_code,
            cursor.stdout_bytes,
            cursor.stdout_chunks,
            cursor.stderr_bytes,
            cursor.stderr_chunks,
        )

        return exit_code

    def _execute(self, hostname: str, script: str) -> tuple[str, str, int]:
        """Execute a script synchronously and return collected output."""

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _collect(stream: str, payload: str) -> None:
            if stream == "stdout":
                stdout_chunks.append(payload)
            else:
                stderr_chunks.append(payload)

        cursor = _PSRPStreamCursor(hostname=hostname, on_chunk=_collect)

        with self._session(hostname) as pool:
            exit_code, duration = self._invoke(pool, hostname, script, cursor)

        stdout = self._join_chunks(stdout_chunks)
        stderr = self._join_chunks(stderr_chunks)

        stdout_preview = _format_output_preview(stdout)
        stderr_preview = _format_output_preview(stderr)

        logger.info(
            "Command on %s completed in %.2fs with exit code %s (stdout=%d bytes, stderr=%d bytes)",
            hostname,
            duration,
            exit_code,
            len(stdout.encode("utf-8")),
            len(stderr.encode("utf-8")),
        )
        if stdout_preview:
            logger.info("Command stdout preview on %s:%s", hostname, stdout_preview)
        else:
            logger.info("Command stdout on %s was empty", hostname)

        if stderr_preview:
            level = logger.warning if exit_code != 0 else logger.info
            level("Command stderr preview on %s:%s", hostname, stderr_preview)
        else:
            logger.info("Command stderr on %s was empty", hostname)

        if exit_code != 0:
            logger.warning("Command on %s exited with non-zero status %s", hostname, exit_code)

        return stdout, stderr, exit_code

    def _invoke(
        self,
        pool: RunspacePool,
        hostname: str,
        script: str,
        cursor: _PSRPStreamCursor,
    ) -> tuple[int, float]:
        """Run the provided script in the supplied runspace pool."""

        ps = PowerShell(pool)
        ps.add_script(script)

        start_time = perf_counter()
        async_handle = None
        completed = False
        try:
            async_handle = ps.begin_invoke()
            while True:
                state = ps.poll_invoke(async_handle)
                cursor.drain(ps)
                if self._state_complete(state):
                    break
            ps.end_invoke(async_handle)
            completed = True
            cursor.drain(ps)
        except AuthenticationError as exc:  # pragma: no cover - network heavy
            logger.error("Authentication failure while executing command on %s: %s", hostname, exc)
            raise WinRMAuthenticationError(str(exc)) from exc
        except PyPSRPError as exc:  # pragma: no cover - network heavy
            logger.error("WinRM execution failed on %s: %s", hostname, exc)
            raise WinRMTransportError(str(exc)) from exc
        finally:
            if async_handle is not None and not completed:
                try:
                    ps.end_invoke(async_handle)
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.debug("Failed to end PowerShell invocation cleanly", exc_info=True)

            closer = getattr(ps, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.debug("Failed to close PowerShell pipeline cleanly", exc_info=True)

        duration = perf_counter() - start_time
        exit_code = cursor.exit_code
        if exit_code is None:
            exit_code = 0 if not ps.had_errors else 1

        return exit_code, duration

    @staticmethod
    def _state_complete(state: InvocationState) -> bool:
        """Return True when the invocation state indicates completion."""

        if isinstance(state, InvocationState):
            terminal_states = {
                InvocationState.COMPLETED,
                InvocationState.FAILED,
                InvocationState.STOPPED,
            }
            disconnected = getattr(InvocationState, "DISCONNECTED", None)
            if disconnected is not None:
                terminal_states.add(disconnected)
            return state in terminal_states

        normalized = str(state).lower()
        return normalized in {"completed", "failed", "stopped", "disconnected"}

    @staticmethod
    def _join_chunks(chunks: Iterable[str]) -> str:
        """Combine collected string chunks preserving order."""

        return "".join(chunk for chunk in chunks if chunk)

    def _wrap_command(
        self, command: str, environment: Optional[Dict[str, str]]
    ) -> str:
        """Embed the requested command in boilerplate handling."""

        env_lines: list[str] = []
        if environment:
            for key, value in environment.items():
                env_lines.append(f"$env:{key} = {self._ps_quote(str(value))}")

        sentinel_line = f'Write-Output "{self._EXIT_SENTINEL}$AetherExitCode"'
        boilerplate = [
            "$ErrorActionPreference = 'Continue'",
            "$ProgressPreference = 'SilentlyContinue'",
            "$global:LASTEXITCODE = 0",
            "$AetherExitCode = 0",
            *env_lines,
            "try {",
            "    & {",
            "        " + command.replace("\n", "\n        "),
            "    }",
            "    if ($?) {",
            "        $AetherExitCode = $LASTEXITCODE",
            "    } else {",
            "        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {",
            "            $AetherExitCode = $LASTEXITCODE",
            "        } else {",
            "            $AetherExitCode = 1",
            "        }",
            "    }",
            "} catch {",
            "    $AetherExitCode = 1",
            "    Write-Error $_",
            "}",
            "if ($AetherExitCode -eq $null) { $AetherExitCode = 0 }",
            sentinel_line,
        ]

        return "\n".join(boilerplate)

    @staticmethod
    def _ps_quote(value: str) -> str:
        """Return a single-quoted PowerShell literal."""

        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    def _build_script_invocation(
        self, script_path: str, parameters: Dict[str, Any]
    ) -> str:
        """Construct the PowerShell invocation for a script path."""

        args: list[str] = []
        for key, value in parameters.items():
            if value is None:
                continue

            flag = f"-{key}"
            if isinstance(value, bool):
                if value:
                    args.append(flag)
            elif isinstance(value, (int, float)):
                args.extend([flag, str(value)])
            else:
                args.extend([flag, self._ps_quote(str(value))])

        path_literal = self._ps_quote(script_path)
        invocation = f"& {path_literal}"
        if args:
            invocation = f"{invocation} {' '.join(args)}"

        return invocation

    def _dispose_session(self, session: WSMan) -> None:
        """Attempt to close transport resources for a WSMan session."""

        closer = getattr(session, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.debug("Failed to close WSMan session cleanly", exc_info=True)


# Global WinRM service instance
winrm_service = WinRMService()

__all__ = [
    "WinRMService",
    "winrm_service",
    "WinRMAuthenticationError",
    "WinRMTransportError",
]
