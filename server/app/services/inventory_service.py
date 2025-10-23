"""Inventory management service for tracking Hyper-V hosts and VMs."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
import json
import random

from ..core.models import Host, VM, VMState, OSFamily, Cluster
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
        self._refresh_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the inventory service and begin periodic refresh."""
        logger.info("Starting inventory service")

        if settings.dummy_data:
            logger.info("DUMMY_DATA enabled - using development data")
            await self._initialize_dummy_data()
        else:
            # Deploy artifacts to hosts first
            await self._deploy_artifacts_to_hosts()

            # Then refresh inventory
            await self.refresh_inventory()

        # Start background refresh task
        self._refresh_task = asyncio.create_task(self._periodic_refresh())

    async def stop(self):
        """Stop the inventory service."""
        logger.info("Stopping inventory service")
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

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

    async def _periodic_refresh(self):
        """Periodically refresh inventory."""
        while True:
            try:
                await asyncio.sleep(settings.inventory_refresh_interval)
                await self.refresh_inventory()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic inventory refresh: {e}")

    async def refresh_inventory(self):
        """Refresh inventory from all configured hosts."""
        if settings.dummy_data:
            # In dummy mode, just refresh timestamp and maybe randomize states
            await self._refresh_dummy_data()
            return

        logger.info("Refreshing inventory")

        host_list = settings.get_hyperv_hosts_list()

        if not host_list:
            logger.warning("No Hyper-V hosts configured")
            # Clear any existing clusters and hosts since none are configured
            self.clusters.clear()
            self.hosts.clear()
            self.vms.clear()
            # Still set last_refresh to indicate the service is ready
            self.last_refresh = datetime.utcnow()
            return

        # Query each host first to determine which are actually connected
        connected_hosts = []
        for hostname in host_list:
            await self._refresh_host(hostname)
            host = self.hosts.get(hostname)
            if host and host.connected:
                connected_hosts.append(hostname)

        # Only create clusters if there are connected hosts
        if connected_hosts:
            # Initialize clusters from config (simplified - assumes single cluster)
            if not self.clusters:
                cluster_name = "Default"
                self.clusters[cluster_name] = Cluster(
                    name=cluster_name,
                    hosts=connected_hosts,
                    connected_hosts=len(connected_hosts),
                    total_hosts=len(host_list)
                )
            else:
                # Update existing cluster with current connected hosts
                for cluster in self.clusters.values():
                    cluster.hosts = connected_hosts
                    cluster.connected_hosts = len(connected_hosts)
                    cluster.total_hosts = len(host_list)
        else:
            # No connected hosts, clear clusters but keep disconnected host info
            logger.info("No hosts are currently connected")
            self.clusters.clear()
            # Remove VMs since no hosts are connected
            self.vms.clear()

        self.last_refresh = datetime.utcnow()
        logger.info(
            f"Inventory refresh completed. Connected hosts: {len(connected_hosts)}, Total VMs: {len(self.vms)}")

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

            # Determine cluster assignment (simplified)
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

            # Update VM inventory
            for vm in vms:
                key = f"{hostname}:{vm.name}"
                self.vms[key] = vm

            # Remove VMs that no longer exist on this host
            keys_to_remove = [
                key for key in self.vms.keys()
                if key.startswith(f"{hostname}:") and key not in
                [f"{hostname}:{vm.name}" for vm in vms]
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
                cluster=None,  # Disconnected hosts have no cluster
                connected=False,
                last_seen=self.hosts.get(hostname,
                                         Host(hostname=hostname)).last_seen,
                error=str(e)
            )

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
        command = """
        Get-VM | Select-Object Name, State, ProcessorCount, @{N='MemoryGB';E={$_.MemoryAssigned/1GB}}, CreationTime | ConvertTo-Json
        """

        stdout, stderr, exit_code = winrm_service.execute_ps_command(
            hostname, command
        )

        if exit_code != 0:
            raise Exception(f"Failed to query VMs: {stderr}")

        vms = []
        try:
            if stdout.strip():
                data = json.loads(stdout)

                # Handle single VM vs array
                if isinstance(data, dict):
                    data = [data]

                for vm_data in data:
                    # Map PowerShell state to our enum
                    state_str = vm_data.get('State', 'Unknown')
                    try:
                        state = VMState(state_str)
                    except ValueError:
                        state = VMState.UNKNOWN

                    vm = VM(
                        name=vm_data.get('Name', ''),
                        host=hostname,
                        state=state,
                        cpu_cores=vm_data.get('ProcessorCount', 0),
                        memory_gb=round(vm_data.get('MemoryGB', 0.0), 2),
                        created_at=vm_data.get('CreationTime')
                    )
                    vms.append(vm)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse VM data from {hostname}: {e}")
            logger.debug(f"Raw output: {stdout}")

        return vms

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
