"""Service for deploying scripts and ISOs to Hyper-V hosts."""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from winrm.exceptions import InvalidCredentialsError, WinRMTransportError

from ..core.config import settings
from ..core.models import NotificationLevel
from .notification_service import notification_service
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)

@dataclass
class StartupDeploymentProgress:
    """Track aggregate progress of the startup agent deployment."""

    status: str = "idle"
    total_hosts: int = 0
    completed_hosts: int = 0
    successful_hosts: int = 0
    failed_hosts: int = 0
    provisioning_available: bool = True
    last_error: Optional[str] = None
    per_host: Dict[str, str] = field(default_factory=dict)

    def copy(self) -> "StartupDeploymentProgress":
        return StartupDeploymentProgress(
            status=self.status,
            total_hosts=self.total_hosts,
            completed_hosts=self.completed_hosts,
            successful_hosts=self.successful_hosts,
            failed_hosts=self.failed_hosts,
            provisioning_available=self.provisioning_available,
            last_error=self.last_error,
            per_host=dict(self.per_host),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "total_hosts": self.total_hosts,
            "completed_hosts": self.completed_hosts,
            "successful_hosts": self.successful_hosts,
            "failed_hosts": self.failed_hosts,
            "provisioning_available": self.provisioning_available,
            "last_error": self.last_error,
            "per_host": dict(self.per_host),
        }


