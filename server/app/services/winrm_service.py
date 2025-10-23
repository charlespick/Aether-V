"""WinRM service for executing PowerShell commands on Hyper-V hosts."""
import logging
from typing import Any, Callable, Dict, Optional
import winrm
from winrm.protocol import Protocol

from ..core.config import settings

logger = logging.getLogger(__name__)


class WinRMService:
    """Service for managing WinRM connections to Hyper-V hosts."""
    
    def __init__(self):
        self._sessions: Dict[str, Protocol] = {}
    
    def get_session(self, hostname: str) -> Protocol:
        """Get or create a WinRM session for a host."""
        if hostname not in self._sessions:
            self._sessions[hostname] = self._create_session(hostname)
        return self._sessions[hostname]
    
    def _create_session(self, hostname: str) -> Protocol:
        """Create a new WinRM session."""
        logger.info(f"Creating WinRM session to {hostname}")
        
        endpoint = f"http://{hostname}:{settings.winrm_port}/wsman"
        
        session = Protocol(
            endpoint=endpoint,
            transport=settings.winrm_transport,
            username=settings.winrm_username,
            password=settings.winrm_password,
            server_cert_validation='ignore'
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
        
        logger.info(f"Executing on {hostname}: {command}")
        
        try:
            shell_id = session.open_shell()
            command_id = session.run_command(shell_id, command)
            stdout, stderr, exit_code = session.get_command_output(shell_id, command_id)
            session.cleanup_command(shell_id, command_id)
            session.close_shell(shell_id)
            
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""
            
            logger.info(f"Command completed with exit code: {exit_code}")
            if stderr_str:
                logger.warning(f"Command stderr: {stderr_str}")
            
            return stdout_str, stderr_str, exit_code
        
        except Exception as e:
            logger.error(f"WinRM execution failed on {hostname}: {e}")
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
        
        logger.info(f"Executing command on {hostname}: {command[:100]}...")
        
        try:
            shell_id = session.open_shell()
            command_id = session.run_command(shell_id, f"powershell.exe -Command \"{command}\"")
            stdout, stderr, exit_code = session.get_command_output(shell_id, command_id)
            session.cleanup_command(shell_id, command_id)
            session.close_shell(shell_id)
            
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""
            
            return stdout_str, stderr_str, exit_code
        
        except Exception as e:
            logger.error(f"WinRM command execution failed on {hostname}: {e}")
            raise

    def stream_ps_command(
        self,
        hostname: str,
        command: str,
        on_chunk: Callable[[str, str], None],
    ) -> int:
        """Execute a PowerShell command and stream output via callback."""
        session = self.get_session(hostname)

        logger.info(f"Streaming command on {hostname}: {command[:100]}...")

        shell_id = session.open_shell()
        command_id = session.run_command(shell_id, f"powershell.exe -Command \"{command}\"")

        exit_code = 0
        try:
            command_done = False
            while not command_done:
                stdout, stderr, exit_code, command_done = session.receive(shell_id, command_id)
                if stdout:
                    on_chunk('stdout', stdout.decode('utf-8', errors='replace'))
                if stderr:
                    on_chunk('stderr', stderr.decode('utf-8', errors='replace'))
        except Exception as exc:
            logger.error(f"WinRM streaming execution failed on {hostname}: {exc}")
            raise
        finally:
            try:
                session.cleanup_command(shell_id, command_id)
            finally:
                session.close_shell(shell_id)

        return exit_code


# Global WinRM service instance
winrm_service = WinRMService()
