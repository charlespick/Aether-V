"""Service for controlling Hyper-V virtual machines via WinRM."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VMActionResult:
    """Result payload for a VM control action."""

    stdout: str
    stderr: str


class VMControlError(RuntimeError):
    """Raised when a VM control action fails."""

    def __init__(self, action: str, hostname: str, vm_name: str, message: str):
        super().__init__(message)
        self.action = action
        self.hostname = hostname
        self.vm_name = vm_name
        self.message = message


class VMControlService:
    """Execute Hyper-V virtual machine lifecycle actions through WinRM."""

    async def start_vm(self, hostname: str, vm_name: str) -> VMActionResult:
        """Start a powered-off virtual machine."""

        command = self._format_command(
            "Start-VM",
            hostname,
            vm_name,
            extra_parameters="-Confirm:$false",
        )
        return await self._run_command(hostname, vm_name, "start", command)

    async def shutdown_vm(self, hostname: str, vm_name: str) -> VMActionResult:
        """Request a graceful shutdown of a virtual machine."""

        command = self._format_command(
            "Stop-VM",
            hostname,
            vm_name,
            extra_parameters="-Confirm:$false",
        )
        return await self._run_command(hostname, vm_name, "shutdown", command)

    async def stop_vm(self, hostname: str, vm_name: str) -> VMActionResult:
        """Immediately power off a virtual machine (turn off)."""

        command = self._format_command(
            "Stop-VM",
            hostname,
            vm_name,
            extra_parameters="-TurnOff -Confirm:$false",
        )
        return await self._run_command(hostname, vm_name, "stop", command)

    async def reset_vm(self, hostname: str, vm_name: str) -> VMActionResult:
        """Reset (power cycle) a running virtual machine."""

        command = self._format_command(
            "Restart-VM",
            hostname,
            vm_name,
            extra_parameters="-Force -Confirm:$false",
        )
        return await self._run_command(hostname, vm_name, "reset", command)

    async def _run_command(
        self, hostname: str, vm_name: str, action: str, command: str
    ) -> VMActionResult:
        """Execute a PowerShell command and return the result."""

        logger.info(
            "Executing %s action for VM %s on host %s", action, vm_name, hostname
        )
        try:
            stdout, stderr, exit_code = await asyncio.to_thread(
                winrm_service.execute_ps_command,
                hostname,
                command,
            )
        except Exception as exc:  # pragma: no cover - network failure surface
            logger.exception(
                "WinRM transport error while executing %s for %s on %s",
                action,
                vm_name,
                hostname,
            )
            raise VMControlError(
                action,
                hostname,
                vm_name,
                f"WinRM communication failed: {exc}",
            ) from exc

        stdout = stdout or ""
        stderr = stderr or ""

        if exit_code != 0:
            logger.error(
                "Command for action %s on VM %s (host %s) exited with %s", 
                action,
                vm_name,
                hostname,
                exit_code,
            )
            preview = stderr.strip() or stdout.strip()
            message = preview[:500] if preview else "Unknown error"
            raise VMControlError(action, hostname, vm_name, message)

        logger.info(
            "VM action %s for %s on %s completed successfully", action, vm_name, hostname
        )
        return VMActionResult(stdout=stdout, stderr=stderr)

    @staticmethod
    def _format_command(
        verb: str, hostname: str, vm_name: str, extra_parameters: str = ""
    ) -> str:
        """Format a PowerShell command for Hyper-V VM control."""

        host_arg = VMControlService._ps_single_quote(hostname)
        vm_arg = VMControlService._ps_single_quote(vm_name)

        parameter_segment = "-ComputerName $hostName -Name $vmName"
        if extra_parameters:
            parameter_segment = f"{parameter_segment} {extra_parameters.strip()}"

        command_lines = [
            "$ErrorActionPreference = 'Stop'",
            "$ProgressPreference = 'SilentlyContinue'",
            "Import-Module Hyper-V -ErrorAction Stop | Out-Null",
            "",
            f"$hostName = {host_arg}",
            f"$vmName = {vm_arg}",
            "",
            "try {",
            f"    {verb} {parameter_segment} -ErrorAction Stop | Out-Null",
            "} catch {",
            "    $message = $_.Exception.Message",
            "    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {",
            "        $message = $_.ErrorDetails.Message",
            "    } elseif ($_.FullyQualifiedErrorId) {",
            f"        $message = \"{verb} failed: \" + $_.FullyQualifiedErrorId",
            "    }",
            "    throw $message",
            "}",
        ]

        return "\n".join(command_lines)

    @staticmethod
    def _ps_single_quote(value: str) -> str:
        """Quote a string for inclusion in a PowerShell single-quoted literal."""

        escaped = (value or "").replace("'", "''")
        return f"'{escaped}'"


# Global service instance
vm_control_service = VMControlService()

__all__ = [
    "VMActionResult",
    "VMControlError",
    "VMControlService",
    "vm_control_service",
]