class HostDeploymentService:
    """Service for deploying artifacts (scripts and ISOs) to Hyper-V hosts."""

    def __init__(self):
        self._container_version: str = ""
        self._agent_download_base_url: Optional[str] = None
        self._deployment_enabled = self._initialize_agent_download_base_url()
        self._load_container_version()
        self._startup_task: Optional[asyncio.Task[None]] = None
        self._startup_event: Optional[asyncio.Event] = None
        self._startup_progress = StartupDeploymentProgress()
        self._startup_lock = asyncio.Lock()
        self._progress_lock = asyncio.Lock()

    def _initialize_agent_download_base_url(self) -> bool:
        """Resolve and cache the agent download base URL if configured."""

        base_url = settings.get_agent_download_base_url()
        if not base_url:
            logger.warning(
                "AGENT_DOWNLOAD_BASE_URL is not configured; host deployments are disabled."
            )
            return False

        self._agent_download_base_url = base_url
        logger.info("Host deployment service configured with agent download endpoint %s", base_url)
        return True

    @property
    def is_enabled(self) -> bool:
        """Return True when host deployments are permitted."""

        return self._deployment_enabled
    
    def _load_container_version(self):
        """Load version from container artifacts."""
        version_file = settings.version_file_path
        try:
            with open(version_file, 'r') as f:
                self._container_version = f.read().strip()
            logger.info(f"Container version: {self._container_version}")
        except Exception as e:
            logger.error(f"Failed to load container version: {e}")
            self._container_version = "0.0.0"
    
    def get_container_version(self) -> str:
        """Get the container version."""
        return self._container_version
    
    async def ensure_host_setup(self, hostname: str) -> bool:
        """
        Ensure host has correct scripts and ISOs deployed.
        
        Args:
            hostname: Target Hyper-V host
            
        Returns:
            True if setup successful, False otherwise
        """
        logger.info(f"Ensuring host setup for {hostname}")

        try:
            # Check host version in a worker thread because it performs network I/O
            host_version = await asyncio.to_thread(self._get_host_version, hostname)
            logger.info(f"Host {hostname} version: {host_version}")

            if self._needs_update(host_version):
                logger.info(
                    f"Host {hostname} needs update from {host_version} to {self._container_version}"
                )
                return await asyncio.to_thread(self._deploy_to_host, hostname)

            logger.info(f"Host {hostname} is up-to-date")
            return True

        except Exception as e:
            logger.error(f"Failed to ensure host setup for {hostname}: {e}")
            return False
    
    def _get_host_version(self, hostname: str) -> str:
        """Get the version currently deployed on a host."""
        version_file_path = f"{settings.host_install_directory}\\version"
        
        command = f"Get-Content -Path '{version_file_path}' -ErrorAction SilentlyContinue"
        
        try:
            stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)

            if exit_code == 0 and stdout.strip():
                return stdout.strip()
            else:
                # Version file doesn't exist, return 0.0.0
                return "0.0.0"
        except InvalidCredentialsError as exc:
            winrm_service.close_session(hostname)
            logger.error(
                "Authentication failed while retrieving agent version for %s: %s",
                hostname,
                exc,
            )
            raise
        except WinRMTransportError as exc:
            winrm_service.close_session(hostname)
            logger.error(
                "WinRM transport error while retrieving agent version for %s: %s",
                hostname,
                exc,
            )
            raise
        except Exception as e:
            logger.warning(f"Failed to get host version for {hostname}: {e}")
            return "0.0.0"
    
    def _needs_update(self, host_version: str) -> bool:
        """Check if host needs to be updated."""
        if host_version == "0.0.0":
            return True
        
        try:
            # Parse versions as semantic version tuples
            host_parts = [int(x) for x in host_version.split('.')]
            container_parts = [int(x) for x in self._container_version.split('.')]
            
            # Compare versions
            return container_parts > host_parts
        except Exception as e:
            logger.warning(f"Version comparison failed: {e}, forcing update")
            return True
    
    def _deploy_to_host(self, hostname: str) -> bool:
        """Deploy scripts and ISOs to a host."""
        logger.info(f"Starting deployment to {hostname}")

        try:
            if not self._deployment_enabled:
                logger.warning(
                    "Host deployment service is disabled; skipping deployment to %s",
                    hostname,
                )
                return False

            script_files = self._collect_script_files()
            iso_files = self._collect_iso_files()
            version_path = Path(settings.version_file_path)

            if not version_path.exists():
                logger.error(f"Version file not found at {version_path}")
                return False

            expected_artifacts: List[str] = [path.name for path in script_files]
            expected_artifacts.extend(path.name for path in iso_files)
            expected_artifacts.append(version_path.name)

            # Create installation directory
            if not self._ensure_install_directory(hostname):
                return False

            if not self._clear_host_install_directory(hostname):
                return False

            if not self._verify_install_directory_empty(hostname):
                return False

            # Deploy scripts
            if not self._deploy_scripts(hostname, script_files):
                return False

            # Deploy ISOs
            if not self._deploy_isos(hostname, iso_files):
                return False

            # Deploy version file
            if not self._deploy_version_file(hostname):
                return False

            if not self._verify_expected_artifacts_present(hostname, expected_artifacts):
                return False

            logger.info(f"Deployment to {hostname} completed successfully")
            return True

        except Exception as e:
            logger.error(f"Deployment to {hostname} failed: {e}")
            return False
    
    def _ensure_install_directory(self, hostname: str) -> bool:
        """Ensure the installation directory exists on the host."""
        install_dir = settings.host_install_directory
        
        command = f"New-Item -ItemType Directory -Path '{install_dir}' -Force | Out-Null"
        
        try:
            _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            
            if exit_code != 0:
                logger.error(f"Failed to create directory on {hostname}: {stderr}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to ensure install directory on {hostname}: {e}")
            return False
    
    def _deploy_scripts(self, hostname: str, script_files: Sequence[Path]) -> bool:
        """Deploy PowerShell scripts to host."""
        logger.info(f"Deploying scripts to {hostname}")

        script_dir = Path(settings.agent_artifacts_path)

        try:
            if not script_files:
                logger.warning(f"No script files found in {script_dir}")
                return True

            logger.info(f"Found {len(script_files)} scripts to deploy")

            for script_file in script_files:
                remote_path = self._build_remote_path(script_file.name)

                if not self._download_file_to_host(hostname, script_file.name, remote_path):
                    logger.error(f"Failed to deploy script {script_file.name} to {hostname}")
                    return False

                logger.debug(f"Deployed {script_file.name} to {hostname}")

            logger.info(f"All scripts deployed to {hostname}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deploy scripts to {hostname}: {e}")
            return False
    
    def _deploy_isos(self, hostname: str, iso_files: Sequence[Path]) -> bool:
        """Deploy ISO files to host."""
        logger.info(f"Deploying ISOs to {hostname}")

        iso_dir = Path(settings.agent_artifacts_path)

        try:
            if not iso_files:
                logger.warning(f"No ISO files found in {iso_dir}")
                return False

            logger.info(f"Found {len(iso_files)} ISOs to deploy")

            for iso_file in iso_files:
                remote_path = self._build_remote_path(iso_file.name)

                if not self._download_file_to_host(hostname, iso_file.name, remote_path):
                    logger.error(f"Failed to deploy ISO {iso_file.name} to {hostname}")
                    return False

                logger.info(f"Deployed {iso_file.name} to {hostname}")

            logger.info(f"All ISOs deployed to {hostname}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deploy ISOs to {hostname}: {e}")
            return False
    
    def _deploy_version_file(self, hostname: str) -> bool:
        """Deploy version file to host."""
        logger.info(f"Deploying version file to {hostname}")

        version_path = Path(settings.version_file_path)
        if not version_path.exists():
            logger.error(f"Version file not found at {version_path}")
            return False

        remote_path = self._build_remote_path(version_path.name)

        try:
            return self._download_file_to_host(hostname, version_path.name, remote_path)
        except Exception as e:
            logger.error(f"Failed to deploy version file to {hostname}: {e}")
            return False

    def _collect_script_files(self) -> List[Path]:
        """Return all PowerShell scripts available for deployment."""

        artifact_dir = Path(settings.agent_artifacts_path)

        if not artifact_dir.exists():
            logger.error(f"Agent artifacts directory does not exist: {artifact_dir}")
            return []

        return sorted(path for path in artifact_dir.glob('*.ps1') if path.is_file())

    def _collect_iso_files(self) -> List[Path]:
        """Return all ISO files available for deployment."""

        artifact_dir = Path(settings.agent_artifacts_path)

        if not artifact_dir.exists():
            logger.error(f"Agent artifacts directory does not exist: {artifact_dir}")
            return []

        return sorted(path for path in artifact_dir.glob('*.iso') if path.is_file())

    def _clear_host_install_directory(self, hostname: str) -> bool:
        """Remove all files from the host installation directory."""

        install_dir = settings.host_install_directory
        command = (
            "$ErrorActionPreference = 'Stop'; "
            f"$installDir = {self._ps_literal(install_dir)}; "
            "if (-not (Test-Path -LiteralPath $installDir)) {"
            "    New-Item -ItemType Directory -Path $installDir -Force | Out-Null"
            "} "
            "Get-ChildItem -LiteralPath $installDir -Force -ErrorAction Stop | Remove-Item -Force -Recurse -ErrorAction Stop"
        )

        _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)

        if exit_code != 0:
            logger.error(f"Failed to clear install directory on {hostname}: {stderr}")
            return False

        logger.info(f"Cleared install directory {install_dir} on {hostname}")
        return True

    def _verify_install_directory_empty(self, hostname: str) -> bool:
        """Ensure the host installation directory is empty after cleanup."""

        install_dir = settings.host_install_directory
        command = (
            "$ErrorActionPreference = 'Stop'; "
            f"$installDir = {self._ps_literal(install_dir)}; "
            "$items = Get-ChildItem -LiteralPath $installDir -Force -ErrorAction Stop; "
            "if ($items -and $items.Count -gt 0) {"
            "    $names = $items | Select-Object -ExpandProperty FullName; "
            "    Write-Error (\"Install directory cleanup failed; remaining items: \" + ($names -join ', '))"
            "} else { Write-Output 'EMPTY' }"
        )

        _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)

        if exit_code != 0:
            logger.error(f"Install directory verification failed on {hostname}: {stderr}")
            return False

        logger.info(f"Verified {install_dir} is empty on {hostname}")
        return True

    def _verify_expected_artifacts_present(
        self, hostname: str, artifact_names: Sequence[str]
    ) -> bool:
        """Ensure every expected artifact exists on the host after download."""

        if not artifact_names:
            logger.debug("No artifacts to verify on host %s", hostname)
            return True

        install_dir = settings.host_install_directory
        command = (
            "$ErrorActionPreference = 'Stop'; "
            f"$installDir = {self._ps_literal(install_dir)}; "
            f"$expected = {self._ps_array_literal(artifact_names)}; "
            "$missing = @(); "
            "foreach ($name in $expected) {"
            "    $path = Join-Path -Path $installDir -ChildPath $name; "
            "    if (-not (Test-Path -LiteralPath $path)) { $missing += $path }"
            "} "
            "if ($missing.Count -gt 0) {"
            "    Write-Error (\"Missing artifact(s): \" + ($missing -join ', '))"
            "} else { Write-Output 'OK' }"
        )

        _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)

        if exit_code != 0:
            logger.error(f"Artifact verification failed on {hostname}: {stderr}")
            return False

        logger.info(f"Verified {len(artifact_names)} artifact(s) on {hostname}")
        return True

    @staticmethod
    def _ps_literal(value: str) -> str:
        """Return a PowerShell single-quoted string literal for the provided value."""

        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _ps_array_literal(values: Sequence[str]) -> str:
        """Return a PowerShell array literal with each element safely quoted."""

        if not values:
            return "@()"

        escaped_values = [HostDeploymentService._ps_literal(v) for v in values]
        return f"@({', '.join(escaped_values)})"

    def _build_remote_path(self, filename: str) -> str:
        """Construct the remote path inside the host install directory."""
        return str(PureWindowsPath(settings.host_install_directory) / filename)

    def _download_file_to_host(self, hostname: str, artifact_name: str, remote_path: str) -> bool:
        """Download an artifact from the web server to the host using HTTP."""
        if not self._deployment_enabled:
            logger.error(
                "Host deployment service is disabled; unable to download %s to %s",
                artifact_name,
                hostname,
            )
            return False

        download_url = self._build_download_url(artifact_name)
        command = (
            "$ProgressPreference = 'SilentlyContinue'; "
            f"$downloadUrl = {self._ps_literal(download_url)}; "
            f"$destinationPath = {self._ps_literal(remote_path)}; "
            "Invoke-WebRequest -Uri $downloadUrl -OutFile $destinationPath -UseBasicParsing"
        )

        logger.info(f"Downloading {artifact_name} to {hostname}:{remote_path} from {download_url}")

        max_attempts = max(1, settings.agent_download_max_attempts)
        retry_interval = max(0.0, settings.agent_download_retry_interval)

        for attempt in range(1, max_attempts + 1):
            _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)

            if exit_code == 0:
                if attempt > 1:
                    logger.info(
                        "Download of %s to %s succeeded on attempt %d/%d",
                        artifact_name,
                        hostname,
                        attempt,
                        max_attempts,
                    )
                return True

            logger.warning(
                "Attempt %d/%d failed to download %s to %s: %s",
                attempt,
                max_attempts,
                artifact_name,
                hostname,
                stderr.strip() or f"exit code {exit_code}",
            )

            if attempt < max_attempts and retry_interval:
                logger.info(
                    "Retrying download of %s to %s in %.1f seconds",
                    artifact_name,
                    hostname,
                    retry_interval,
                )
                time.sleep(retry_interval)

        logger.error(
            "Failed to download %s to %s after %d attempt(s)",
            artifact_name,
            hostname,
            max_attempts,
        )
        return False

    def _build_download_url(self, artifact_name: str) -> str:
        """Build a download URL for an artifact exposed by the FastAPI static mount."""
        if not self._agent_download_base_url:
            raise RuntimeError(
                "Host deployment service is disabled because AGENT_DOWNLOAD_BASE_URL is not configured"
            )

        return f"{self._agent_download_base_url}/{quote(artifact_name)}"

    async def deploy_to_all_hosts(self, hostnames: List[str]) -> Tuple[int, int]:
        """
        Deploy to all specified hosts.

        Args:
            hostnames: List of host names to deploy to

        Returns:
            Tuple of (successful_count, failed_count)
        """
        if not self._deployment_enabled:
            logger.warning(
                "Host deployment service is disabled; skipping deployment to %d host(s)",
                len(hostnames),
            )
            return 0, len(hostnames)

        results = await asyncio.gather(
            *(self.ensure_host_setup(hostname) for hostname in hostnames),
            return_exceptions=True,
        )

        successful = 0
        failed = 0

        for result in results:
            if isinstance(result, Exception):
                logger.error("Host deployment task failed: %s", result)
                failed += 1
            elif result:
                successful += 1
            else:
                failed += 1

        return successful, failed

    async def start_startup_deployment(self, hostnames: Sequence[str]) -> None:
        """Kick off background deployment of agents to all configured hosts."""

        mark_status: Optional[str] = None
        should_return = False

        async with self._startup_lock:
            if self._startup_task:
                return

            if not hostnames:
                logger.info("No Hyper-V hosts configured; skipping startup agent deployment")
                mark_status = "skipped"
                should_return = True
            elif not self._deployment_enabled:
                logger.warning(
                    "Host deployment service is disabled; skipping startup deployment"
                )
                mark_status = "skipped"
                should_return = True
            else:
                host_list = [host for host in hostnames if host]
                if not host_list:
                    mark_status = "skipped"
                    should_return = True
                else:
                    self._startup_event = asyncio.Event()
                    async with self._progress_lock:
                        self._startup_progress = StartupDeploymentProgress(
                            status="running",
                            total_hosts=len(host_list),
                            provisioning_available=False,
                            per_host={host: "pending" for host in host_list},
                        )
                        snapshot = self._startup_progress.copy()

                    self._publish_startup_notification(snapshot)

                    loop = asyncio.get_running_loop()
                    self._startup_task = loop.create_task(
                        self._run_startup_deployment(host_list)
                    )

        if mark_status is not None:
            await self._mark_startup_complete(status=mark_status)

        if should_return:
            return

    def is_startup_in_progress(self) -> bool:
        return (
            self._startup_progress.status == "running"
            and not self._startup_progress.provisioning_available
        )

    def is_provisioning_available(self) -> bool:
        if not self._deployment_enabled:
            return True
        if not self._startup_event:
            return True
        if not self._startup_event.is_set():
            return False
        return self._startup_progress.provisioning_available

    def get_startup_summary(self) -> Dict[str, Any]:
        return self._startup_progress.copy().as_dict()

    async def wait_for_startup(self) -> None:
        if self._startup_event:
            await self._startup_event.wait()

    async def _run_startup_deployment(self, hostnames: List[str]) -> None:
        logger.info(
            "Deploying provisioning agents to %d host(s) in background", len(hostnames)
        )

        semaphore = asyncio.Semaphore(max(1, settings.agent_startup_concurrency))
        tasks = [
            asyncio.create_task(self._deploy_host_startup(hostname, semaphore))
            for hostname in hostnames
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Unhandled exception during startup deployment: %s", exc)
            async with self._progress_lock:
                progress = self._startup_progress
                progress.status = "failed"
                progress.provisioning_available = True
                progress.last_error = str(exc)
                snapshot = progress.copy()
        else:
            async with self._progress_lock:
                progress = self._startup_progress
                progress.status = "successful" if progress.failed_hosts == 0 else "failed"
                progress.provisioning_available = True
                snapshot = progress.copy()
        finally:
            await self._mark_startup_complete(snapshot.status, snapshot)

    async def _mark_startup_complete(
        self, status: str, snapshot: Optional[StartupDeploymentProgress] = None
    ) -> None:
        async with self._progress_lock:
            if snapshot is None:
                self._startup_progress.status = status
                self._startup_progress.provisioning_available = True
                snapshot = self._startup_progress.copy()

        if self._startup_event and not self._startup_event.is_set():
            self._startup_event.set()

        self._publish_startup_notification(snapshot)

        async with self._startup_lock:
            self._startup_task = None

    async def _deploy_host_startup(
        self, hostname: str, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            try:
                success = await self.ensure_host_setup(hostname)
                error: Optional[str] = None
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Deployment thread failed for %s: %s", hostname, exc)
                success = False
                error = str(exc)

        await self._record_startup_result(hostname, success, error)

    async def _record_startup_result(
        self, hostname: str, success: bool, error: Optional[str]
    ) -> None:
        async with self._progress_lock:
            progress = self._startup_progress
            progress.completed_hosts += 1
            if success:
                progress.successful_hosts += 1
                progress.per_host[hostname] = "successful"
            else:
                progress.failed_hosts += 1
                progress.per_host[hostname] = "failed"
                progress.last_error = error or f"Deployment failed for {hostname}"
            snapshot = progress.copy()

        self._publish_startup_notification(snapshot)

    def _publish_startup_notification(self, progress: StartupDeploymentProgress) -> None:
        status = progress.status

        if status == "running":
            level = NotificationLevel.INFO
            message = (
                f"Deploying provisioning agents to Hyper-V hosts: "
                f"{progress.completed_hosts}/{progress.total_hosts} complete."
            )
            if progress.failed_hosts:
                message += f" {progress.failed_hosts} host(s) failed."
            message += " VM provisioning is temporarily unavailable."
            provisioning_available = False
        elif status == "successful" or status == "skipped":
            level = NotificationLevel.SUCCESS
            provisioning_available = True
            message = (
                "Provisioning agents are ready on all hosts. VM provisioning is available."
                if status == "successful"
                else "Provisioning agents are already up to date."
            )
        else:  # failed or unknown
            level = NotificationLevel.ERROR
            provisioning_available = True
            failure_detail = (
                f" Last error: {progress.last_error}." if progress.last_error else ""
            )
            message = (
                f"Provisioning agent deployment completed with {progress.failed_hosts} "
                f"failure(s). VM provisioning may be unavailable on affected hosts."
                f"{failure_detail}"
            )

        metadata = {
            "total_hosts": progress.total_hosts,
            "completed_hosts": progress.completed_hosts,
            "successful_hosts": progress.successful_hosts,
            "failed_hosts": progress.failed_hosts,
            "per_host": progress.per_host,
        }

        notification_service.upsert_agent_deployment_notification(
            status=status,
            message=message,
            level=level,
            provisioning_available=provisioning_available,
            metadata=metadata,
        )


# Global host deployment service instance
host_deployment_service = HostDeploymentService()
