"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
import logging
from base64 import b64encode
from contextlib import contextmanager
from threading import RLock
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, Optional

from winrm.protocol import Protocol

from ..core.config import settings

logger = logging.getLogger(__name__)


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

    def __init__(self):
        self._sessions: Dict[str, Protocol] = {}
        self._session_locks: Dict[str, RLock] = {}
        self._locks_guard = RLock()

    def _get_host_lock(self, hostname: str) -> RLock:
        """Return a re-entrant lock guarding the session for the host."""

        with self._locks_guard:
            lock = self._session_locks.get(hostname)
            if lock is None:
                lock = RLock()
                self._session_locks[hostname] = lock
            return lock

    @contextmanager
    def _host_session(self, hostname: str):
        """Serialize access to a host's WinRM session."""

        lock = self._get_host_lock(hostname)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

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

        exit_code = 0
        start_time = perf_counter()
        try:
            command_done = False
            while not command_done:
                stdout, stderr, exit_code, command_done = session.receive(shell_id, command_id)
                if stdout:
                    on_chunk('stdout', stdout.decode('utf-8', errors='replace'))
                    logger.debug(
                        "Received %d stdout bytes from %s (streaming)",
                        len(stdout),
                        hostname,
                    )
                if stderr:
                    on_chunk('stderr', stderr.decode('utf-8', errors='replace'))
                    logger.debug(
                        "Received %d stderr bytes from %s (streaming)",
                        len(stderr),
                        hostname,
                    )
        finally:
            try:
                session.cleanup_command(shell_id, command_id)
            finally:
                session.close_shell(shell_id)
        duration = perf_counter() - start_time
        return exit_code, duration

    def get_session(self, hostname: str) -> Protocol:
        """Get or create a WinRM session for a host."""
        if hostname not in self._sessions:
            logger.debug("No cached WinRM session for %s; creating new session", hostname)
            self._sessions[hostname] = self._create_session(hostname)
        else:
            logger.debug("Reusing cached WinRM session for %s", hostname)
        return self._sessions[hostname]

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
        """Close a WinRM session."""

        with self._host_session(hostname):
            if hostname in self._sessions:
                logger.info(f"Closing WinRM session to {hostname}")
                del self._sessions[hostname]
    
    def close_all_sessions(self):
        """Close all WinRM sessions."""
        logger.info("Closing all WinRM sessions")
        with self._locks_guard:
            self._sessions.clear()
            self._session_locks.clear()
    
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
        with self._host_session(hostname):
            session = self.get_session(hostname)

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
        with self._host_session(hostname):
            session = self.get_session(hostname)

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
        with self._host_session(hostname):
            session = self.get_session(hostname)

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


# Global WinRM service instance
winrm_service = WinRMService()
