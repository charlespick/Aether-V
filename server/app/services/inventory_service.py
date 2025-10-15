"""Inventory management service for tracking Hyper-V hosts and VMs."""
import logging
from datetime import datetime
from typing import List, Dict, Optional
import asyncio
import json

from ..core.models import Host, VM, VMState, OSFamily
from ..core.config import settings
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


class InventoryService:
    """Service for managing inventory of hosts and VMs."""
    
    def __init__(self):
        self.hosts: Dict[str, Host] = {}
        self.vms: Dict[str, VM] = {}  # Key is "hostname:vmname"
        self.last_refresh: Optional[datetime] = None
        self._refresh_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the inventory service and begin periodic refresh."""
        logger.info("Starting inventory service")
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
        logger.info("Refreshing inventory")
        
        host_list = settings.get_hyperv_hosts_list()
        
        if not host_list:
            logger.warning("No Hyper-V hosts configured")
            return
        
        # Query each host
        for hostname in host_list:
            await self._refresh_host(hostname)
        
        self.last_refresh = datetime.utcnow()
        logger.info(f"Inventory refresh completed. Total VMs: {len(self.vms)}")
    
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
            
            # Update host status
            self.hosts[hostname] = Host(
                hostname=hostname,
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
                if key.startswith(f"{hostname}:") and key not in [f"{hostname}:{vm.name}" for vm in vms]
            ]
            for key in keys_to_remove:
                del self.vms[key]
            
            logger.info(f"Host {hostname}: {len(vms)} VMs")
        
        except Exception as e:
            logger.error(f"Failed to refresh host {hostname}: {e}")
            self.hosts[hostname] = Host(
                hostname=hostname,
                connected=False,
                last_seen=self.hosts.get(hostname, Host(hostname=hostname)).last_seen,
                error=str(e)
            )
    
    def _test_host_connection(self, hostname: str):
        """Test WinRM connection to a host."""
        command = "echo 'connection test'"
        stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
        
        if exit_code != 0:
            raise Exception(f"Connection test failed: {stderr}")
    
    def _query_host_vms(self, hostname: str) -> List[VM]:
        """Query VMs from a host using PowerShell."""
        # PowerShell command to get VM information
        command = """
        Get-VM | Select-Object Name, State, ProcessorCount, @{N='MemoryGB';E={$_.MemoryAssigned/1GB}}, CreationTime | ConvertTo-Json
        """
        
        stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
        
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
    
    def get_all_hosts(self) -> List[Host]:
        """Get all hosts."""
        return list(self.hosts.values())
    
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
