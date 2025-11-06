"""Inventory management service for tracking Hyper-V hosts and VMs."""
import asyncio
import hashlib
import json
import logging
import random
import textwrap
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Set

from ..core.models import (
    Cluster,
    Host,
    NotificationCategory,
    NotificationLevel,
    OSFamily,
    VM,
    VMState,
)
from ..core.config import settings
from .winrm_service import winrm_service
from .host_deployment_service import host_deployment_service

logger = logging.getLogger(__name__)


class InventoryService:
    """Service for managing inventory of hosts and VMs."""

    def __init__(self):
        self.clusters: Dict[str, Cluster] = {}
        self.hosts: Dict[str, Host] = {}
        self.vms: Dict[str, VM] = {}  # Key is "hostname:vmname"
        self.last_refresh: Optional[datetime] = None
        self._job_vm_placeholders: Dict[str, Set[str]] = {}

        # Runtime state for background refresh management
        self._refresh_worker: Optional[asyncio.Task] = None
        self._manual_refresh_event: asyncio.Event = asyncio.Event()
        self._pending_manual_refreshes: Deque[asyncio.Future] = deque()
        self._initial_refresh_complete: asyncio.Event = asyncio.Event()
        self._started: bool = False
        self._overrun_active: bool = False
        self._inventory_notification_id: Optional[str] = None

        # Progress tracking for UI feedback
        self._status: str = "idle"
        self._status_message: str = "Inventory service not yet started."
        self._status_level: NotificationLevel = NotificationLevel.INFO
        self._status_metadata: Dict[str, Any] = {}
        self._status_updated_at: Optional[datetime] = None
        self._cycle_total_hosts: int = 0
        self._cycle_completed_hosts: int = 0
        self._cycle_index: int = 0

    async def start(self):
        """Start the inventory service and launch background refresh."""
        logger.info("Starting inventory service")

        if self._refresh_worker and not self._refresh_worker.done():
            logger.debug("Inventory service already running; skipping start")
            return

        self._started = True
        self._initial_refresh_complete = asyncio.Event()
        self._manual_refresh_event = asyncio.Event()
        self._pending_manual_refreshes = deque()
        self._overrun_active = False

        if settings.dummy_data:
            logger.info("DUMMY_DATA enabled - using development data")
            await self._initialize_dummy_data()
            self._initial_refresh_complete.set()
            self._update_status(
                "ready",
                "Inventory data loaded in development mode.",
                NotificationLevel.INFO,
                notify=True,
                metadata={"mode": "dummy"},
            )
        else:
            if host_deployment_service.is_startup_in_progress():
                logger.info(
                    "Host agent deployment running in background; continuing inventory startup"
                )

            self._update_status(
                "starting",
                "Inventory refresh is running in the background. Data may be incomplete.",
                NotificationLevel.INFO,
                notify=True,
                metadata={"phase": "startup"},
            )

        # Ensure a refresh cycle kicks off immediately
        self._manual_refresh_event.set()
        self._refresh_worker = asyncio.create_task(self._refresh_loop())

    async def stop(self):
        """Stop the inventory service."""
        logger.info("Stopping inventory service")
        self._started = False
        if self._refresh_worker:
            self._manual_refresh_event.set()
            self._refresh_worker.cancel()
            try:
                await self._refresh_worker
            except asyncio.CancelledError:
                pass
            self._refresh_worker = None

        while self._pending_manual_refreshes:
            future = self._pending_manual_refreshes.popleft()
            if not future.done():
                future.cancel()

    async def _initialize_dummy_data(self):
        """Initialize with dummy data for development."""
        logger.info("Initializing dummy data for development")

        # Create dummy clusters
        cluster1 = Cluster(
            name="Production",
            hosts=["hyperv01.lab.local", "hyperv02.lab.local"],
            connected_hosts=2,
            total_hosts=2
        )

        cluster2 = Cluster(
            name="Development",
            hosts=["hyperv-dev01.lab.local"],
            connected_hosts=1,
            total_hosts=1
        )

        self.clusters = {
            "Production": cluster1,
            "Development": cluster2
        }

        # Create connected hosts with VMs
        now = datetime.utcnow()

        # Production cluster hosts
        self.hosts["hyperv01.lab.local"] = Host(
            hostname="hyperv01.lab.local",
            cluster="Production",
            connected=True,
            last_seen=now,
            error=None
        )

        self.hosts["hyperv02.lab.local"] = Host(
            hostname="hyperv02.lab.local",
            cluster="Production",
            connected=True,
            last_seen=now,
            error=None
        )

        # Development cluster host
        self.hosts["hyperv-dev01.lab.local"] = Host(
            hostname="hyperv-dev01.lab.local",
            cluster="Development",
            connected=True,
            last_seen=now,
            error=None
        )

        # Add a few disconnected hosts
        self.hosts["hyperv03.lab.local"] = Host(
            hostname="hyperv03.lab.local",
            cluster=None,  # No cluster assignment
            connected=False,
            last_seen=now - timedelta(hours=2),
            error="Connection timeout"
        )

        self.hosts["hyperv-backup01.lab.local"] = Host(
            hostname="hyperv-backup01.lab.local",
            cluster=None,
            connected=False,
            last_seen=now - timedelta(minutes=30),
            error="WinRM authentication failed"
        )

        # Create dummy VMs
        dummy_vms = [
            # VMs on hyperv01
            VM(name="web-server-01", host="hyperv01.lab.local",
               state=VMState.RUNNING, cpu_cores=4, memory_gb=8.0,
               os_family=OSFamily.LINUX, created_at=now - timedelta(days=5)),
            VM(name="db-server-01", host="hyperv01.lab.local",
               state=VMState.RUNNING, cpu_cores=8, memory_gb=16.0,
               os_family=OSFamily.LINUX, created_at=now - timedelta(days=10)),
            VM(name="win-app-01", host="hyperv01.lab.local",
               state=VMState.OFF, cpu_cores=2, memory_gb=4.0,
               os_family=OSFamily.WINDOWS, created_at=now - timedelta(days=2)),

            # VMs on hyperv02
            VM(name="load-balancer-01", host="hyperv02.lab.local",
               state=VMState.RUNNING, cpu_cores=2, memory_gb=4.0,
               os_family=OSFamily.LINUX, created_at=now - timedelta(days=7)),
            VM(name="monitoring-01", host="hyperv02.lab.local",
               state=VMState.RUNNING, cpu_cores=4, memory_gb=8.0,
               os_family=OSFamily.LINUX, created_at=now - timedelta(days=3)),
            VM(name="backup-vm", host="hyperv02.lab.local",
               state=VMState.SAVED, cpu_cores=1, memory_gb=2.0,
               os_family=OSFamily.WINDOWS, created_at=now - timedelta(days=15)),

            # VMs on dev host
            VM(name="test-vm-01", host="hyperv-dev01.lab.local",
               state=VMState.RUNNING, cpu_cores=2, memory_gb=4.0,
               os_family=OSFamily.LINUX, created_at=now - timedelta(days=1)),
            VM(name="dev-workstation", host="hyperv-dev01.lab.local",
               state=VMState.PAUSED, cpu_cores=4, memory_gb=8.0,
               os_family=OSFamily.WINDOWS, created_at=now - timedelta(hours=8)),
        ]

        # Add VMs to inventory
        for vm in dummy_vms:
            key = f"{vm.host}:{vm.name}"
            self.vms[key] = vm

        self.last_refresh = now
        logger.info("Dummy data initialized successfully")

    async def _deploy_artifacts_to_hosts(self):
        """Deploy scripts and ISOs to all configured hosts."""
        logger.info("Deploying artifacts to Hyper-V hosts")

        host_list = settings.get_hyperv_hosts_list()

        if not host_list:
            logger.warning("No Hyper-V hosts configured")
            return

        if not host_deployment_service.is_enabled:
            logger.warning(
                "Host deployment service is disabled; skipping artifact deployment to hosts"
            )
            return

        container_version = host_deployment_service.get_container_version()
        logger.info(f"Container version: {container_version}")

        successful, failed = await host_deployment_service.deploy_to_all_hosts(
            host_list
        )

        if failed > 0:
            logger.warning(f"Artifact deployment completed with "
                           f"{failed} failure(s) and {successful} success(es)")
        else:
            logger.info(f"Artifact deployment completed successfully "
                        f"to all {successful} host(s)")

    async def _refresh_loop(self):
        """Background loop that keeps the inventory up-to-date."""
        logger.info("Inventory refresh loop starting")
        try:
            while True:
                manual = False
                if self._manual_refresh_event.is_set():
                    manual = True
                    self._manual_refresh_event.clear()

                duration = await self._run_refresh_cycle(manual=manual)
                self._resolve_manual_requests()

                if manual:
                    # Immediately continue to honour additional manual refresh requests
                    continue

                wait_time = max(0.0, settings.inventory_refresh_interval - duration)
                if wait_time <= 0:
                    continue

                try:
                    await asyncio.wait_for(self._manual_refresh_event.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.info("Inventory refresh loop cancelled")
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Inventory refresh loop terminated unexpectedly: %s", exc)
            self._fail_manual_requests(exc)
            raise
        finally:
            self._resolve_manual_requests()

    async def refresh_inventory(self):
        """Trigger an immediate inventory refresh."""
        if settings.dummy_data:
            await self._refresh_dummy_data()
            return

        if not self._refresh_worker or self._refresh_worker.done():
            logger.debug("Inventory refresh requested before worker loop initialised; running inline")
            await self._run_refresh_cycle(manual=True)
            return

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_manual_refreshes.append(future)
        self._manual_refresh_event.set()

        try:
            await future
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise

    async def _run_refresh_cycle(self, *, manual: bool = False) -> float:
        """Execute a single refresh cycle and return the duration in seconds."""

        start_monotonic = time.monotonic()

        if settings.dummy_data:
            await self._refresh_dummy_data()
            self.last_refresh = datetime.utcnow()
            duration = time.monotonic() - start_monotonic
            self._update_status(
                "ready",
                "Inventory data loaded in development mode.",
                NotificationLevel.INFO,
                notify=False,
                metadata={
                    "mode": "dummy",
                    "manual": manual,
                    "duration_seconds": round(duration, 3),
                },
            )
            return duration

        host_list = settings.get_hyperv_hosts_list()
        if not host_list:
            logger.info("No Hyper-V hosts configured; clearing inventory")
            self._clear_inventory()
            self.last_refresh = datetime.utcnow()
            self._initial_refresh_complete.set()
            self._update_status(
                "ready",
                "No Hyper-V hosts are configured.",
                NotificationLevel.INFO,
                notify=True,
                metadata={
                    "manual": manual,
                    "duration_seconds": 0.0,
                    "total_hosts": 0,
                    "completed_hosts": 0,
                    "connected_hosts": 0,
                },
            )
            return time.monotonic() - start_monotonic

        ordered_hosts = self._ordered_hosts(host_list, manual=manual)
        total_hosts = len(ordered_hosts)
        interval = max(float(settings.inventory_refresh_interval), 0.0)
        per_host_slot = 0.0
        if not manual and total_hosts > 0 and interval > 0:
            per_host_slot = interval / total_hosts

        self._cycle_total_hosts = total_hosts
        self._cycle_completed_hosts = 0
        connected_hosts: List[str] = []

        progress_metadata = {
            "manual": manual,
            "total_hosts": total_hosts,
            "completed_hosts": self._cycle_completed_hosts,
            "per_host_interval_seconds": round(per_host_slot, 3) if per_host_slot else 0.0,
        }

        progress_message = self._format_progress_message(
            self._cycle_completed_hosts, total_hosts
        )
        self._update_status(
            "refreshing",
            progress_message,
            NotificationLevel.INFO,
            notify=not manual and not self._initial_refresh_complete.is_set(),
            metadata=progress_metadata,
        )

        for index, hostname in enumerate(ordered_hosts):
            await self._refresh_host(hostname)

            host = self.hosts.get(hostname)
            if host and host.connected:
                connected_hosts.append(hostname)

            self._cycle_completed_hosts += 1

            progress_metadata = {
                "manual": manual,
                "total_hosts": total_hosts,
                "completed_hosts": self._cycle_completed_hosts,
                "per_host_interval_seconds": round(per_host_slot, 3) if per_host_slot else 0.0,
            }

            progress_message = self._format_progress_message(
                self._cycle_completed_hosts, total_hosts
            )
            self._update_status(
                "refreshing",
                progress_message,
                NotificationLevel.INFO,
                notify=False,
                metadata=progress_metadata,
            )

            if not self._initial_refresh_complete.is_set():
                self._initial_refresh_complete.set()

            if per_host_slot > 0:
                if self._manual_refresh_event.is_set():
                    per_host_slot = 0.0
                else:
                    next_slot = start_monotonic + per_host_slot * (index + 1)
                    delay = next_slot - time.monotonic()
                    if delay > 0:
                        try:
                            await asyncio.wait_for(
                                self._manual_refresh_event.wait(), timeout=delay
                            )
                        except asyncio.TimeoutError:
                            pass
                        if self._manual_refresh_event.is_set():
                            per_host_slot = 0.0

        self._rebuild_clusters(host_list)
        if not connected_hosts:
            logger.info("No hosts are currently connected")
            self.vms.clear()

        self.last_refresh = datetime.utcnow()

        duration = time.monotonic() - start_monotonic
        self._complete_refresh_cycle(
            duration=duration,
            total_hosts=total_hosts,
            manual=manual,
            connected_hosts=len(connected_hosts),
        )

        logger.info(
            "Inventory refresh completed in %.2fs. Connected hosts: %d, Total VMs: %d",
            duration,
            len(connected_hosts),
            len(self.vms),
        )

        return duration

    def _complete_refresh_cycle(
        self,
        *,
        duration: float,
        total_hosts: int,
        manual: bool,
        connected_hosts: int,
    ) -> None:
        """Update status and notifications after a refresh cycle."""

        metadata = {
            "manual": manual,
            "duration_seconds": round(duration, 3),
            "total_hosts": total_hosts,
            "completed_hosts": self._cycle_completed_hosts,
            "connected_hosts": connected_hosts,
        }

        if manual:
            self._update_status(
                self._status,
                self._status_message,
                self._status_level,
                notify=False,
                metadata=metadata,
            )
            return

        interval = max(float(settings.inventory_refresh_interval), 0.0)

        if interval and duration > interval:
            message = (
                "Inventory refresh exceeded the configured interval. "
                "Add resources or increase INVENTORY_REFRESH_INTERVAL."
            )
            self._overrun_active = True
            self._update_status(
                "delayed",
                message,
                NotificationLevel.WARNING,
                notify=True,
                metadata=metadata,
            )
            return

        if self._overrun_active:
            message = "Inventory refresh recovered to within the configured interval."
            self._overrun_active = False
            self._update_status(
                "ready",
                message,
                NotificationLevel.INFO,
                notify=True,
                metadata=metadata,
            )
            return

        message = (
            "Inventory is up to date."
            if self._initial_refresh_complete.is_set()
            else "Inventory refresh completed."
        )
        level = (
            NotificationLevel.SUCCESS
            if self._initial_refresh_complete.is_set()
            else NotificationLevel.INFO
        )
        notify = not self._initial_refresh_complete.is_set()
        self._update_status(
            "ready",
            message,
            level,
            notify=notify,
            metadata=metadata,
        )

    def _ordered_hosts(self, hostnames: List[str], *, manual: bool = False) -> List[str]:
        """Return hostnames in a deterministic hashed order with rotation."""

        sanitized = [host for host in hostnames if host]
        sanitized.sort(key=lambda host: hashlib.sha256(host.encode("utf-8")).digest())

        if not sanitized:
            return []

        if manual:
            return sanitized

        offset = self._cycle_index % len(sanitized)
        self._cycle_index += 1

        if offset:
            return sanitized[offset:] + sanitized[:offset]

        return sanitized

    def _resolve_manual_requests(self) -> None:
        """Resolve any pending manual refresh futures."""

        while self._pending_manual_refreshes:
            future = self._pending_manual_refreshes.popleft()
            if not future.done():
                future.set_result(True)

    def _fail_manual_requests(self, exc: Exception) -> None:
        """Fail all pending manual refresh futures with the provided exception."""

        while self._pending_manual_refreshes:
            future = self._pending_manual_refreshes.popleft()
            if not future.done():
                future.set_exception(exc)

    def _clear_inventory(self) -> None:
        """Reset the in-memory inventory state."""

        self.clusters.clear()
        self.hosts.clear()
        self.vms.clear()
        self._job_vm_placeholders.clear()

    def _format_progress_message(self, completed: int, total: int) -> str:
        if total <= 0:
            return "Inventory refresh running"
        return f"Inventory refresh in progress ({completed}/{total})"

    def _update_status(
        self,
        status: str,
        message: str,
        level: NotificationLevel,
        *,
        notify: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata = dict(metadata or {})
        changed = (
            status != self._status
            or message != self._status_message
            or level != self._status_level
            or metadata != self._status_metadata
        )

        self._status = status
        self._status_message = message
        self._status_level = level
        self._status_metadata = metadata
        self._status_updated_at = datetime.utcnow()

        if notify and changed:
            self._publish_inventory_notification(status, message, level, metadata)

    def _publish_inventory_notification(
        self,
        status: str,
        message: str,
        level: NotificationLevel,
        metadata: Dict[str, Any],
    ) -> None:
        try:
            from .notification_service import notification_service
        except Exception:  # pragma: no cover - import safety
            return

        payload = dict(metadata)
        payload.setdefault("status", status)

        notification = notification_service.upsert_inventory_notification(
            status=status,
            message=message,
            level=level,
            metadata=payload,
        )

        if notification:
            self._inventory_notification_id = notification.id

    def get_status_summary(self) -> Dict[str, Any]:
        """Return a snapshot of the current inventory refresh status."""

        metadata = dict(self._status_metadata)
        metadata.setdefault("total_hosts", self._cycle_total_hosts)
        metadata.setdefault("completed_hosts", self._cycle_completed_hosts)
        metadata.setdefault("manual", False)

        summary = {
            "state": self._status,
            "message": self._status_message,
            "level": self._status_level.value,
            "metadata": metadata,
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "initial_refresh_complete": self._initial_refresh_complete.is_set(),
            "updated_at": self._status_updated_at.isoformat() if self._status_updated_at else None,
            "started": self._started,
        }

        return summary

    def is_available(self) -> bool:
        """Return True when the inventory service has been started."""

        return self._started

    def has_completed_initial_refresh(self) -> bool:
        """Return True once the first refresh cycle has completed."""

        return self._initial_refresh_complete.is_set()

    async def _refresh_dummy_data(self):
        """Refresh dummy data with some random state changes."""
        # Occasionally change VM states for demo purposes
        if random.random() < 0.1:  # 10% chance per refresh
            vm_list = list(self.vms.values())
            if vm_list:
                vm = random.choice(vm_list)
                if vm.state == VMState.RUNNING:
                    vm.state = VMState.OFF
                elif vm.state == VMState.OFF:
                    vm.state = VMState.RUNNING

                logger.info(
                    f"Dummy data: Changed {vm.name} state to {vm.state}")

        self.last_refresh = datetime.utcnow()

    async def _refresh_host(self, hostname: str):
        """Refresh inventory for a single host."""
        logger.info(f"Refreshing inventory for host: {hostname}")

        try:
            # Test connection
            await asyncio.to_thread(
                self._test_host_connection,
                hostname
            )

            # Query VMs
            vms = await asyncio.to_thread(
                self._query_host_vms,
                hostname
            )

            # Determine cluster assignment
            cluster_name = await asyncio.to_thread(
                self._query_host_cluster,
                hostname
            )
            if not cluster_name:
                cluster_name = "Default"

            # Check if host was previously disconnected and create reconnection notification
            previous_host = self.hosts.get(hostname)
            was_disconnected = previous_host and not previous_host.connected if previous_host else True

            # Create notification for host reconnection (only if not dummy data and was previously disconnected)
            if was_disconnected and not settings.dummy_data and previous_host:
                # Import here to avoid circular import
                from .notification_service import notification_service
                notification_service.create_host_reconnected_notification(
                    hostname)

            # Update host status
            self.hosts[hostname] = Host(
                hostname=hostname,
                cluster=cluster_name,
                connected=True,
                last_seen=datetime.utcnow(),
                error=None
            )

            expected_keys = {f"{hostname}:{vm.name}" for vm in vms}

            # Update VM inventory
            for vm in vms:
                key = f"{hostname}:{vm.name}"
                self._detach_placeholder_key(key)
                self.vms[key] = vm

            # Remove VMs that no longer exist on this host, but preserve active placeholders
            active_placeholder_keys = self._active_placeholder_keys()
            keys_to_remove = [
                key for key in list(self.vms.keys())
                if key.startswith(f"{hostname}:")
                and key not in expected_keys
                and key not in active_placeholder_keys
            ]
            for key in keys_to_remove:
                del self.vms[key]

            logger.info(f"Host {hostname}: {len(vms)} VMs")

        except Exception as e:
            logger.error(f"Failed to refresh host {hostname}: {e}")

            # Check if host was previously connected and create notification
            previous_host = self.hosts.get(hostname)
            was_connected = previous_host and previous_host.connected if previous_host else False

            # Create notification for host becoming unreachable (only if not dummy data)
            if was_connected and not settings.dummy_data:
                # Import here to avoid circular import
                from .notification_service import notification_service
                notification_service.create_host_unreachable_notification(
                    hostname, str(e))

            self.hosts[hostname] = Host(
                hostname=hostname,
                cluster=previous_host.cluster if previous_host else None,
                connected=False,
                last_seen=self.hosts.get(hostname,
                                         Host(hostname=hostname)).last_seen,
                error=str(e)
            )

            # Clear non-placeholder VMs for the unreachable host
            self._clear_host_vms(hostname, preserve_placeholders=True)

    def _test_host_connection(self, hostname: str):
        """Test WinRM connection to a host."""
        command = "echo 'connection test'"
        stdout, stderr, exit_code = winrm_service.execute_ps_command(
            hostname, command
        )

        if exit_code != 0:
            raise Exception(f"Connection test failed: {stderr}")

    def _query_host_vms(self, hostname: str) -> List[VM]:
        """Query VMs from a host using PowerShell."""
        # PowerShell command to get VM information
        command = textwrap.dedent(
            """
            $ErrorActionPreference = 'Stop'
            $vms = Get-VM | Select-Object \
                Name, \
                @{N='State';E={$_.State.ToString()}}, \
                ProcessorCount, \
                @{N='MemoryGB';E={[math]::Round(($_.MemoryAssigned/1GB), 2)}}, \
                @{N='CreationTime';E={
                    if ($_.CreationTime) {
                        $_.CreationTime.ToUniversalTime().ToString('o')
                    } else {
                        $null
                    }
                }}, \
                @{N='Generation';E={$_.Generation}}, \
                @{N='Version';E={$_.Version}}, \
                @{N='OperatingSystem';E={
                    if ($_.OperatingSystem) {
                        $_.OperatingSystem.ToString()
                    } else {
                        $null
                    }
                }}
            $vms | ConvertTo-Json -Depth 3
            """
        )

        stdout, stderr, exit_code = winrm_service.execute_ps_command(
            hostname, command
        )

        if exit_code != 0:
            raise Exception(f"Failed to query VMs: {stderr}")

        raw_output = stdout.strip().lstrip("\ufeff")
        if not raw_output:
            logger.info(f"Host {hostname} returned no VM data")
            return []

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse VM data from {hostname}: {e}")
            logger.debug(f"Raw VM output from {hostname}: {stdout}")
            raise

        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list):
            raise ValueError(
                f"Unexpected VM payload type from {hostname}: {type(data).__name__}"
            )

        vms: List[VM] = []
        for vm_data in data:
            if not isinstance(vm_data, dict):
                logger.warning(
                    "Skipping VM entry from %s because it is not a dictionary: %r",
                    hostname,
                    vm_data,
                )
                continue

            state_str = vm_data.get('State', 'Unknown')
            try:
                state = VMState(state_str)
            except ValueError:
                state = VMState.UNKNOWN

            memory_value = vm_data.get('MemoryGB', 0.0)
            memory_gb = self._coerce_float(memory_value, default=0.0)

            cpu_value = vm_data.get('ProcessorCount', 0)
            cpu_cores = self._coerce_int(cpu_value, default=0)

            os_family = self._infer_os_family(vm_data.get('OperatingSystem'))

            vm = VM(
                name=vm_data.get('Name', ''),
                host=hostname,
                state=state,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                os_family=os_family,
                created_at=vm_data.get('CreationTime')
            )
            vms.append(vm)

        logger.info("Host %s returned %d VM(s)", hostname, len(vms))
        return vms

    def _query_host_cluster(self, hostname: str) -> Optional[str]:
        """Discover the cluster name for the given host."""
        host_literal = self._ps_string_literal(hostname)
        command = textwrap.dedent(
            f"""
            try {{
                $node = Get-ClusterNode -Name {host_literal} -ErrorAction Stop
                if ($node -and $node.Cluster) {{
                    $node.Cluster.Name
                }}
            }} catch {{
                ''
            }}
            """
        )

        stdout, stderr, exit_code = winrm_service.execute_ps_command(
            hostname, command
        )

        if exit_code != 0:
            logger.debug(
                "Cluster query for host %s failed with exit code %s: %s",
                hostname,
                exit_code,
                stderr,
            )
            return None

        cluster_name = stdout.strip()
        if not cluster_name:
            logger.debug("Host %s is not part of a cluster", hostname)
            return None

        logger.debug("Host %s belongs to cluster '%s'", hostname, cluster_name)
        return cluster_name

    def _rebuild_clusters(self, configured_hosts: List[str]) -> None:
        """Recalculate cluster information based on current hosts."""
        cluster_hosts: Dict[str, Set[str]] = {}
        cluster_connected_counts: Dict[str, int] = {}

        for hostname in configured_hosts:
            host = self.hosts.get(hostname)
            if not host:
                continue

            cluster_name = host.cluster or "Default"
            cluster_hosts.setdefault(cluster_name, set()).add(host.hostname)
            if host.connected:
                cluster_connected_counts[cluster_name] = (
                    cluster_connected_counts.get(cluster_name, 0) + 1
                )

        new_clusters: Dict[str, Cluster] = {}
        for cluster_name, hostnames in cluster_hosts.items():
            sorted_hosts = sorted(hostnames)
            new_clusters[cluster_name] = Cluster(
                name=cluster_name,
                hosts=sorted_hosts,
                connected_hosts=cluster_connected_counts.get(cluster_name, 0),
                total_hosts=len(sorted_hosts)
            )

        self.clusters = new_clusters
        if new_clusters:
            logger.info(
                "Rebuilt cluster inventory: %s",
                {name: cluster.connected_hosts for name, cluster in new_clusters.items()}
            )

    def _active_placeholder_keys(self) -> Set[str]:
        return {key for keys in self._job_vm_placeholders.values() for key in keys}

    def _detach_placeholder_key(self, key: str) -> None:
        empty_jobs = []
        for job_id, keys in self._job_vm_placeholders.items():
            if key in keys:
                keys.discard(key)
                if not keys:
                    empty_jobs.append(job_id)
        for job_id in empty_jobs:
            self._job_vm_placeholders.pop(job_id, None)

    def _clear_host_vms(self, hostname: str, preserve_placeholders: bool = False) -> None:
        active_placeholder_keys = self._active_placeholder_keys() if preserve_placeholders else set()
        keys_to_remove = [
            key for key in list(self.vms.keys())
            if key.startswith(f"{hostname}:") and key not in active_placeholder_keys
        ]
        for key in keys_to_remove:
            del self.vms[key]

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            logger.debug("Unable to coerce %r to float; using default %s", value, default)
            return default

    def _coerce_int(self, value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            logger.debug("Unable to coerce %r to int; using default %s", value, default)
            return default

    def _infer_os_family(self, os_name: Any) -> Optional[OSFamily]:
        if not os_name or not isinstance(os_name, str):
            return None

        lowered = os_name.lower()
        if "windows" in lowered:
            return OSFamily.WINDOWS
        if any(keyword in lowered for keyword in ("linux", "ubuntu", "debian", "centos", "rhel")):
            return OSFamily.LINUX
        return None

    def _ps_string_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def track_job_vm(self, job_id: str, vm_name: str, host: str) -> None:
        """Track a VM being created by an in-progress job."""
        if not job_id or not vm_name or not host:
            return

        key = f"{host}:{vm_name}"
        placeholder = VM(
            name=vm_name,
            host=host,
            state=VMState.CREATING,
            cpu_cores=0,
            memory_gb=0.0
        )
        self.vms[key] = placeholder
        self._job_vm_placeholders.setdefault(job_id, set()).add(key)
        logger.info(
            "Tracking in-progress VM %s on host %s for job %s", vm_name, host, job_id
        )

    def clear_job_vm(self, job_id: str) -> None:
        """Remove any placeholder VMs tracked for a job."""
        keys = self._job_vm_placeholders.pop(job_id, set())
        for key in keys:
            vm = self.vms.get(key)
            if vm and vm.state == VMState.CREATING:
                del self.vms[key]
        logger.info("Cleared in-progress VM placeholders for job %s", job_id)

    def get_all_clusters(self) -> List[Cluster]:
        """Get all clusters."""
        return list(self.clusters.values())

    def get_all_hosts(self) -> List[Host]:
        """Get all hosts."""
        return list(self.hosts.values())

    def get_connected_hosts(self) -> List[Host]:
        """Get only connected hosts."""
        return [host for host in self.hosts.values() if host.connected]

    def get_disconnected_hosts(self) -> List[Host]:
        """Get only disconnected hosts."""
        return [host for host in self.hosts.values() if not host.connected]

    def get_all_vms(self) -> List[VM]:
        """Get all VMs across all hosts."""
        return list(self.vms.values())

    def get_host_vms(self, hostname: str) -> List[VM]:
        """Get VMs for a specific host."""
        return [vm for vm in self.vms.values() if vm.host == hostname]

    def get_vm(self, hostname: str, vm_name: str) -> Optional[VM]:
        """Get a specific VM."""
        key = f"{hostname}:{vm_name}"
        return self.vms.get(key)


# Global inventory service instance
inventory_service = InventoryService()
