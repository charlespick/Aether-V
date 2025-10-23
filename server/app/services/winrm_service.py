"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
import logging
from time import perf_counter
from typing import Any, Callable, Dict, Optional
import winrm
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
    
    def __init__(self):
        self._sessions: Dict[str, Protocol] = {}
    
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
        if hostname in self._sessions:
            logger.info(f"Closing WinRM session to {hostname}")
            del self._sessions[hostname]
    
    def close_all_sessions(self):
        """Close all WinRM sessions."""
        logger.info("Closing all WinRM sessions")
        self._sessions.clear()
    
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
        session = self.get_session(hostname)
        
        # Build PowerShell command
        param_args = []
        for key, value in parameters.items():
            if value is None:
                continue
            
            # Handle different value types
            if isinstance(value, bool):
                if value:
                    param_args.append(f"-{key}")
            elif isinstance(value, (int, float)):
                param_args.append(f"-{key} {value}")
            elif isinstance(value, str):
                # Escape quotes in string values
                escaped_value = value.replace('"', '`"')
                param_args.append(f'-{key} "{escaped_value}"')
        
        param_str = " ".join(param_args)
        
        # Build environment variable settings
        env_str = ""
        if environment:
            env_vars = "; ".join([f"$env:{k} = '{v}'" for k, v in environment.items()])
            env_str = f"{env_vars}; "
        
        command = (
            f"{env_str}"
            f"powershell.exe -ExecutionPolicy Bypass -File \"{script_path}\" {param_str}"
        )
        
        logger.info("Executing PowerShell script on %s", hostname)
        logger.debug(
            "Script invocation on %s -> path=%s params=%s env=%s",
            hostname,
            script_path,
            parameters,
            environment,
        )
        logger.debug("Full rendered script command for %s: %s", hostname, command)

        try:
            start_time = perf_counter()
            shell_id = session.open_shell()
            logger.debug("Opened shell %s on %s", shell_id, hostname)
            command_id = session.run_command(shell_id, command)
            logger.debug("Started command %s on shell %s (%s)", command_id, shell_id, hostname)
            stdout, stderr, exit_code = session.get_command_output(shell_id, command_id)
            session.cleanup_command(shell_id, command_id)
            session.close_shell(shell_id)
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
        session = self.get_session(hostname)
        
        truncated_command = command.replace("\n", " ")
        if len(truncated_command) > 120:
            truncated_command = f"{truncated_command[:117]}..."
        logger.info("Executing PowerShell command on %s: %s", hostname, truncated_command)
        logger.debug("Full PowerShell command on %s: %s", hostname, command)

        try:
            start_time = perf_counter()
            shell_id = session.open_shell()
            logger.debug("Opened shell %s on %s", shell_id, hostname)
            command_id = session.run_command(shell_id, f"powershell.exe -Command \"{command}\"")
            logger.debug("Started command %s on shell %s (%s)", command_id, shell_id, hostname)
            stdout, stderr, exit_code = session.get_command_output(shell_id, command_id)
            session.cleanup_command(shell_id, command_id)
            session.close_shell(shell_id)
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
        session = self.get_session(hostname)

        truncated_command = command.replace("\n", " ")
        if len(truncated_command) > 120:
            truncated_command = f"{truncated_command[:117]}..."
        logger.info("Streaming PowerShell command on %s: %s", hostname, truncated_command)
        logger.debug("Full streaming PowerShell command on %s: %s", hostname, command)

        shell_id = session.open_shell()
        logger.debug("Opened streaming shell %s on %s", shell_id, hostname)
        command_id = session.run_command(shell_id, f"powershell.exe -Command \"{command}\"")
        logger.debug("Started streaming command %s on shell %s (%s)", command_id, shell_id, hostname)

        exit_code = 0
        try:
            start_time = perf_counter()
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
        except Exception as exc:
            logger.exception("WinRM streaming execution failed on %s", hostname)
            raise
        finally:
            try:
                session.cleanup_command(shell_id, command_id)
            finally:
                session.close_shell(shell_id)
            duration = perf_counter() - start_time
            logger.info(
                "Streaming command on %s completed in %.2fs with exit code %s",
                hostname,
                duration,
                exit_code,
            )

        return exit_code


# Global WinRM service instance
winrm_service = WinRMService()
