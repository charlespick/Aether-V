"""Inventory management service for tracking Hyper-V hosts and VMs."""

import asyncio
import hashlib
import itertools
import json
import logging
import random
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import PureWindowsPath
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, TypeVar

from ..core.config import settings
from ..core.models import (
    Cluster,
    Host,
    NotificationLevel,
    OSFamily,
    VM,
    VMState,
)
from .host_deployment_service import host_deployment_service, InventoryReadiness
from .notification_service import notification_service
from .remote_task_service import (
    remote_task_service,
    RemoteTaskCategory,
    RemoteTaskTimeoutError,
)
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


T = TypeVar("T")


INVENTORY_SCRIPT_NAME = "Inventory.Collect.ps1"
PREPARING_HOST_MESSAGE = "Preparing host, will retry later"


class InventoryScriptMissingError(RuntimeError):
    """Raised when the inventory collection script is missing on the host."""

    def __init__(self, hostname: str, script_path: str, message: str):
        super().__init__(message)
        self.hostname = hostname
        self.script_path = script_path
        self.detail = message


@dataclass(frozen=True)
class HostRefreshSnapshot:
    """Instructions describing how to apply a host refresh."""

    hostname: str
    refreshed: bool
    skipped: bool
    sequence: int
    host: Optional[Host] = None
    vms: List[VM] = field(default_factory=list)
    expected_vm_keys: Optional[Set[str]] = None
    mark_preparing: bool = False
    clear_preparing: bool = False
    error: Optional[str] = None
    host_last_refresh: Optional[datetime] = None
    clear_host_last_refresh: bool = False
    clear_host_vms: bool = False
    preserve_placeholders: bool = True
    record_duration: bool = False
    duration: Optional[float] = None
    expected_interval: Optional[float] = None


