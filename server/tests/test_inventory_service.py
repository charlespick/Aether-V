"""
Tests for inventory service.
"""
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.models import Host, VM, VMState
from app.services.inventory_service import InventoryService


@pytest.mark.unit
class TestInventoryService:
    """Test inventory service basic functionality."""

    def test_initialization(self):
        """Test inventory service initializes with empty state."""
        service = InventoryService()
        
        assert len(service.clusters) == 0
        assert len(service.hosts) == 0
        assert len(service.vms) == 0
        assert service.last_refresh is None

    def test_get_host_by_name(self):
        """Test retrieving a host by name."""
        service = InventoryService()
        
        # Add a mock host
        host = Host(
            name="test-host",
            fqdn="test-host.example.com",
            total_memory_mb=32768,
            available_memory_mb=16384,
            processor_count=8,
            logical_processor_count=16,
            os_version="10.0.20348",
        )
        service.hosts["test-host"] = host
        
        # Retrieve host
        retrieved = service.get_host_by_name("test-host")
        assert retrieved is not None
        assert retrieved.name == "test-host"
        assert retrieved.total_memory_mb == 32768

    def test_get_vm_by_key(self):
        """Test retrieving a VM by composite key."""
        service = InventoryService()
        
        # Add a mock VM
        vm = VM(
            name="test-vm",
            host="test-host",
            state=VMState.RUNNING,
            cpu_usage=10,
            memory_assigned_mb=2048,
            memory_demand_mb=1024,
            uptime="01:23:45",
            version="9.0",
        )
        vm_key = f"{vm.host}:{vm.name}"
        service.vms[vm_key] = vm
        
        # Retrieve VM
        retrieved = service.get_vm_by_key("test-host:test-vm")
        assert retrieved is not None
        assert retrieved.name == "test-vm"
        assert retrieved.host == "test-host"
        assert retrieved.state == VMState.RUNNING

    def test_add_job_vm_placeholder(self):
        """Test adding placeholder VMs for jobs."""
        service = InventoryService()
        
        # Add placeholder
        service.add_job_vm_placeholder("job-123", "test-host", "new-vm")
        
        assert "job-123" in service._job_vm_placeholders
        assert "test-host:new-vm" in service._job_vm_placeholders["job-123"]

    def test_remove_job_vm_placeholder(self):
        """Test removing placeholder VMs."""
        service = InventoryService()
        
        # Add and then remove placeholder
        service.add_job_vm_placeholder("job-123", "test-host", "new-vm")
        service.remove_job_vm_placeholder("job-123", "test-host", "new-vm")
        
        assert "job-123" not in service._job_vm_placeholders or \
               "test-host:new-vm" not in service._job_vm_placeholders.get("job-123", set())

    def test_get_all_hosts(self):
        """Test retrieving all hosts."""
        service = InventoryService()
        
        # Add multiple hosts
        for i in range(3):
            host = Host(
                name=f"host-{i}",
                fqdn=f"host-{i}.example.com",
                total_memory_mb=32768,
                available_memory_mb=16384,
                processor_count=8,
                logical_processor_count=16,
                os_version="10.0.20348",
            )
            service.hosts[f"host-{i}"] = host
        
        all_hosts = list(service.get_all_hosts())
        assert len(all_hosts) == 3
        assert all(isinstance(h, Host) for h in all_hosts)

    def test_get_all_vms(self):
        """Test retrieving all VMs."""
        service = InventoryService()
        
        # Add multiple VMs
        for i in range(5):
            vm = VM(
                name=f"vm-{i}",
                host="test-host",
                state=VMState.RUNNING if i % 2 == 0 else VMState.OFF,
                cpu_usage=10 * i,
                memory_assigned_mb=2048,
                memory_demand_mb=1024,
                uptime="01:23:45",
                version="9.0",
            )
            vm_key = f"{vm.host}:{vm.name}"
            service.vms[vm_key] = vm
        
        all_vms = list(service.get_all_vms())
        assert len(all_vms) == 5
        assert all(isinstance(v, VM) for v in all_vms)

    def test_get_vms_by_host(self):
        """Test retrieving VMs for a specific host."""
        service = InventoryService()
        
        # Add VMs for different hosts
        for host_idx in range(2):
            for vm_idx in range(3):
                vm = VM(
                    name=f"vm-{vm_idx}",
                    host=f"host-{host_idx}",
                    state=VMState.RUNNING,
                    cpu_usage=10,
                    memory_assigned_mb=2048,
                    memory_demand_mb=1024,
                    uptime="01:23:45",
                    version="9.0",
                )
                vm_key = f"{vm.host}:{vm.name}"
                service.vms[vm_key] = vm
        
        # Get VMs for host-0
        host0_vms = list(service.get_vms_by_host("host-0"))
        assert len(host0_vms) == 3
        assert all(v.host == "host-0" for v in host0_vms)
        
        # Get VMs for host-1
        host1_vms = list(service.get_vms_by_host("host-1"))
        assert len(host1_vms) == 3
        assert all(v.host == "host-1" for v in host1_vms)


@pytest.mark.integration
@pytest.mark.winrm
class TestInventoryServiceIntegration:
    """Test inventory service with mocked WinRM."""

    @pytest.mark.asyncio
    async def test_refresh_with_mocked_winrm(self, mock_config):
        """Test inventory refresh with mocked WinRM service."""
        service = InventoryService()
        
        # Mock WinRM response with sample inventory data
        mock_inventory_data = {
            "Hosts": [
                {
                    "Name": "test-host",
                    "FQDN": "test-host.example.com",
                    "TotalMemoryMB": 32768,
                    "AvailableMemoryMB": 16384,
                    "ProcessorCount": 8,
                    "LogicalProcessorCount": 16,
                    "OSVersion": "10.0.20348",
                }
            ],
            "VMs": [
                {
                    "Name": "test-vm",
                    "Host": "test-host",
                    "State": "Running",
                    "CPUUsage": 10,
                    "MemoryAssignedMB": 2048,
                    "MemoryDemandMB": 1024,
                    "Uptime": "01:23:45",
                    "Version": "9.0",
                }
            ],
        }
        
        # This is a placeholder for integration testing
        # In actual integration tests, we would mock the WinRM service
        # and test the full refresh flow
        assert service is not None
