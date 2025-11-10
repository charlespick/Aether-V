"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Set

from pypsrp.exceptions import (
    AuthenticationError,
    PSInvocationState,
    WinRMError,
    WinRMTransportError as PyWinRMTransportError,
)
from pypsrp.powershell import PowerShell, RunspacePool
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
    information_index: int = 0
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

        # Drain information stream (Write-Host, Write-Information)
        information_items = ps.streams.information[self.information_index :]
        if information_items:
            for record in information_items:
                text = self._stringify_information(record)
                if not text:
                    continue

                payload = self._ensure_line_termination(text)
                self.stdout_chunks += 1
                self.stdout_bytes += len(payload.encode("utf-8", errors="ignore"))
                self.on_chunk("stdout", payload)

        self.information_index = len(ps.streams.information)

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
    def _stringify(item: Any, *, _seen: Optional[Set[int]] = None) -> str:
        """Best-effort string conversion for PSRP data."""

        if item is None:
            return ""

        if _seen is None:
            _seen = set()

        obj_id = id(item)
        if obj_id in _seen:
            return ""

        _seen.add(obj_id)

        try:
            formatter = getattr(item, "to_string", None)
            if callable(formatter):
                try:
                    text = formatter()
                    if text:
                        return text
                except Exception:  # pragma: no cover - defensive logging
                    logger.debug("Failed to format PSRP object via to_string", exc_info=True)

            complex_text = _PSRPStreamCursor._stringify_complex(item, _seen)
            if complex_text:
                return complex_text

            textual = getattr(item, "to_string", None)
            if isinstance(textual, str) and textual.strip():
                return textual

            if hasattr(item, "value") and isinstance(getattr(item, "value"), str):
                return getattr(item, "value")

            return str(item)
        finally:
            _seen.discard(obj_id)

    @staticmethod
    def _stringify_information(record: Any) -> str:
        """Convert an information stream record into printable text."""

        message_data = getattr(record, "message_data", None)
        extracted = _PSRPStreamCursor._extract_information_message(message_data)
        if extracted:
            return extracted

        formatter = getattr(record, "to_string", None)
        if callable(formatter):
            try:
                text = formatter()
                if text:
                    return text
            except Exception:  # pragma: no cover - defensive logging
                logger.debug("Failed to format information record", exc_info=True)

        textual = getattr(record, "message", None)
        if isinstance(textual, str) and textual.strip():
            return textual.strip()

        return str(record)

    @staticmethod
    def _extract_information_message(message_data: Any) -> str:
        """Return friendly text from Write-Information/Write-Host payloads."""

        def _clean(value: str) -> str:
            return value.rstrip("\r\n")

        if message_data is None:
            return ""

        if isinstance(message_data, bytes):
            try:
                decoded = message_data.decode("utf-8")
            except UnicodeDecodeError:
                decoded = message_data.decode("utf-8", errors="ignore")
            if decoded.strip():
                return _clean(decoded)
            return ""

        if isinstance(message_data, str):
            if message_data.strip():
                return _clean(message_data)
            return ""

        if isinstance(message_data, dict):
            for key in ("message", "Message"):
                value = message_data.get(key)
                if isinstance(value, str) and value.strip():
                    return _clean(value)
            return ""

        message_attr = getattr(message_data, "message", None)
        if isinstance(message_attr, str) and message_attr.strip():
            return _clean(message_attr)

        for attr in ("Message", "Value"):
            value = getattr(message_data, attr, None)
            if isinstance(value, str) and value.strip():
                return _clean(value)

        adapted = getattr(message_data, "adapted_properties", None)
        if isinstance(adapted, dict):
            for key, value in adapted.items():
                if key.lower() == "message" and isinstance(value, str) and value.strip():
                    return _clean(value)

        property_sets = getattr(message_data, "property_sets", None)
        if isinstance(property_sets, list):
            for entry in property_sets:
                if not isinstance(entry, dict):
                    continue
                for key, value in entry.items():
                    if key.lower() == "message" and isinstance(value, str) and value.strip():
                        return _clean(value)

        return _PSRPStreamCursor._stringify(message_data)

    @staticmethod
    def _stringify_complex(item: Any, seen: Set[int]) -> str:
        """Render pypsrp complex objects by enumerating their properties."""

        def iter_property_dict(data: Any) -> Iterable[tuple[str, Any]]:
            if isinstance(data, dict):
                yield from data.items()
            return

        def iter_property_list(data: Any) -> Iterable[tuple[str, Any]]:
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        for key, value in entry.items():
                            yield key, value


        properties: list[tuple[str, Any]] = []

        property_sets = getattr(item, "property_sets", None)
        if property_sets:
            properties.extend(iter_property_list(property_sets))

        adapted = getattr(item, "adapted_properties", None)
        if adapted:
            properties.extend(iter_property_dict(adapted))

        extended = getattr(item, "extended_properties", None)
        if extended:
            properties.extend(iter_property_dict(extended))

        if not properties:
            return ""

        lines: list[str] = []
        for key, value in properties:
            value_text = _PSRPStreamCursor._coerce_property_value(value, seen)
            if not value_text:
                continue

            needs_block = "\n" in value_text or _PSRPStreamCursor._is_complex_like(value)
            if needs_block:
                indented = "\n".join(f"  {segment}" for segment in value_text.splitlines())
                formatted = f"\n{indented}"
            else:
                formatted = f" {value_text}"

            lines.append(f"{key}:{formatted}")

        return "\n".join(lines)

    @staticmethod
    def _is_complex_like(value: Any) -> bool:
        """Return True when the value exposes complex object metadata."""

        return any(
            hasattr(value, attr)
            for attr in ("adapted_properties", "extended_properties", "property_sets")
        )

    @staticmethod
    def _coerce_property_value(value: Any, seen: Set[int]) -> str:
        """Normalise nested property values into printable text."""

        if value is None:
            return ""

        if isinstance(value, (str, int, float, bool)):
            return str(value)

        if isinstance(value, (list, tuple, set)):
            parts = [
                _PSRPStreamCursor._coerce_property_value(element, seen)
                for element in value
            ]
            filtered = [part for part in parts if part]
            return ", ".join(filtered)

        if isinstance(value, dict):
            parts = []
            for key, nested in value.items():
                nested_text = _PSRPStreamCursor._coerce_property_value(nested, seen)
                if not nested_text:
                    continue
                parts.append(f"{key}={nested_text}")
            return ", ".join(parts)

        return _PSRPStreamCursor._stringify(value, _seen=seen).strip()

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
    _DEFAULT_CCACHE: str = "/tmp/aetherv_krb5_ccache"

    def __init__(self) -> None:
        self._kerberos_lock = threading.Lock()
        self._kerberos_ready = False
        self._kerberos_ccache: Optional[str] = None
        self._warned_klist_missing = False

    def initialize(self) -> None:
        """Ensure Kerberos credentials are available before serving requests."""

        try:
            self._ensure_kerberos_ticket()
        except WinRMAuthenticationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Kerberos initialization failed: %s", exc)
            raise

    def _ensure_kerberos_ticket(self) -> None:
        """Acquire or renew Kerberos credentials as needed."""

        with self._kerberos_lock:
            if self._kerberos_ready and self._kerberos_ccache:
                env = os.environ.copy()
                env["KRB5CCNAME"] = self._kerberos_ccache
                try:
                    result = subprocess.run(
                        ["klist", "-s"],
                        env=env,
                        capture_output=True,
                        check=False,
                    )
                except FileNotFoundError:
                    if not self._warned_klist_missing:
                        logger.warning(
                            "klist utility not found; Kerberos ticket freshness checks are disabled"
                        )
                        self._warned_klist_missing = True
                    return

                if result.returncode == 0:
                    return

                logger.warning(
                    "Kerberos ticket cache check failed (rc=%s); reinitializing credentials",
                    result.returncode,
                )
                self._kerberos_ready = False

            self._acquire_kerberos_ticket_locked()

    def _acquire_kerberos_ticket_locked(self) -> None:
        """Initialise Kerberos credentials using the configured keytab."""

        principal = (settings.winrm_kerberos_principal or "").strip()
        keytab_path_value = (settings.winrm_kerberos_keytab or "").strip()

        if not principal or not keytab_path_value:
            raise WinRMAuthenticationError(
                "Kerberos principal and keytab must be configured via WINRM_KERBEROS_PRINCIPAL and WINRM_KERBEROS_KEYTAB"
            )

        keytab_path = Path(keytab_path_value)
        if not keytab_path.is_file():
            raise WinRMAuthenticationError(
                f"Kerberos keytab not found at {keytab_path}. Ensure the Kubernetes secret is mounted."
            )

        ccache_value = (settings.winrm_kerberos_ccache or self._DEFAULT_CCACHE).strip()
        if not ccache_value:
            ccache_value = self._DEFAULT_CCACHE

        ccache_path = Path(ccache_value)
        try:
            ccache_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - filesystem permissions
            logger.warning(
                "Unable to pre-create Kerberos credential cache directory %s: %s", ccache_path.parent, exc
            )

        env = os.environ.copy()
        env["KRB5_CLIENT_KTNAME"] = str(keytab_path)
        env["KRB5CCNAME"] = str(ccache_path)

        logger.info(
            "Acquiring Kerberos ticket for %s using keytab %s (ccache=%s)",
            principal,
            keytab_path,
            ccache_path,
        )

        try:
            result = subprocess.run(
                ["kinit", "-k", "-t", str(keytab_path), principal],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise WinRMAuthenticationError(
                "kinit utility not found on PATH; install Kerberos user tools in the container"
            ) from exc

        if result.returncode != 0:
            error_output = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise WinRMAuthenticationError(
                f"Failed to initialize Kerberos credentials for {principal}: {error_output}"
            )

        os.environ["KRB5_CLIENT_KTNAME"] = env["KRB5_CLIENT_KTNAME"]
        os.environ["KRB5CCNAME"] = env["KRB5CCNAME"]
        self._kerberos_ccache = env["KRB5CCNAME"]
        self._kerberos_ready = True

        logger.info(
            "Kerberos ticket acquired successfully for %s; credentials cached at %s",
            principal,
            self._kerberos_ccache,
        )

    @contextmanager
    def _session(self, hostname: str) -> Iterator[RunspacePool]:
        """Yield an opened runspace pool for the target host."""

        wsman = self._create_session(hostname)
        pool = self._open_runspace_pool(hostname, wsman)
        try:
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
        return self._open_runspace_pool(hostname, wsman)

    def _create_session(self, hostname: str) -> WSMan:
        """Create a new WSMan session using configured credentials."""

        connection_timeout = int(max(1.0, float(settings.winrm_connection_timeout)))
        operation_timeout = int(max(1.0, float(settings.winrm_operation_timeout)))
        read_timeout = int(max(1.0, float(settings.winrm_read_timeout)))

        self._ensure_kerberos_ticket()

        selected_transport = "kerberos"
        logger.info(
            "Creating WinRM (PSRP) session to %s (port=%s, transport=%s, username=%s)",
            hostname,
            settings.winrm_port,
            selected_transport,
            settings.winrm_kerberos_principal or "<unspecified>",
        )
        logger.debug(
            "WSMan timeouts for %s -> connection=%ss, operation=%ss, read=%ss",
            hostname,
            connection_timeout,
            operation_timeout,
            read_timeout,
        )

        auth = selected_transport
        use_ssl = settings.winrm_port == 5986

        try:
            session = WSMan(
                hostname,
                port=settings.winrm_port,
                username=settings.winrm_kerberos_principal,
                auth=auth,
                ssl=use_ssl,
                cert_validation=False,
                connection_timeout=connection_timeout,
                operation_timeout=operation_timeout,
                read_timeout=read_timeout,
                kerberos_delegation=True,
            )
        except AuthenticationError as exc:  # pragma: no cover - network heavy
            logger.error("Authentication failed while connecting to %s: %s", hostname, exc)
            raise WinRMAuthenticationError(str(exc)) from exc
        except (PyWinRMTransportError, WinRMError) as exc:  # pragma: no cover - network heavy
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

    def execute_ps_command(self, hostname: str, command: str) -> tuple[str, str, int]:
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
        completed = False
        last_state_log = start_time
        last_state = None
        poll_timeout = int(
            max(1.0, min(float(settings.winrm_poll_interval_seconds), float(settings.winrm_operation_timeout)))
        )
        logger.debug(
            "Using poll interval of %ss for PowerShell invocation on %s (operation timeout=%ss)",
            poll_timeout,
            hostname,
            settings.winrm_operation_timeout,
        )
        try:
            ps.begin_invoke()
            while True:
                ps.poll_invoke(timeout=poll_timeout)
                cursor.drain(ps)
                state = getattr(ps, "state", None)
                normalized_state = self._normalize_state(state)
                if state != last_state:
                    logger.debug(
                        "PowerShell state for %s transitioned to %s",
                        hostname,
                        normalized_state,
                    )
                    last_state = state

                now = perf_counter()
                if now - last_state_log >= 5.0:
                    logger.debug(
                        "PowerShell invocation on %s still running (state=%s, had_errors=%s)",
                        hostname,
                        normalized_state,
                        getattr(ps, "had_errors", False),
                    )
                    last_state_log = now

                if self._state_complete(state):
                    break
            ps.end_invoke()
            completed = True
            cursor.drain(ps)
        except AuthenticationError as exc:  # pragma: no cover - network heavy
            logger.error("Authentication failure while executing command on %s: %s", hostname, exc)
            raise WinRMAuthenticationError(str(exc)) from exc
        except WinRMError as exc:  # pragma: no cover - network heavy
            logger.error("WinRM execution failed on %s: %s", hostname, exc)
            raise WinRMTransportError(str(exc)) from exc
        finally:
            if not completed:
                try:
                    ps.end_invoke()
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
            exit_code = 0 if not getattr(ps, "had_errors", False) else 1

        logger.debug(
            "PowerShell invocation on %s finished in %.2fs (state=%s, had_errors=%s)",
            hostname,
            duration,
            self._normalize_state(getattr(ps, "state", None)),
            getattr(ps, "had_errors", False),
        )

        return exit_code, duration

    @staticmethod
    def _normalize_state(state: object) -> str:
        """Return a normalized string representation of a PS invocation state."""

        if isinstance(state, PSInvocationState):
            return state.name.lower()
        if state is None:
            return "unknown"
        return str(state).lower()

    @staticmethod
    def _state_complete(state: object) -> bool:
        """Return True when the invocation state indicates completion."""

        terminal_states = {
            getattr(PSInvocationState, "COMPLETED", None),
            getattr(PSInvocationState, "FAILED", None),
            getattr(PSInvocationState, "STOPPED", None),
        }
        disconnected = getattr(PSInvocationState, "DISCONNECTED", None)
        if disconnected is not None:
            terminal_states.add(disconnected)

        normalized_terminals = {value for value in terminal_states if value is not None}
        if normalized_terminals and state in normalized_terminals:
            return True

        normalized = WinRMService._normalize_state(state)
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

    def _open_runspace_pool(self, hostname: str, wsman: WSMan) -> RunspacePool:
        """Open a runspace pool and translate connection errors."""

        start_time = perf_counter()
        pool = RunspacePool(wsman)
        try:
            pool.open()
        except AuthenticationError as exc:  # pragma: no cover - network heavy
            logger.error(
                "Authentication failure while opening runspace pool on %s: %s",
                hostname,
                exc,
            )
            self._dispose_session(wsman)
            raise WinRMAuthenticationError(str(exc)) from exc
        except (PyWinRMTransportError, WinRMError) as exc:  # pragma: no cover - network heavy
            logger.error(
                "Transport error while opening runspace pool on %s: %s",
                hostname,
                exc,
            )
            self._dispose_session(wsman)
            raise WinRMTransportError(str(exc)) from exc

        duration = perf_counter() - start_time
        logger.debug(
            "Runspace pool on %s opened in %.2fs (max_envelope=%s)",
            hostname,
            duration,
            getattr(pool, "max_envelope_size", "unknown"),
        )

        return pool


# Global WinRM service instance
winrm_service = WinRMService()

__all__ = [
    "WinRMService",
    "winrm_service",
    "WinRMAuthenticationError",
    "WinRMTransportError",
]
