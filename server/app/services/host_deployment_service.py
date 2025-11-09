"""Service for deploying scripts and ISOs to Hyper-V hosts."""

import asyncio
import logging
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar, Literal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from ..core.config import settings, AGENT_ARTIFACTS_DIR
from ..core.models import NotificationLevel
from .notification_service import notification_service
from .remote_task_service import (
    remote_task_service,
    RemoteTaskCategory,
    RemoteTaskTimeoutError,
)
from .winrm_service import (
    WinRMAuthenticationError,
    WinRMTransportError,
    winrm_service,
)

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


@dataclass(slots=True)
class HostSetupStatus:
    state: Literal["unknown", "checking", "ready", "updating", "update-failed", "error"] = "unknown"
    error: Optional[str] = None


@dataclass(slots=True)
class InventoryReadiness:
    ready: bool
    preparing: bool
    error: Optional[str] = None


T = TypeVar("T")


class HostDeploymentService:
    """Service for deploying artifacts (scripts and ISOs) to Hyper-V hosts."""

    def __init__(self):
        self._container_version: str = ""
        self._agent_download_base_url: Optional[str] = None
        self._deployment_enabled = self._initialize_agent_download_base_url()
        self._verified_host_versions: Dict[str, str] = {}
        self._host_setup_status: Dict[str, HostSetupStatus] = {}
        self._load_container_version()
        self._startup_task: Optional[asyncio.Task[None]] = None
        self._startup_event: Optional[asyncio.Event] = None
        self._startup_progress = StartupDeploymentProgress()
        self._startup_lock = asyncio.Lock()
        self._progress_lock = asyncio.Lock()
        self._ingress_ready = False
        self._ingress_lock = asyncio.Lock()

        # Cache bound method objects so identity checks in tests that stub
        # `_run_winrm_call` receive the same callable instances every time.
        self._get_host_version = self._get_host_version  # type: ignore[assignment]
        self._deploy_to_host = self._deploy_to_host  # type: ignore[assignment]

    def _initialize_agent_download_base_url(self) -> bool:
        """Resolve and cache the agent download base URL if configured."""

        base_url = settings.get_agent_download_base_url()
        if not base_url:
            logger.warning(
                "AGENT_DOWNLOAD_BASE_URL is not configured; host deployments are disabled."
            )
            return False

        self._agent_download_base_url = base_url
        logger.info(
            "Host deployment service configured with agent download endpoint %s",
            base_url,
        )
        return True

    @property
    def is_enabled(self) -> bool:
        """Return True when host deployments are permitted."""

        return self._deployment_enabled

    def _load_container_version(self):
        """Load version from container artifacts."""
        version_file = settings.version_file_path
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                raw_version = f.read()
            normalized = self._normalize_version_text(raw_version)
            if not normalized:
                logger.warning(
                    "Container version file %s did not contain a usable value", version_file
                )
            self._container_version = normalized
            logger.info("Container version: %s", self._container_version or "<empty>")
        except Exception as e:
            logger.error(f"Failed to load container version: {e}")
            self._container_version = "0.0.0"
        self._verified_host_versions.clear()
        self._host_setup_status.clear()

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
        logger.debug("Ensuring host setup for %s", hostname)
        self._host_setup_status[hostname] = HostSetupStatus(state="checking")

        try:
            # Check host version in a worker thread because it performs network I/O
            host_version = await self._run_winrm_call(
                hostname,
                self._get_host_version,
                description=f"version check for {hostname}",
            )
            needs_update, normalized_host_version, decision = self._assess_host_version(
                host_version
            )
            logger.debug(
                "Host %s version check: container=%r host=%r -> %s",
                hostname,
                (self._container_version or "").strip() or None,
                normalized_host_version or None,
                decision,
            )

            if needs_update:
                logger.info(
                    "Host %s requires agent redeployment; waiting for ingress readiness",
                    hostname,
                )
                await self._wait_for_agent_endpoint_ready()
                self._host_setup_status[hostname] = HostSetupStatus(state="updating")
                deployment_success = await self._run_winrm_call(
                    hostname,
                    self._deploy_to_host,
                    host_version,
                    description=f"deployment for {hostname}",
                )
                if deployment_success:
                    self._verified_host_versions[hostname] = self._container_version
                    self._host_setup_status[hostname] = HostSetupStatus(state="ready")
                else:
                    self._verified_host_versions.pop(hostname, None)
                    self._host_setup_status[hostname] = HostSetupStatus(
                        state="update-failed", error="deployment failed"
                    )
                return deployment_success

            logger.info("Host %s is up-to-date; deployment skipped", hostname)
            self._verified_host_versions[hostname] = self._container_version
            self._host_setup_status[hostname] = HostSetupStatus(state="ready")
            return True

        except Exception as e:
            logger.error(f"Failed to ensure host setup for {hostname}: {e}")
            self._verified_host_versions.pop(hostname, None)
            self._host_setup_status[hostname] = HostSetupStatus(state="error", error=str(e))
            return False

    async def ensure_inventory_ready(self, hostname: str) -> InventoryReadiness:
        """Validate that a host is prepared for inventory collection."""

        if not self._deployment_enabled:
            return InventoryReadiness(ready=True, preparing=False, error=None)

        container_version = self._container_version
        cached_version = self._verified_host_versions.get(hostname)
        if cached_version == container_version:
            self._host_setup_status[hostname] = HostSetupStatus(state="ready")
            return InventoryReadiness(ready=True, preparing=False, error=None)

        ready = await self.ensure_host_setup(hostname)
        status = self._host_setup_status.get(hostname, HostSetupStatus())

        if ready:
            pass
            return InventoryReadiness(ready=True, preparing=False, error=None)

        preparing = status.state in {"updating", "update-failed"}
        error = status.error if status.state == "error" else None
        return InventoryReadiness(ready=False, preparing=preparing, error=error)

    async def _run_winrm_call(
        self,
        hostname: str,
        func: Callable[..., T],
        *args: Any,
        description: str,
    ) -> T:
        """Execute a potentially blocking WinRM call with a timeout."""

        timeout = max(1.0, float(settings.host_deployment_timeout))
        start = time.perf_counter()
        logger.debug(
            "Queueing WinRM operation (%s) on %s with timeout %.1fs",
            description,
            hostname,
            timeout,
        )
        try:
            result = await remote_task_service.run_blocking(
                hostname,
                func,
                hostname,
                *args,
                description=description,
                category=RemoteTaskCategory.DEPLOYMENT,
                timeout=timeout,
            )
        except RemoteTaskTimeoutError as exc:
            logger.error(
                "WinRM operation (%s) on %s exceeded timeout of %.1fs",
                description,
                hostname,
                timeout,
            )
            raise TimeoutError(
                f"Timed out after {timeout:.1f}s during {description}"
            ) from exc
        except Exception:
            duration = time.perf_counter() - start
            logger.debug(
                "WinRM operation (%s) on %s raised after %.2fs",
                description,
                hostname,
                duration,
                exc_info=True,
            )
            raise
        else:
            duration = time.perf_counter() - start
            logger.debug(
                "WinRM operation (%s) on %s completed in %.2fs",
                description,
                hostname,
                duration,
            )
            return result

    def _get_host_version(self, hostname: str) -> str:
        """Get the version currently deployed on a host."""
        version_file_path = f"{settings.host_install_directory}\\version"

        command = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop';
            $versionPath = {self._ps_literal(version_file_path)};
            if (-not (Test-Path -LiteralPath $versionPath)) {{ return }}
            try {{
                $content = [System.IO.File]::ReadAllText($versionPath, [System.Text.Encoding]::UTF8)
            }} catch {{
                try {{
                    $content = [System.IO.File]::ReadAllText($versionPath)
                }} catch {{
                    $content = $null
                }}
            }}
            if ($content -eq $null) {{ return }}
            $trimmed = $content.Trim()
            $trimmed = $trimmed.TrimStart([char]0xFEFF)
            $trimmed = $trimmed.Trim([char]0)
            if (-not [string]::IsNullOrWhiteSpace($trimmed)) {{ Write-Output $trimmed }}
            """
        ).strip()

        try:
            stdout, stderr, exit_code = winrm_service.execute_ps_command(
                hostname, command
            )

            logger.debug(
                "Host version command on %s returned exit=%s stdout_len=%d stderr_len=%d",
                hostname,
                exit_code,
                len(stdout.encode("utf-8")),
                len(stderr.encode("utf-8")),
            )

            normalized_stdout = self._normalize_version_text(stdout)

            if exit_code == 0 and normalized_stdout:
                logger.debug(
                    "Host %s reported version raw=%r normalized=%r",
                    hostname,
                    stdout,
                    normalized_stdout,
                )
                return normalized_stdout
            else:
                # Version file doesn't exist or unreadable
                logger.warning(
                    "Host %s did not provide a usable version (exit=%s, raw stdout=%r, stderr=%r)",
                    hostname,
                    exit_code,
                    stdout,
                    stderr,
                )
                return "0.0.0"
        except WinRMAuthenticationError as exc:
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

    def _assess_host_version(
        self, host_version: Optional[str]
    ) -> Tuple[bool, str, str]:
        """
        Determine whether the host requires an update, returning the normalized version and a reason.

        Args:
            host_version (Optional[str]): The version string reported by the host.

        Returns:
            Tuple[bool, str, str]: A tuple containing:
                - needs_update (bool): Whether the host requires an update.
                - normalized_version (str): The normalized version string of the host.
                - decision_reason (str): A string explaining the decision.
        """
        container_version = self._normalize_version_text(self._container_version)
        normalized_host = self._normalize_version_text(host_version)

        if not container_version:
            logger.warning(
                "Container version is empty; forcing deployment for host artifacts"
            )
            return True, normalized_host, "container version unavailable"

        if normalized_host == container_version:
            return False, normalized_host, "versions match"

        if not normalized_host:
            return True, normalized_host, "host version missing"

        if normalized_host == "0.0.0":
            return True, normalized_host, "host reported default version 0.0.0"

        try:
            host_parts = [int(x) for x in normalized_host.split(".")]
            container_parts = [int(x) for x in container_version.split(".")]
        except Exception:
            logger.warning(
                "Version comparison failed for container=%r host=%r; forcing update",
                container_version,
                normalized_host,
            )
            return True, normalized_host, "host version unparsable"

        if container_parts > host_parts:
            return True, normalized_host, "container version newer than host"

        if container_parts == host_parts:
            return False, normalized_host, "versions match after normalization"

        return False, normalized_host, "host version ahead of container"

    def _needs_update(self, host_version: str) -> bool:
        """Check if host needs to be updated."""

        needs_update, _, _ = self._assess_host_version(host_version)
        return needs_update

    @staticmethod
    def _normalize_version_text(value: Optional[str]) -> str:
        """Clean version text by trimming whitespace, BOMs, nulls, and blank lines."""

        if not value:
            return ""

        text = value.replace("\ufeff", "").replace("\x00", "")
        text = text.strip()

        if not text:
            return ""

        if "\n" in text or "\r" in text:
            for line in text.replace("\r", "\n").split("\n"):
                cleaned = line.strip()
                if cleaned:
                    return cleaned
            return ""

        return text

    def _deploy_to_host(self, hostname: str, observed_host_version: Optional[str] = None) -> bool:
        """Deploy scripts and ISOs to a host."""
        container_version = (self._container_version or "").strip()

        needs_update, normalized_observed, decision = self._assess_host_version(
            observed_host_version
        )
        logger.debug(
            "Starting deployment evaluation for %s (container=%r, observed_host=%r -> %s)",
            hostname,
            container_version or None,
            normalized_observed or None,
            decision,
        )

        try:
            if not self._deployment_enabled:
                logger.warning(
                    "Host deployment service is disabled; skipping deployment to %s",
                    hostname,
                )
                return False

            if observed_host_version is not None and not needs_update:
                logger.debug(
                    "Skipping deployment to %s; observed host version %r already matches container %r",
                    hostname,
                    normalized_observed or None,
                    container_version or None,
                )
                return True

            refreshed_host_version: Optional[str] = None
            refresh_needed = True
            try:
                refreshed_host_version = self._get_host_version(hostname)
                refresh_needed, normalized_refresh, refresh_decision = (
                    self._assess_host_version(refreshed_host_version)
                )
                logger.debug(
                    "Refreshed host version for %s prior to deployment: container=%r host=%r -> %s",
                    hostname,
                    container_version or None,
                    normalized_refresh or None,
                    refresh_decision,
                )
            except Exception as exc:  # pragma: no cover - defensive logging path
                logger.warning(
                    "Unable to refresh host version for %s prior to deployment: %s",
                    hostname,
                    exc,
                )

            if refreshed_host_version is not None and not refresh_needed:
                logger.info(
                    "Skipping deployment to %s; host version matches container",
                    hostname,
                )
                return True

            logger.info(f"Starting deployment to {hostname}")

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

            if not self._verify_expected_artifacts_present(
                hostname, expected_artifacts
            ):
                return False

            logger.info(f"Deployment to {hostname} completed successfully")
            return True

        except Exception as e:
            logger.error(f"Deployment to {hostname} failed: {e}")
            return False

    def _ensure_install_directory(self, hostname: str) -> bool:
        """Ensure the installation directory exists on the host."""
        install_dir = settings.host_install_directory

        command = (
            f"New-Item -ItemType Directory -Path '{install_dir}' -Force | Out-Null"
        )

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

        script_dir = AGENT_ARTIFACTS_DIR

        try:
            if not script_files:
                logger.warning(f"No script files found in {script_dir}")
                return True

            logger.debug("Found %d scripts to deploy", len(script_files))

            for script_file in script_files:
                remote_path = self._build_remote_path(script_file.name)

                if not self._download_file_to_host(
                    hostname, script_file.name, remote_path
                ):
                    logger.error(
                        f"Failed to deploy script {script_file.name} to {hostname}"
                    )
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

        iso_dir = AGENT_ARTIFACTS_DIR

        try:
            if not iso_files:
                logger.warning(f"No ISO files found in {iso_dir}")
                return False

            logger.debug("Found %d ISOs to deploy", len(iso_files))

            for iso_file in iso_files:
                remote_path = self._build_remote_path(iso_file.name)

                if not self._download_file_to_host(
                    hostname, iso_file.name, remote_path
                ):
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

        artifact_dir = AGENT_ARTIFACTS_DIR

        if not artifact_dir.exists():
            logger.error(f"Agent artifacts directory does not exist: {artifact_dir}")
            return []

        return sorted(path for path in artifact_dir.glob("*.ps1") if path.is_file())

    def _collect_iso_files(self) -> List[Path]:
        """Return all ISO files available for deployment."""

        artifact_dir = AGENT_ARTIFACTS_DIR

        if not artifact_dir.exists():
            logger.error(f"Agent artifacts directory does not exist: {artifact_dir}")
            return []

        return sorted(path for path in artifact_dir.glob("*.iso") if path.is_file())

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
            logger.error(
                f"Install directory verification failed on {hostname}: {stderr}"
            )
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

    def _download_file_to_host(
        self, hostname: str, artifact_name: str, remote_path: str
    ) -> bool:
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

        logger.info(
            f"Downloading {artifact_name} to {hostname}:{remote_path} from {download_url}"
        )

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
                logger.info(
                    "No Hyper-V hosts configured; skipping startup agent deployment"
                )
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
        await self._wait_for_agent_endpoint_ready()
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
                progress.status = (
                    "successful" if progress.failed_hosts == 0 else "failed"
                )
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

    async def _wait_for_agent_endpoint_ready(self) -> None:
        """Block until ingress routes to this service or a timeout elapses."""

        if self._ingress_ready:
            return

        if not self._agent_download_base_url:
            self._ingress_ready = True
            return

        async with self._ingress_lock:
            if self._ingress_ready:
                return

            health_url = self._build_health_check_url()
            if not health_url:
                self._ingress_ready = True
                return

            timeout = max(1.0, float(settings.agent_startup_ingress_timeout))
            interval = max(0.5, float(settings.agent_startup_ingress_poll_interval))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            attempt = 0
            last_error: Optional[str] = None

            logger.info(
                "Waiting up to %.1fs for ingress routing before deploying host scripts",
                timeout,
            )

            async with httpx.AsyncClient(follow_redirects=True) as client:
                while True:
                    attempt += 1
                    try:
                        response = await client.get(health_url, timeout=5.0)
                    except httpx.HTTPError as exc:
                        last_error = str(exc)
                        logger.debug(
                            "Ingress probe attempt %d failed for %s: %s",
                            attempt,
                            health_url,
                            exc,
                        )
                    else:
                        status = response.status_code
                        if status != 503 and status < 500:
                            self._ingress_ready = True
                            logger.info(
                                "Ingress readiness confirmed after %d attempt(s) via %s (status=%d)",
                                attempt,
                                health_url,
                                status,
                            )
                            return

                        last_error = f"status {status}"
                        logger.debug(
                            "Ingress probe attempt %d received HTTP %d from %s",
                            attempt,
                            status,
                            health_url,
                        )

                    if loop.time() >= deadline:
                        logger.warning(
                            "Timed out after %.1fs waiting for ingress readiness; proceeding with host deployment (last error: %s)",
                            timeout,
                            last_error or "unknown",
                        )
                        self._ingress_ready = True
                        return

                    await asyncio.sleep(interval)

    def _build_health_check_url(self) -> Optional[str]:
        """Derive the service health check URL from the agent download base."""

        if not self._agent_download_base_url:
            return None

        parts = urlsplit(self._agent_download_base_url)
        if not parts.scheme or not parts.netloc:
            logger.warning(
                "Cannot derive health check URL from agent download base %s", self._agent_download_base_url
            )
            return None

        root = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
        return f"{root.rstrip('/')}/healthz"

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

    def _publish_startup_notification(
        self, progress: StartupDeploymentProgress
    ) -> None:
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

    async def get_metrics(self) -> Dict[str, Any]:
        """Return diagnostic information about host deployment tasks."""

        async with self._progress_lock:
            progress_snapshot = self._startup_progress.copy()

        async with self._ingress_lock:
            ingress_ready = self._ingress_ready

        startup_task_running = (
            self._startup_task is not None and not self._startup_task.done()
        )

        return {
            "enabled": self._deployment_enabled,
            "ingress_ready": ingress_ready,
            "startup_task_running": startup_task_running,
            "startup": progress_snapshot.as_dict(),
        }


# Global host deployment service instance
host_deployment_service = HostDeploymentService()
