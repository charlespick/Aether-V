"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
import logging
from base64 import b64encode
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

from winrm.exceptions import WinRMOperationTimeoutError
from winrm.protocol import Protocol

from ..core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class _WinRMStreamState:
    """Track streaming progress and provide consistent logging."""

    hostname: str
    command_id: str
    on_chunk: Callable[[str, str], None]
    stdout_sent: int = 0
    stderr_sent: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_chunks: int = 0
    stderr_chunks: int = 0
    timeouts: int = 0
    last_stream_activity: float = field(default_factory=perf_counter)

    def process(self, stream_name: str, payload: bytes) -> None:
        """Send only the newly observed bytes for the given stream."""

        if not payload:
            return

        if stream_name == "stdout":
            new_payload, total_sent = self._extract_new_bytes(payload, self.stdout_sent)
            if not new_payload:
                return
            self.stdout_sent = total_sent
            self.stdout_bytes += len(new_payload)
            self.stdout_chunks += 1
            chunk_index = self.stdout_chunks
        else:
            new_payload, total_sent = self._extract_new_bytes(payload, self.stderr_sent)
            if not new_payload:
                return
            self.stderr_sent = total_sent
            self.stderr_bytes += len(new_payload)
            self.stderr_chunks += 1
            chunk_index = self.stderr_chunks

        decoded = new_payload.decode("utf-8", errors="replace")
        self.on_chunk(stream_name, decoded)
        self.last_stream_activity = perf_counter()
        logger.debug(
            "Streamed %d %s bytes from %s for command %s (chunk #%d)",
            len(new_payload),
            stream_name,
            self.hostname,
            self.command_id,
            chunk_index,
        )

    def register_timeout(self) -> None:
        """Record a WinRM operation timeout while waiting for output."""

        self.timeouts += 1
        idle = perf_counter() - self.last_stream_activity
        logger.debug(
            "WinRM streaming timeout while waiting for output from %s (command=%s, idle=%.2fs, timeouts=%d)",
            self.hostname,
            self.command_id,
            idle,
            self.timeouts,
        )

    def log_summary(self, exit_code: Optional[int], duration: float) -> None:
        """Emit a summary of the streamed session."""

        logger.info(
            "Streaming PowerShell command %s on %s finished (exit_code=%s, duration=%.2fs, stdout=%d bytes in %d chunks, stderr=%d bytes in %d chunks, timeouts=%d)",
            self.command_id,
            self.hostname,
            exit_code if exit_code is not None else "<unknown>",
            duration,
            self.stdout_bytes,
            self.stdout_chunks,
            self.stderr_bytes,
            self.stderr_chunks,
            self.timeouts,
        )

    @staticmethod
    def _extract_new_bytes(payload: bytes, total_sent: int) -> tuple[bytes, int]:
        """Return bytes that have not yet been emitted for a stream."""

        payload_length = len(payload)
        if payload_length < total_sent:
            # Some WinRM providers only return the newest bytes. Treat the payload
            # as fresh data and advance the sent counter incrementally.
            return payload, total_sent + payload_length

        new_payload = payload[total_sent:]
        return new_payload, payload_length


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

    _BASE_POWERSHELL_ARGS: tuple[str, ...] = (
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
    )

    @contextmanager
    def _session(self, hostname: str) -> Iterator[Protocol]:
        """Yield a fresh WinRM protocol session for a host."""

        session = self._create_session(hostname)
        try:
            yield session
        finally:
            self._dispose_session(session)

    def _open_powershell_shell(
        self,
        session: Protocol,
        hostname: str,
        *,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> str:
        """Open a PowerShell-friendly shell for the given session."""
        normalized_env = None
        if env_vars:
            normalized_env = {key: str(value) for key, value in env_vars.items()}

        shell_id = session.open_shell(codepage=65001, env_vars=normalized_env)
        logger.debug("Opened PowerShell shell %s on %s", shell_id, hostname)
        return shell_id

    @classmethod
    def _build_powershell_command(
        cls, additional_args: Iterable[str]
    ) -> list[str]:
        """Create a full PowerShell command line for execution."""
        command = list(cls._BASE_POWERSHELL_ARGS)
        command.extend(additional_args)
        return command

    def _run_powershell_command(
        self,
        session: Protocol,
        hostname: str,
        args: Iterable[str],
        *,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> tuple[bytes, bytes, int]:
        """Execute a PowerShell command and return the raw outputs."""
        shell_id = self._open_powershell_shell(session, hostname, env_vars=env_vars)
        try:
            command_args = list(args)
            command_id = session.run_command(
                shell_id,
                "powershell.exe",
                command_args,
                skip_cmd_shell=True,
            )
            logger.debug(
                "Started PowerShell command %s on shell %s (%s)",
                command_id,
                shell_id,
                hostname,
            )
            stdout, stderr, exit_code = session.get_command_output(shell_id, command_id)
            session.cleanup_command(shell_id, command_id)
            return stdout, stderr, exit_code
        finally:
            session.close_shell(shell_id)

    def _stream_powershell_command(
        self,
        session: Protocol,
        hostname: str,
        args: Iterable[str],
        on_chunk: Callable[[str, str], None],
    ) -> tuple[int, float]:
        """Execute a PowerShell command and stream output via callback."""
        shell_id = self._open_powershell_shell(session, hostname)
        command_args = list(args)
        command_id = session.run_command(
            shell_id,
            "powershell.exe",
            command_args,
            skip_cmd_shell=True,
        )
        logger.debug(
            "Started streaming PowerShell command %s on shell %s (%s)",
            command_id,
            shell_id,
            hostname,
        )

        stream_state = _WinRMStreamState(
            hostname=hostname,
            command_id=command_id,
            on_chunk=on_chunk,
        )
        exit_code: Optional[int] = None
        start_time = perf_counter()
        try:
            command_done = False
            while not command_done:
                try:
                    stdout, stderr, chunk_exit_code, command_done = self._get_command_output_raw(
                        session,
                        shell_id,
                        command_id,
                    )
                except WinRMOperationTimeoutError:
                    # Long-running commands trigger timeout exceptions while still executing.
                    # Keep waiting for more output.
                    stream_state.register_timeout()
                    continue

                stream_state.process("stdout", stdout)
                stream_state.process("stderr", stderr)
                if command_done:
                    exit_code = chunk_exit_code
        finally:
            try:
                session.cleanup_command(shell_id, command_id)
            finally:
                session.close_shell(shell_id)
        duration = perf_counter() - start_time
        stream_state.log_summary(exit_code, duration)
        return exit_code or 0, duration

    @staticmethod
    def _get_command_output_raw(
        session: Protocol, shell_id: str, command_id: str
    ) -> tuple[bytes, bytes, int, bool]:
        """Retrieve the next chunk of command output using available APIs."""

        getter = getattr(session, "get_command_output_raw", None)
        if getter is None:
            getter = getattr(session, "_raw_get_command_output")
        return getter(shell_id, command_id)

    def get_session(self, hostname: str) -> Protocol:
        """Return a brand new WinRM session for a host."""

        logger.debug("Creating new WinRM session for %s", hostname)
        return self._create_session(hostname)

    def _create_session(self, hostname: str) -> Protocol:
        """Create a new WinRM session."""
        endpoint = f"http://{hostname}:{settings.winrm_port}/wsman"
        logger.info(
            "Creating WinRM session to %s (endpoint=%s, transport=%s, username=%s)",
            hostname,
            endpoint,
            settings.winrm_transport,
            settings.winrm_username or "<anonymous>",
        )

        session = Protocol(
            endpoint=endpoint,
            transport=settings.winrm_transport,
            username=settings.winrm_username,
            password=settings.winrm_password,
            server_cert_validation='ignore'
        )

        logger.debug(
            "Created WinRM session to %s; keepalive timeout=%s; locale=%s",
            hostname,
            getattr(session, "timeout", "unknown"),
            getattr(session, "locale", "unknown"),
        )
        return session
    
    def close_session(self, hostname: str):
        """Close cached WinRM sessions (no-op for per-operation sessions)."""

        logger.debug("close_session called for %s, but sessions are not cached", hostname)

    def close_all_sessions(self):
        """Close all WinRM sessions (no-op for per-operation sessions)."""

        logger.debug("close_all_sessions called, but sessions are not cached")
    
    def execute_ps_script(
        self,
        hostname: str,
        script_path: str,
        parameters: Dict[str, Any],
        environment: Optional[Dict[str, str]] = None
    ) -> tuple[str, str, int]:
        """
        Execute a PowerShell script on a remote host.
        
        Args:
            hostname: Target Hyper-V host
            script_path: Path to PowerShell script on the host
            parameters: Script parameters as key-value pairs
            environment: Environment variables to set
        
        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        with self._session(hostname) as session:

            # Build PowerShell command
            param_args: list[str] = []
            for key, value in parameters.items():
                if value is None:
                    continue

                flag = f"-{key}"
                if isinstance(value, bool):
                    if value:
                        param_args.append(flag)
                elif isinstance(value, (int, float)):
                    param_args.extend([flag, str(value)])
                elif isinstance(value, str):
                    escaped_value = value.replace('"', '`"')
                    param_args.extend([flag, f'"{escaped_value}"'])

            escaped_path = script_path.replace('"', '`"')
            ps_args = self._build_powershell_command(
                ["-File", f'"{escaped_path}"', *param_args]
            )

            logger.info("Executing PowerShell script on %s", hostname)
            logger.debug(
                "Script invocation on %s -> path=%s params=%s env=%s",
                hostname,
                script_path,
                parameters,
                environment,
            )
            logger.debug(
                "Full rendered script command for %s: powershell.exe %s",
                hostname,
                " ".join(ps_args),
            )

            try:
                start_time = perf_counter()
                stdout, stderr, exit_code = self._run_powershell_command(
                    session,
                    hostname,
                    ps_args,
                    env_vars=environment,
                )
                duration = perf_counter() - start_time

                stdout_str = stdout.decode('utf-8') if stdout else ""
                stderr_str = stderr.decode('utf-8') if stderr else ""

                stdout_preview = _format_output_preview(stdout_str)
                stderr_preview = _format_output_preview(stderr_str)

                logger.info(
                    "Script on %s completed in %.2fs with exit code %s (stdout=%d bytes, stderr=%d bytes)",
                    hostname,
                    duration,
                    exit_code,
                    len(stdout or b""),
                    len(stderr or b""),
                )
                if stdout_preview:
                    logger.info("Script stdout preview on %s:%s", hostname, stdout_preview)
                else:
                    logger.info("Script stdout on %s was empty", hostname)

                if stderr_preview:
                    logger.warning("Script stderr preview on %s:%s", hostname, stderr_preview)
                else:
                    logger.info("Script stderr on %s was empty", hostname)

                return stdout_str, stderr_str, exit_code

            except Exception as e:
                logger.exception("WinRM script execution failed on %s", hostname)
                raise
    
    def execute_ps_command(
        self,
        hostname: str,
        command: str
    ) -> tuple[str, str, int]:
        """
        Execute a PowerShell command directly.
        
        Args:
            hostname: Target Hyper-V host
            command: PowerShell command to execute
        
        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        with self._session(hostname) as session:

            truncated_command = command.replace("\n", " ")
            if len(truncated_command) > 120:
                truncated_command = f"{truncated_command[:117]}..."
            logger.info("Executing PowerShell command on %s: %s", hostname, truncated_command)
            logger.debug("Full PowerShell command on %s: %s", hostname, command)

            encoded_command = b64encode(command.encode('utf-16le')).decode('ascii')
            ps_args = self._build_powershell_command(["-EncodedCommand", encoded_command])

            try:
                start_time = perf_counter()
                stdout, stderr, exit_code = self._run_powershell_command(
                    session,
                    hostname,
                    ps_args,
                )
                duration = perf_counter() - start_time

                stdout_str = stdout.decode('utf-8') if stdout else ""
                stderr_str = stderr.decode('utf-8') if stderr else ""
                stdout_preview = _format_output_preview(stdout_str)
                stderr_preview = _format_output_preview(stderr_str)

                logger.info(
                    "Command on %s completed in %.2fs with exit code %s (stdout=%d bytes, stderr=%d bytes)",
                    hostname,
                    duration,
                    exit_code,
                    len(stdout or b""),
                    len(stderr or b""),
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
                    logger.warning(
                        "Command on %s exited with non-zero status %s", hostname, exit_code
                    )

                return stdout_str, stderr_str, exit_code

            except Exception as e:
                logger.exception("WinRM command execution failed on %s", hostname)
                raise

    def stream_ps_command(
        self,
        hostname: str,
        command: str,
        on_chunk: Callable[[str, str], None],
    ) -> int:
        """Execute a PowerShell command and stream output via callback."""
        with self._session(hostname) as session:

            truncated_command = command.replace("\n", " ")
            if len(truncated_command) > 120:
                truncated_command = f"{truncated_command[:117]}..."
            logger.info("Streaming PowerShell command on %s: %s", hostname, truncated_command)
            logger.debug("Full streaming PowerShell command on %s: %s", hostname, command)

            encoded_command = b64encode(command.encode('utf-16le')).decode('ascii')
            ps_args = self._build_powershell_command(["-EncodedCommand", encoded_command])

            try:
                exit_code, duration = self._stream_powershell_command(
                    session,
                    hostname,
                    ps_args,
                    on_chunk,
                )
            except Exception as exc:
                logger.exception("WinRM streaming execution failed on %s", hostname)
                raise
            logger.info(
                "Streaming command on %s completed in %.2fs with exit code %s",
                hostname,
                duration,
                exit_code,
            )

            return exit_code


    def _dispose_session(self, session: Protocol):
        """Attempt to close transport resources for a WinRM session."""

        transport = getattr(session, "transport", None)
        close = getattr(transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("Failed to close WinRM transport cleanly")


# Global WinRM service instance
winrm_service = WinRMService()