class InventoryService:
    """Service for managing inventory of hosts and VMs."""

    _VM_HA_FLAG_KEYS: tuple[str, ...] = (
        "high_availability",
        "highavailability",
        "ha_enabled",
        "haenabled",
        "clustered",
        "is_clustered",
        "isclustered",
        "vm_clustered",
        "vmclustered",
        "ha",
    )
    _CLUSTER_SENTINELS: Set[str] = {
        "",
        "default",
        "standalone",
        "stand-alone",
        "standalone host",
        "standalone-host",
        "none",
        "null",
        "n/a",
        "not clustered",
        "notclustered",
        "nonclustered",
        "single host",
        "single-host",
    }
    _BOOLEAN_TRUE_VALUES: Set[str] = {
        "1",
        "true",
        "yes",
        "enabled",
        "ha",
        "clustered",
        "high availability",
        "high-availability",
        "highavailability",
        "on",
    }
    _BOOLEAN_FALSE_VALUES: Set[str] = {
        "0",
        "false",
        "no",
        "disabled",
        "off",
        "standalone",
        "stand-alone",
        "not clustered",
        "notclustered",
        "nonclustered",
        "single host",
        "single-host",
    }

    def __init__(self):
        self.clusters: Dict[str, Cluster] = {}
        self.hosts: Dict[str, Host] = {}
        self.vms: Dict[str, VM] = {}  # Key is "hostname:vmname"
        self.last_refresh: Optional[datetime] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._initial_refresh_task: Optional[asyncio.Task] = None
        self._bootstrap_task: Optional[asyncio.Task] = None
        self._refresh_lock = asyncio.Lock()
        self._job_vm_placeholders: Dict[str, Set[str]] = {}
        self._job_vm_originals: Dict[str, Dict[str, Optional[VM]]] = {}
        self._host_last_refresh: Dict[str, datetime] = {}
        self._inventory_status_key = "inventory-loading"
        self._refresh_overrun_key = "inventory-refresh-capacity"
        self._refresh_overrun_active = False
        self._initial_refresh_event = asyncio.Event()
        self._initial_refresh_succeeded = False
        self._preparing_hosts: Set[str] = set()
        self._preparing_notification_prefix = "inventory-preparing"
        self._slow_host_notification_prefix = "inventory-slow-host"
        self._slow_hosts: Set[str] = set()
        self._total_host_refresh_duration = 0.0
        self._host_refresh_samples = 0
        self._average_host_refresh_seconds = 0.0
        self._snapshot_sequence_counter = itertools.count()
        self._host_last_applied_sequence: Dict[str, int] = {}

    async def start(self):
        """Start the inventory service and begin periodic refresh."""
        logger.info("Starting inventory service")

        self._initial_refresh_event.clear()
        self._initial_refresh_succeeded = False
        self._total_host_refresh_duration = 0.0
        self._host_refresh_samples = 0
        self._average_host_refresh_seconds = 0.0
        self._preparing_hosts.clear()
        self._slow_hosts.clear()

        if self._bootstrap_task and not self._bootstrap_task.done():
            logger.debug("Inventory bootstrap already running; skipping duplicate start")
            return

        loop = asyncio.get_running_loop()
        self._bootstrap_task = loop.create_task(self._bootstrap_startup_sequence())

    async def _bootstrap_startup_sequence(self) -> None:
        """Wait for dependencies before kicking off inventory refresh loops."""

        current_task = asyncio.current_task()
        try:
            deployment_summary = host_deployment_service.get_startup_summary()
            if deployment_summary:
                logger.info(
                    "Inventory bootstrap observing host deployment status=%s (success=%d failed=%d)",
                    deployment_summary.get("status"),
                    deployment_summary.get("successful_hosts", 0),
                    deployment_summary.get("failed_hosts", 0),
                )

            if settings.dummy_data:
                logger.info("DUMMY_DATA enabled - using development data")
                await self._initialize_dummy_data()
                self._refresh_task = asyncio.create_task(self._dummy_refresh_loop())
                self._initial_refresh_task = None
                self._initial_refresh_event.set()
                self._initial_refresh_succeeded = True
                return

            self._notify_inventory_status(
                title="Inventory refresh in progress",
                message=(
                    "Initial inventory synchronisation is running; host and VM data may be "
                    "incomplete until it finishes."
                ),
                level=NotificationLevel.INFO,
                metadata={"phase": "startup"},
            )

            loop = asyncio.get_running_loop()
            self._initial_refresh_task = loop.create_task(self._run_initial_refresh())
            self._refresh_task = loop.create_task(self._staggered_refresh_loop())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Inventory bootstrap failed: %s", exc)
            self._notify_inventory_status(
                title="Inventory refresh failed",
                message=(
                    "Inventory service could not start because dependencies were unavailable: %s"
                )
                % exc,
                level=NotificationLevel.ERROR,
                metadata={"phase": "startup", "error": str(exc)},
            )
            self._initial_refresh_event.set()
        finally:
            if self._bootstrap_task is current_task:
                self._bootstrap_task = None

    async def _run_initial_refresh(self) -> None:
        try:
            await self.refresh_inventory(reason="startup")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Initial inventory refresh failed: %s", exc)
            self._notify_inventory_status(
                title="Inventory refresh failed",
                message=(
                    "Initial inventory synchronisation failed: %s. Background refresh "
                    "will continue attempting to update data."
                )
                % exc,
                level=NotificationLevel.ERROR,
                metadata={"phase": "startup", "error": str(exc)},
            )
        else:
            self._initial_refresh_succeeded = True
            self._notify_inventory_status(
                title="Inventory synchronised",
                message="Initial inventory synchronisation completed successfully.",
                level=NotificationLevel.SUCCESS,
                metadata={
                    "phase": "startup",
                    "last_refresh": (
                        self.last_refresh.isoformat() if self.last_refresh else None
                    ),
                },
            )
        finally:
            self._initial_refresh_event.set()

    async def stop(self):
        """Stop the inventory service."""
        logger.info("Stopping inventory service")
        if self._bootstrap_task:
            self._bootstrap_task.cancel()
            try:
                await self._bootstrap_task
            except asyncio.CancelledError:
                logger.debug("Inventory bootstrap task cancellation acknowledged")
            self._bootstrap_task = None
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                logger.debug("Inventory refresh loop cancelled")
            self._refresh_task = None
        if self._initial_refresh_task:
            self._initial_refresh_task.cancel()
            try:
                await self._initial_refresh_task
            except asyncio.CancelledError:
                logger.debug("Initial inventory refresh task cancelled")
            self._initial_refresh_task = None

        notification_service.clear_system_notification(self._inventory_status_key)
        notification_service.clear_system_notification(self._refresh_overrun_key)
        for hostname in list(self._preparing_hosts):
            notification_service.clear_system_notification(
                self._preparing_notification_key(hostname)
            )
        self._preparing_hosts.clear()
        for hostname in list(self._slow_hosts):
            notification_service.clear_system_notification(
                self._slow_host_notification_key(hostname)
            )
        self._slow_hosts.clear()

    async def _initialize_dummy_data(self):
        """Initialize with dummy data for development."""
        logger.info("Initializing dummy data for development")

        # Create dummy clusters
        cluster1 = Cluster(
            name="Production",
            hosts=["hyperv01.lab.local", "hyperv02.lab.local"],
            connected_hosts=2,
            total_hosts=2,
        )

        cluster2 = Cluster(
            name="Development",
            hosts=["hyperv-dev01.lab.local"],
            connected_hosts=1,
            total_hosts=1,
        )

        self.clusters = {"Production": cluster1, "Development": cluster2}

        # Create connected hosts with VMs
        now = datetime.utcnow()

        # Production cluster hosts
        self.hosts["hyperv01.lab.local"] = Host(
            hostname="hyperv01.lab.local",
            cluster="Production",
            connected=True,
            last_seen=now,
            error=None,
        )

        self.hosts["hyperv02.lab.local"] = Host(
            hostname="hyperv02.lab.local",
            cluster="Production",
            connected=True,
            last_seen=now,
            error=None,
        )

        # Development cluster host
        self.hosts["hyperv-dev01.lab.local"] = Host(
            hostname="hyperv-dev01.lab.local",
            cluster="Development",
            connected=True,
            last_seen=now,
            error=None,
        )

        # Add a few disconnected hosts
        self.hosts["hyperv03.lab.local"] = Host(
            hostname="hyperv03.lab.local",
            cluster=None,  # No cluster assignment
            connected=False,
            last_seen=now - timedelta(hours=2),
            error="Connection timeout",
        )

        self.hosts["hyperv-backup01.lab.local"] = Host(
            hostname="hyperv-backup01.lab.local",
            cluster=None,
            connected=False,
            last_seen=now - timedelta(minutes=30),
            error="WinRM authentication failed",
        )

        # Create dummy VMs
        dummy_vms = [
            # VMs on hyperv01
            VM(
                name="web-server-01",
                host="hyperv01.lab.local",
                state=VMState.RUNNING,
                cpu_cores=4,
                memory_gb=8.0,
                os_family=OSFamily.LINUX,
                created_at=now - timedelta(days=5),
                cluster="Production",
                high_availability=True,
            ),
            VM(
                name="db-server-01",
                host="hyperv01.lab.local",
                state=VMState.RUNNING,
                cpu_cores=8,
                memory_gb=16.0,
                os_family=OSFamily.LINUX,
                created_at=now - timedelta(days=10),
                cluster="Production",
                high_availability=True,
            ),
            VM(
                name="win-app-01",
                host="hyperv01.lab.local",
                state=VMState.OFF,
                cpu_cores=2,
                memory_gb=4.0,
                os_family=OSFamily.WINDOWS,
                created_at=now - timedelta(days=2),
                cluster="Production",
                high_availability=True,
            ),
            # VMs on hyperv02
            VM(
                name="load-balancer-01",
                host="hyperv02.lab.local",
                state=VMState.RUNNING,
                cpu_cores=2,
                memory_gb=4.0,
                os_family=OSFamily.LINUX,
                created_at=now - timedelta(days=7),
                cluster="Production",
                high_availability=True,
            ),
            VM(
                name="monitoring-01",
                host="hyperv02.lab.local",
                state=VMState.RUNNING,
                cpu_cores=4,
                memory_gb=8.0,
                os_family=OSFamily.LINUX,
                created_at=now - timedelta(days=3),
                cluster="Production",
                high_availability=True,
            ),
            VM(
                name="backup-vm",
                host="hyperv02.lab.local",
                state=VMState.SAVED,
                cpu_cores=1,
                memory_gb=2.0,
                os_family=OSFamily.WINDOWS,
                created_at=now - timedelta(days=15),
                cluster="Production",
                high_availability=True,
            ),
            # VMs on dev host
            VM(
                name="test-vm-01",
                host="hyperv-dev01.lab.local",
                state=VMState.RUNNING,
                cpu_cores=2,
                memory_gb=4.0,
                os_family=OSFamily.LINUX,
                created_at=now - timedelta(days=1),
                cluster="Development",
                high_availability=True,
            ),
            VM(
                name="dev-workstation",
                host="hyperv-dev01.lab.local",
                state=VMState.PAUSED,
                cpu_cores=4,
                memory_gb=8.0,
                os_family=OSFamily.WINDOWS,
                created_at=now - timedelta(hours=8),
                cluster="Development",
                high_availability=True,
            ),
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
            logger.warning(
                f"Artifact deployment completed with "
                f"{failed} failure(s) and {successful} success(es)"
            )
        else:
            logger.info(
                f"Artifact deployment completed successfully "
                f"to all {successful} host(s)"
            )

    async def _dummy_refresh_loop(self):
        """Periodically refresh dummy inventory data for development mode."""
        while True:
            try:
                await asyncio.sleep(settings.inventory_refresh_interval)
                await self._refresh_dummy_data()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in dummy inventory refresh: %s", exc)

    async def _staggered_refresh_loop(self):
        """Spread inventory refreshes across the configured interval."""

        interval = max(1.0, float(settings.inventory_refresh_interval))

        while True:
            cycle_start = time.perf_counter()
            host_list = [host for host in settings.get_hyperv_hosts_list() if host]

            if not host_list:
                logger.debug(
                    "No Hyper-V hosts configured; sleeping until next interval"
                )
                await asyncio.sleep(interval)
                self._finalise_cycle_refresh([], cycle_start, interval)
                continue

            ordered_hosts = self._ordered_hosts(host_list)
            per_host_delay = interval / max(len(ordered_hosts), 1)
            cycle_skipped: List[str] = []
            cycle_refreshed: List[str] = []

            for index, hostname in enumerate(ordered_hosts):
                rebuild_clusters = index == len(ordered_hosts) - 1
                try:
                    result = await self.refresh_inventory(
                        [hostname],
                        rebuild_clusters=rebuild_clusters,
                        reason="background",
                        expected_interval=interval,
                    )
                    cycle_refreshed.extend(result.get("refreshed_hosts", []))
                    cycle_skipped.extend(result.get("skipped_hosts", []))
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Background refresh for %s failed: %s", hostname, exc)

                if index < len(ordered_hosts) - 1:
                    await asyncio.sleep(per_host_delay)

            self._finalise_cycle_refresh(
                ordered_hosts,
                cycle_start,
                interval,
                skipped_hosts=cycle_skipped,
                refreshed_hosts=cycle_refreshed,
            )

            elapsed = time.perf_counter() - cycle_start
            remaining = interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)

    def _ordered_hosts(self, hosts: Iterable[str]) -> List[str]:
        return sorted(
            hosts,
            key=lambda host: (self._stable_host_hash(host), host.lower()),
        )

    def _finalise_cycle_refresh(
        self,
        hosts_in_cycle: Iterable[str],
        cycle_start: float,
        interval: float,
        *,
        skipped_hosts: Optional[Sequence[str]] = None,
        refreshed_hosts: Optional[Sequence[str]] = None,
    ) -> None:
        duration = time.perf_counter() - cycle_start
        cycle_hosts = list(hosts_in_cycle)
        host_count = len(cycle_hosts)
        configured_hosts = [host for host in settings.get_hyperv_hosts_list() if host]
        skipped_list = list(skipped_hosts or [])
        refreshed_list = list(refreshed_hosts or [])

        if not configured_hosts:
            # Inventory cleared elsewhere when no hosts are configured, but ensure
            # last_refresh stays current so readiness probes succeed.
            self.last_refresh = datetime.utcnow()
            self._notify_inventory_status(
                title="Inventory synchronised",
                message="No Hyper-V hosts are configured; inventory data is empty.",
                level=NotificationLevel.INFO,
                metadata={
                    "hosts_in_cycle": host_count,
                    "cycle_duration_seconds": round(duration, 2),
                    "interval_seconds": interval,
                    "hosts": cycle_hosts,
                    "skipped_hosts": skipped_list,
                    "refreshed_hosts": refreshed_list,
                },
            )
            self._handle_refresh_overrun(duration, interval, host_count)
            return

        if self.last_refresh:
            metadata = {
                "hosts_in_cycle": host_count,
                "cycle_duration_seconds": round(duration, 2),
                "interval_seconds": interval,
                "last_refresh": self.last_refresh.isoformat(),
                "hosts": cycle_hosts,
                "skipped_hosts": skipped_list,
                "refreshed_hosts": refreshed_list,
                "average_host_refresh_seconds": round(
                    self._average_host_refresh_seconds, 2
                ),
            }
            self._notify_inventory_status(
                title="Inventory synchronised",
                message=(
                    "Inventory data is current; background refresh continues in a "
                    "staggered cycle."
                ),
                level=NotificationLevel.SUCCESS,
                metadata=metadata,
            )

        self._handle_refresh_overrun(duration, interval, host_count)

    def _handle_refresh_overrun(
        self, duration: float, interval: float, host_count: int
    ) -> None:
        if host_count == 0:
            if self._refresh_overrun_active:
                notification_service.clear_system_notification(
                    self._refresh_overrun_key
                )
                self._refresh_overrun_active = False
            return

        if not self._host_refresh_samples:
            if self._refresh_overrun_active:
                notification_service.clear_system_notification(
                    self._refresh_overrun_key
                )
                self._refresh_overrun_active = False
            return

        average_duration = self._average_host_refresh_seconds

        if average_duration > interval:
            message = (
                "Average per-host inventory refresh is %.1fs which exceeds the "
                "configured interval of %.1fs. Hosts are too slow for your "
                "configuration; consider adjusting the interval or investigating "
                "host performance."
            ) % (average_duration, interval)
            metadata = {
                "cycle_duration_seconds": round(duration, 2),
                "interval_seconds": interval,
                "hosts_in_cycle": host_count,
                "average_host_refresh_seconds": round(average_duration, 2),
            }
            notification_service.upsert_system_notification(
                self._refresh_overrun_key,
                title="Inventory refresh saturation detected",
                message=message,
                level=NotificationLevel.WARNING,
                metadata=metadata,
            )
            self._refresh_overrun_active = True
        elif self._refresh_overrun_active:
            notification_service.clear_system_notification(self._refresh_overrun_key)
            self._refresh_overrun_active = False

    def _notify_inventory_status(
        self,
        *,
        title: str,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        notification_service.upsert_system_notification(
            self._inventory_status_key,
            title=title,
            message=message,
            level=level,
            metadata=metadata,
        )

    def _stable_host_hash(self, hostname: str) -> int:
        return int(hashlib.sha1(hostname.encode("utf-8")).hexdigest(), 16)

    async def refresh_inventory(
        self,
        hostnames: Optional[Sequence[str]] = None,
        *,
        rebuild_clusters: bool = True,
        reason: str = "manual",
        expected_interval: Optional[float] = None,
    ) -> Dict[str, List[str]]:
        """Refresh inventory from configured hosts."""

        if settings.dummy_data:
            await self._refresh_dummy_data()
            return {"refreshed_hosts": [], "skipped_hosts": []}

        configured_hosts = [host for host in settings.get_hyperv_hosts_list() if host]
        target_hosts = (
            [host for host in hostnames if host]
            if hostnames is not None
            else configured_hosts
        )

        if not configured_hosts:
            logger.info("No Hyper-V hosts configured; clearing inventory state")
            async with self._refresh_lock:
                self.clusters.clear()
                self.hosts.clear()
                self.vms.clear()
                self._host_last_refresh.clear()
                self._host_last_applied_sequence.clear()
                self.last_refresh = datetime.utcnow()
            return {"refreshed_hosts": [], "skipped_hosts": []}

        if not target_hosts:
            logger.debug("No target hosts provided for refresh; skipping")
            return {"refreshed_hosts": [], "skipped_hosts": []}

        refreshed_hosts: List[str] = []
        skipped_hosts: List[str] = []

        logger.info(
            "Refreshing inventory (%s) for %d host(s)",
            reason,
            len(target_hosts),
        )

        for hostname in target_hosts:
            snapshot = await self._refresh_host(
                hostname,
                reason=reason,
                expected_interval=expected_interval if reason == "background" else None,
            )
            await self._apply_host_snapshot(snapshot)
            if snapshot.refreshed:
                refreshed_hosts.append(hostname)
            if snapshot.skipped:
                skipped_hosts.append(hostname)

        removed_hosts = await self._prune_unconfigured_hosts(configured_hosts)
        if removed_hosts:
            logger.info(
                "Pruned %d host(s) no longer configured: %s",
                len(removed_hosts),
                removed_hosts,
            )

        if rebuild_clusters and refreshed_hosts:
            async with self._refresh_lock:
                self._rebuild_clusters(configured_hosts)
                self.last_refresh = datetime.utcnow()
                connected_hosts = len([host for host in self.hosts.values() if host.connected])
                total_vms = len(self.vms)
            logger.info(
                "Inventory refresh (%s) completed. Connected hosts: %d, Total VMs: %d",
                reason,
                connected_hosts,
                total_vms,
            )
        elif rebuild_clusters and not refreshed_hosts:
            logger.info(
                "Inventory refresh (%s) deferred; %d host(s) pending preparation",
                reason,
                len(skipped_hosts),
            )

        return {"refreshed_hosts": refreshed_hosts, "skipped_hosts": skipped_hosts}

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

                logger.info(f"Dummy data: Changed {vm.name} state to {vm.state}")

        self.last_refresh = datetime.utcnow()

    async def _apply_host_snapshot(self, snapshot: HostRefreshSnapshot) -> None:
        """Apply a host refresh snapshot while holding the refresh lock."""

        async with self._refresh_lock:
            last_sequence = self._host_last_applied_sequence.get(snapshot.hostname, -1)
            if snapshot.sequence < last_sequence:
                logger.debug(
                    "Discarding stale refresh snapshot for host %s (sequence %d < %d)",
                    snapshot.hostname,
                    snapshot.sequence,
                    last_sequence,
                )
                return

            previous_host = self.hosts.get(snapshot.hostname)
            self._apply_host_snapshot_locked(snapshot, previous_host)
            self._host_last_applied_sequence[snapshot.hostname] = snapshot.sequence

    def _apply_host_snapshot_locked(
        self,
        snapshot: HostRefreshSnapshot,
        previous_host: Optional[Host],
    ) -> None:
        """Apply host refresh mutations. Caller must hold ``_refresh_lock``."""

        if snapshot.mark_preparing:
            self._mark_host_preparing(snapshot.hostname)
            return

        if snapshot.clear_preparing:
            self._clear_preparing_host(snapshot.hostname)

        if snapshot.host is not None:
            self.hosts[snapshot.hostname] = snapshot.host

        if snapshot.clear_host_vms:
            self._clear_host_vms(
                snapshot.hostname, preserve_placeholders=snapshot.preserve_placeholders
            )

        for vm in snapshot.vms:
            key = f"{snapshot.hostname}:{vm.name}"
            self._detach_placeholder_key(key)
            self.vms[key] = vm

        if snapshot.expected_vm_keys is not None:
            active_placeholder_keys = self._active_placeholder_keys()
            keys_to_remove = [
                key
                for key in list(self.vms.keys())
                if key.startswith(f"{snapshot.hostname}:")
                and key not in snapshot.expected_vm_keys
                and key not in active_placeholder_keys
            ]
            for key in keys_to_remove:
                del self.vms[key]

        if snapshot.host_last_refresh is not None:
            self._host_last_refresh[snapshot.hostname] = snapshot.host_last_refresh

        if snapshot.clear_host_last_refresh:
            self._host_last_refresh.pop(snapshot.hostname, None)

        if snapshot.refreshed and not settings.dummy_data:
            if previous_host and not previous_host.connected:
                notification_service.create_host_reconnected_notification(snapshot.hostname)
        elif snapshot.error and not settings.dummy_data:
            if previous_host and previous_host.connected:
                notification_service.create_host_unreachable_notification(
                    snapshot.hostname, snapshot.error
                )

        if (
            snapshot.record_duration
            and snapshot.duration is not None
            and snapshot.expected_interval is not None
        ):
            self._record_host_refresh_duration(
                snapshot.hostname,
                snapshot.duration,
                snapshot.expected_interval,
                snapshot.refreshed,
            )

    async def _refresh_host(
        self,
        hostname: str,
        *,
        reason: str,
        expected_interval: Optional[float],
    ) -> HostRefreshSnapshot:
        """Refresh inventory for a single host and return a mutation snapshot."""

        logger.info("Refreshing inventory for host: %s", hostname)

        sequence = next(self._snapshot_sequence_counter)
        previous_host = self.hosts.get(hostname)
        readiness = await self._ensure_host_ready(hostname)

        if readiness.preparing:
            logger.info(
                "Host %s is still preparing required artifacts; deferring inventory refresh",
                hostname,
            )
            return HostRefreshSnapshot(
                hostname=hostname,
                refreshed=False,
                skipped=True,
                sequence=sequence,
                mark_preparing=True,
            )

        if readiness.error:
            logger.debug(
                "Host %s not ready for inventory due to deployment error: %s",
                hostname,
                readiness.error,
            )

        attempt_started = False
        start_time = 0.0
        snapshot: HostRefreshSnapshot

        try:
            attempt_started = True
            start_time = time.perf_counter()
            payload = await self._collect_with_recovery(hostname)
            cluster_name, vms = self._parse_inventory_snapshot(hostname, payload)

            now = datetime.utcnow()
            expected_keys = {f"{hostname}:{vm.name}" for vm in vms}
            snapshot = HostRefreshSnapshot(
                hostname=hostname,
                refreshed=True,
                skipped=False,
                sequence=sequence,
                host=Host(
                    hostname=hostname,
                    cluster=cluster_name,
                    connected=True,
                    last_seen=now,
                    error=None,
                ),
                vms=vms,
                expected_vm_keys=expected_keys,
                clear_preparing=True,
                host_last_refresh=now,
            )

            logger.info("Host %s: %d VMs", hostname, len(vms))

        except Exception as exc:
            logger.error("Failed to refresh host %s: %s", hostname, exc)

            cluster = previous_host.cluster if previous_host else None
            last_seen = previous_host.last_seen if previous_host else None
            snapshot = HostRefreshSnapshot(
                hostname=hostname,
                refreshed=False,
                skipped=False,
                sequence=sequence,
                host=Host(
                    hostname=hostname,
                    cluster=cluster,
                    connected=False,
                    last_seen=last_seen,
                    error=str(exc),
                ),
                error=str(exc),
                clear_preparing=True,
                clear_host_vms=True,
                clear_host_last_refresh=True,
            )

        finally:
            if attempt_started and expected_interval is not None and reason == "background":
                snapshot = replace(
                    snapshot,
                    record_duration=True,
                    duration=time.perf_counter() - start_time,
                    expected_interval=expected_interval,
                )

        return snapshot

    async def _prune_unconfigured_hosts(
        self, configured_hosts: Sequence[str]
    ) -> List[str]:
        """Remove state for hosts that are no longer configured."""

        async with self._refresh_lock:
            configured_set = {host for host in configured_hosts if host}
            stale_hosts = [
                hostname for hostname in list(self.hosts.keys()) if hostname not in configured_set
            ]

            if not stale_hosts:
                return []

            for hostname in stale_hosts:
                prefix = f"{hostname}:"

                # Clear preparing state and notifications.
                self._clear_preparing_host(hostname)

                # Clear slow host tracking and notification if active.
                if hostname in self._slow_hosts:
                    notification_service.clear_system_notification(
                        self._slow_host_notification_key(hostname)
                    )
                    self._slow_hosts.discard(hostname)

                # Remove VM entries and associated placeholder bookkeeping.
                host_vm_keys = [
                    key for key in list(self.vms.keys()) if key.startswith(prefix)
                ]
                for key in host_vm_keys:
                    self._detach_placeholder_key(key)
                    self.vms.pop(key, None)

                for job_id, keys in list(self._job_vm_placeholders.items()):
                    filtered_keys = {key for key in keys if not key.startswith(prefix)}
                    if filtered_keys:
                        self._job_vm_placeholders[job_id] = filtered_keys
                    else:
                        self._job_vm_placeholders.pop(job_id, None)

                for job_id, originals in list(self._job_vm_originals.items()):
                    keys_to_remove = [
                        key for key in list(originals.keys()) if key.startswith(prefix)
                    ]
                    for key in keys_to_remove:
                        originals.pop(key, None)
                    if not originals:
                        self._job_vm_originals.pop(job_id, None)

                self.hosts.pop(hostname, None)
                self._host_last_refresh.pop(hostname, None)
                self._host_last_applied_sequence.pop(hostname, None)

            return stale_hosts

    async def _ensure_host_ready(self, hostname: str) -> InventoryReadiness:
        """Check whether a host is ready for inventory collection."""

        if settings.dummy_data or not host_deployment_service.is_enabled:
            return InventoryReadiness(ready=True, preparing=False, error=None)

        try:
            readiness = await host_deployment_service.ensure_inventory_ready(hostname)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to verify deployment readiness for %s: %s", hostname, exc
            )
            readiness = InventoryReadiness(ready=False, preparing=False, error=str(exc))

        if readiness is None:
            readiness = InventoryReadiness(ready=True, preparing=False, error=None)

        return readiness

    def _mark_host_preparing(self, hostname: str) -> None:
        """Record that a host is still preparing deployment artifacts."""

        previous_host = self.hosts.get(hostname)
        last_seen = previous_host.last_seen if previous_host else None
        cluster = previous_host.cluster if previous_host else None

        self.hosts[hostname] = Host(
            hostname=hostname,
            cluster=cluster,
            connected=False,
            last_seen=last_seen,
            error=PREPARING_HOST_MESSAGE,
        )
        self._host_last_refresh.pop(hostname, None)

        key = self._preparing_notification_key(hostname)
        notification_service.upsert_system_notification(
            key,
            title="Preparing host for inventory",
            message=(
                f"Host {hostname} is synchronising provisioning artifacts. "
                "Inventory refresh will retry automatically."
            ),
            level=NotificationLevel.INFO,
            metadata={"host": hostname},
        )
        self._preparing_hosts.add(hostname)

    def _clear_preparing_host(self, hostname: str) -> None:
        """Clear preparing state and notifications for a host."""

        if hostname in self._preparing_hosts:
            notification_service.clear_system_notification(
                self._preparing_notification_key(hostname)
            )
            self._preparing_hosts.discard(hostname)

        host = self.hosts.get(hostname)
        if host and host.error == PREPARING_HOST_MESSAGE:
            host.error = None

    def _record_host_refresh_duration(
        self,
        hostname: str,
        duration: float,
        interval: float,
        success: bool,
    ) -> None:
        """Track host refresh duration and surface warnings for overruns."""

        self._total_host_refresh_duration += duration
        self._host_refresh_samples += 1
        self._average_host_refresh_seconds = (
            self._total_host_refresh_duration / self._host_refresh_samples

        )

        if duration > interval:
            metadata = {
                "host": hostname,
                "duration_seconds": round(duration, 2),
                "interval_seconds": interval,
                "refresh_succeeded": success,
            }
            notification_service.upsert_system_notification(
                self._slow_host_notification_key(hostname),
                title="Inventory refresh exceeded interval",
                message=(
                    f"Inventory refresh for {hostname} took {duration:.1f}s, exceeding "
                    f"the configured interval of {interval:.1f}s."
                ),
                level=NotificationLevel.WARNING,
                metadata=metadata,
            )
            self._slow_hosts.add(hostname)
        elif hostname in self._slow_hosts:
            notification_service.clear_system_notification(
                self._slow_host_notification_key(hostname)
            )
            self._slow_hosts.discard(hostname)

    def _preparing_notification_key(self, hostname: str) -> str:
        return f"{self._preparing_notification_prefix}:{hostname}"

    def _slow_host_notification_key(self, hostname: str) -> str:
        return f"{self._slow_host_notification_prefix}:{hostname}"

    async def _collect_with_recovery(self, hostname: str) -> Dict[str, Any]:
        """Collect inventory from a host, redeploying scripts if they are missing."""

        attempt = 0

        while True:
            attempt += 1
            try:
                return await self._run_winrm_call(
                    hostname,
                    self._collect_host_inventory,
                    description=f"inventory collection for {hostname}",
                )
            except InventoryScriptMissingError as exc:
                logger.warning(
                    "Inventory script missing on %s; attempting redeployment (attempt %d)",
                    hostname,
                    attempt,
                )

                if not host_deployment_service.is_enabled:
                    raise RuntimeError(
                        "Required inventory scripts are missing and host deployment service is disabled"
                    ) from exc

                redeployed = await host_deployment_service.ensure_host_setup(hostname)

                if not redeployed:
                    raise RuntimeError(
                        "Redeployment failed while recovering missing inventory scripts"
                    ) from exc

                if attempt >= 2:
                    raise RuntimeError(
                        "Inventory scripts still missing after redeployment"
                    ) from exc

                logger.info(
                    "Redeployment of scripts to %s succeeded; retrying inventory collection",
                    hostname,
                )
                await asyncio.sleep(0)
                continue

    async def _run_winrm_call(
        self,
        hostname: str,
        func: Callable[..., T],
        *args: Any,
        description: str,
    ) -> T:
        """Execute a potentially blocking WinRM call with a timeout."""

        timeout = max(1.0, float(settings.winrm_operation_timeout))
        start = time.perf_counter()
        logger.debug(
            "Queueing inventory WinRM operation (%s) on %s with timeout %.1fs",
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
                category=RemoteTaskCategory.INVENTORY,
                timeout=timeout,
            )
        except RemoteTaskTimeoutError as exc:
            logger.error(
                "Inventory WinRM operation (%s) on %s exceeded timeout of %.1fs",
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
                "Inventory WinRM operation (%s) on %s raised after %.2fs",
                description,
                hostname,
                duration,
                exc_info=True,
            )
            raise
        else:
            duration = time.perf_counter() - start
            logger.debug(
                "Inventory WinRM operation (%s) on %s completed in %.2fs",
                description,
                hostname,
                duration,
            )
            return result

    def _collect_host_inventory(self, hostname: str) -> Dict[str, Any]:
        """Execute the inventory collection script on the target host."""

        script_path = str(
            PureWindowsPath(settings.host_install_directory) / INVENTORY_SCRIPT_NAME
        )
        stdout, stderr, exit_code = winrm_service.execute_ps_script(
            hostname,
            script_path,
            {"ComputerName": hostname},
        )

        logger.debug(
            "Inventory script on %s exit=%s stdout_len=%d stderr_len=%d",
            hostname,
            exit_code,
            len(stdout.encode("utf-8")),
            len(stderr.encode("utf-8")),
        )

        if exit_code != 0:
            preview = stderr.strip() or stdout.strip()
            lowered_preview = preview.lower()
            normalised_path = script_path.lower()

            missing_tokens = (
                "not recognized" in lowered_preview
                or "cannot find" in lowered_preview
                or "cannot be found" in lowered_preview
            )
            mentions_script = normalised_path in lowered_preview

            if missing_tokens and mentions_script:
                raise InventoryScriptMissingError(
                    hostname,
                    script_path,
                    f"Inventory script missing on {hostname}: {preview}",
                )

            raise RuntimeError(
                f"Inventory collection failed (exit={exit_code}): {preview}"
            )

        raw_output = stdout.strip().lstrip("\ufeff")
        if not raw_output:
            raise RuntimeError("Inventory script returned no data")

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse inventory payload from %s: %s",
                hostname,
                exc,
            )
            logger.debug("Raw inventory payload from %s: %s", hostname, stdout)
            raise

        if not isinstance(payload, dict):
            raise ValueError(
                f"Unexpected inventory payload type from {hostname}: {type(payload).__name__}"
            )

        return payload

    @classmethod
    def _normalize_cluster_name(cls, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        lowered = text.lower()
        if lowered in cls._CLUSTER_SENTINELS:
            return None

        return text

    @classmethod
    def _coerce_optional_bool(cls, value: Any) -> Optional[bool]:
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False

        if isinstance(value, str):
            normalized = value.strip().lower()
            if not normalized:
                return None
            if normalized in cls._BOOLEAN_TRUE_VALUES:
                return True
            if normalized in cls._BOOLEAN_FALSE_VALUES:
                return False

        return None

    @classmethod
    def _derive_vm_high_availability(
        cls,
        normalized_vm_fields: Dict[str, Any],
        cluster_name: Optional[str],
        host_present: bool,
    ) -> Optional[bool]:
        for key in cls._VM_HA_FLAG_KEYS:
            if key in normalized_vm_fields:
                result = cls._coerce_optional_bool(normalized_vm_fields[key])
                if result is not None:
                    return result

        if cluster_name:
            return True

        if host_present:
            return False

        return None

    def _parse_inventory_snapshot(
        self, hostname: str, payload: Dict[str, Any]
    ) -> tuple[str, List[VM]]:
        """Normalise the inventory payload from the host script."""

        host_section = payload.get("Host")
        if not isinstance(host_section, dict):
            host_section = {}

        warnings: List[str] = []
        for source in (payload.get("Warnings"), host_section.get("Warnings")):
            if isinstance(source, list):
                warnings.extend(str(item) for item in source if item)

        for warning in warnings:
            logger.warning("Inventory warning on %s: %s", hostname, warning)

        error_message = host_section.get("Error")
        if error_message:
            raise RuntimeError(f"Inventory script reported an error: {error_message}")

        raw_cluster_name = host_section.get("ClusterName")
        normalized_cluster = self._normalize_cluster_name(raw_cluster_name)
        cluster_name = normalized_cluster or "Default"
        vm_payload = payload.get("VirtualMachines")

        vms = self._deserialize_vms(
            hostname,
            vm_payload,
            host_cluster=normalized_cluster,
            host_present=True,
        )
        return cluster_name, vms

    def _deserialize_vms(
        self,
        hostname: str,
        data: Any,
        *,
        host_cluster: Optional[str] = None,
        host_present: bool = False,
    ) -> List[VM]:
        """Convert raw VM payloads into VM models."""

        if data is None:
            logger.info("Host %s returned no VM data", hostname)
            return []

        if isinstance(data, dict):
            records = [data]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError(
                f"Unexpected VM payload type from {hostname}: {type(data).__name__}"
            )

        vms: List[VM] = []
        for vm_data in records:
            if not isinstance(vm_data, dict):
                logger.warning(
                    "Skipping VM entry from %s because it is not a dictionary: %r",
                    hostname,
                    vm_data,
                )
                continue

            normalized_fields: Dict[str, Any] = {}
            for key, value in vm_data.items():
                if key is None:
                    continue
                lowered_key = str(key).lower()
                if lowered_key not in normalized_fields:
                    normalized_fields[lowered_key] = value

            vm_cluster_override = self._normalize_cluster_name(
                normalized_fields.get("cluster")
                or normalized_fields.get("cluster_name")
                or normalized_fields.get("clustername")
            )
            cluster_name = vm_cluster_override or host_cluster

            state_str = vm_data.get("State", "Unknown")
            try:
                state = VMState(state_str)
            except ValueError:
                state = VMState.UNKNOWN

            memory_gb = self._coerce_float(vm_data.get("MemoryGB", 0.0), default=0.0)
            cpu_cores = self._coerce_int(vm_data.get("ProcessorCount", 0), default=0)
            os_family = self._infer_os_family(vm_data.get("OperatingSystem"))

            availability = self._derive_vm_high_availability(
                normalized_fields,
                cluster_name,
                host_present=host_present or host_cluster is not None,
            )

            vm = VM(
                name=vm_data.get("Name", ""),
                host=hostname,
                state=state,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                os_family=os_family,
                created_at=vm_data.get("CreationTime"),
                cluster=cluster_name,
                high_availability=availability,
            )
            vms.append(vm)

        return vms

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
                total_hosts=len(sorted_hosts),
            )

        self.clusters = new_clusters
        if new_clusters:
            logger.info(
                "Rebuilt cluster inventory: %s",
                {
                    name: cluster.connected_hosts
                    for name, cluster in new_clusters.items()
                },
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

    def _clear_host_vms(
        self, hostname: str, preserve_placeholders: bool = False
    ) -> None:
        active_placeholder_keys = (
            self._active_placeholder_keys() if preserve_placeholders else set()
        )
        keys_to_remove = [
            key
            for key in list(self.vms.keys())
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
            logger.debug(
                "Unable to coerce %r to float; using default %s", value, default
            )
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
        if any(
            keyword in lowered
            for keyword in ("linux", "ubuntu", "debian", "centos", "rhel")
        ):
            return OSFamily.LINUX
        return None

    def track_job_vm(self, job_id: str, vm_name: str, host: str) -> None:
        """Track a VM being created by an in-progress job."""
        if not job_id or not vm_name or not host:
            return

        key = f"{host}:{vm_name}"
        placeholder = VM(
            name=vm_name, host=host, state=VMState.CREATING, cpu_cores=0, memory_gb=0.0
        )
        self.vms[key] = placeholder
        self._job_vm_placeholders.setdefault(job_id, set()).add(key)
        self._job_vm_originals.pop(job_id, None)
        logger.info(
            "Tracking in-progress VM %s on host %s for job %s", vm_name, host, job_id
        )

    def clear_job_vm(self, job_id: str) -> None:
        """Remove any placeholder VMs tracked for a job."""
        keys = self._job_vm_placeholders.pop(job_id, set())
        for key in keys:
            vm = self.vms.get(key)
            if vm and vm.state in {VMState.CREATING, VMState.DELETING}:
                del self.vms[key]
        self._job_vm_originals.pop(job_id, None)
        logger.info("Cleared in-progress VM placeholders for job %s", job_id)

    def mark_vm_deleting(self, job_id: str, vm_name: str, host: str) -> None:
        """Mark a VM as deleting while a job is in progress."""

        if not job_id or not vm_name or not host:
            return

        key = f"{host}:{vm_name}"
        existing = self.vms.get(key)
        if existing:
            self._job_vm_originals.setdefault(job_id, {})[key] = existing.model_copy(deep=True)
            existing.state = VMState.DELETING
        else:
            self._job_vm_originals.setdefault(job_id, {})[key] = None
            self.vms[key] = VM(name=vm_name, host=host, state=VMState.DELETING, cpu_cores=0, memory_gb=0.0)

        self._job_vm_placeholders.setdefault(job_id, set()).add(key)
        logger.info(
            "Marking VM %s on host %s as deleting for job %s", vm_name, host, job_id
        )

    def finalize_vm_deletion(
        self, job_id: str, vm_name: str, host: str, success: bool
    ) -> None:
        """Apply inventory updates after a deletion job completes."""

        if not job_id or not vm_name or not host:
            return

        key = f"{host}:{vm_name}"
        original_map = self._job_vm_originals.pop(job_id, {})
        original_vm = original_map.get(key)
        placeholder_keys = self._job_vm_placeholders.pop(job_id, set())

        if success:
            if key in self.vms:
                self.vms.pop(key, None)
            logger.info(
                "Removed VM %s on host %s from inventory after successful deletion job %s",
                vm_name,
                host,
                job_id,
            )
        else:
            if original_vm is not None:
                self.vms[key] = original_vm
                logger.info(
                    "Restored VM %s on host %s to state %s after failed deletion job %s",
                    vm_name,
                    host,
                    original_vm.state,
                    job_id,
                )
            else:
                self.vms.pop(key, None)
                logger.info(
                    "Removed transient delete placeholder for VM %s on host %s after failed job %s",
                    vm_name,
                    host,
                    job_id,
                )

        for placeholder_key in placeholder_keys:
            if placeholder_key == key:
                continue
            vm = self.vms.get(placeholder_key)
            if vm and vm.state in {VMState.CREATING, VMState.DELETING}:
                del self.vms[placeholder_key]

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

    def has_completed_initial_refresh(self) -> bool:
        return self._initial_refresh_event.is_set()

    def initial_refresh_succeeded(self) -> bool:
        return self._initial_refresh_succeeded

    def get_metrics(self) -> Dict[str, Any]:
        """Return diagnostic information about inventory refresh behaviour."""

        bootstrap_running = (
            self._bootstrap_task is not None and not self._bootstrap_task.done()
        )
        refresh_loop_running = (
            self._refresh_task is not None and not self._refresh_task.done()
        )
        initial_refresh_running = (
            self._initial_refresh_task is not None
            and not self._initial_refresh_task.done()
        )

        return {
            "hosts_tracked": len(self.hosts),
            "vms_tracked": len(self.vms),
            "clusters_tracked": len(self.clusters),
            "last_refresh": self.last_refresh,
            "refresh_in_progress": self._refresh_lock.locked(),
            "bootstrap_running": bootstrap_running,
            "refresh_loop_running": refresh_loop_running,
            "initial_refresh_running": initial_refresh_running,
            "initial_refresh_completed": self._initial_refresh_event.is_set(),
            "initial_refresh_succeeded": self._initial_refresh_succeeded,
            "refresh_overrun": self._refresh_overrun_active,
            "host_refresh_timestamps": dict(self._host_last_refresh),
            "average_host_refresh_seconds": self._average_host_refresh_seconds,
            "host_refresh_samples": self._host_refresh_samples,
            "preparing_hosts": sorted(self._preparing_hosts),
            "slow_hosts": sorted(self._slow_hosts),
        }


# Global inventory service instance
inventory_service = InventoryService()
