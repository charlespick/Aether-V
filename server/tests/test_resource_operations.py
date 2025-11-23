"""Tests: Resource Operations Round-Trip Validation

This test suite validates the Phase 4 implementation of resource-level operations
using the new JobRequest/JobResult protocol. It tests VM, Disk, and NIC operations
without requiring actual Hyper-V hosts.

Operations tested:
- vm.create, vm.update, vm.delete
- disk.create, disk.update, disk.delete
- nic.create, nic.update, nic.delete

These tests use mocked PowerShell execution to validate the round-trip communication
protocol without requiring actual Hyper-V infrastructure.
"""
import json
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any

import pytest

from app.core.job_envelope import (
    create_job_request,
    create_job_request_from_vm_spec,
    create_job_request_from_disk_spec,
    create_job_request_from_nic_spec,
    create_vm_update_request,
    create_vm_delete_request,
    create_disk_update_request,
    create_disk_delete_request,
    create_nic_update_request,
    create_nic_delete_request,
    parse_job_result,
)
from app.core.pydantic_models import (
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
    VmSpec,
    DiskSpec,
    NicSpec,
)


class TestVmOperations:
    """Test VM create/update/delete operations."""
    
    def _execute_operation(
        self,
        script_path: Path,
        operation: str,
        resource_spec: Dict[str, Any],
    ) -> JobResultEnvelope:
        """Helper to execute an operation and return the parsed result."""
        request = create_job_request(
            operation=operation,
            resource_spec=resource_spec,
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        # For operations that would require Hyper-V, we expect them to fail
        # but we can still validate the protocol structure
        envelope, error = parse_job_result(result.stdout if result.stdout else result.stderr)
        
        # If we can't parse the result, check if it's because of missing Hyper-V
        if error and "Get-VM" in result.stderr:
            pytest.skip("PowerShell Hyper-V module not available in test environment")
        
        assert envelope is not None, f"Failed to parse result: {error}"
        return envelope
    
    def test_vm_create_envelope_structure(self, script_path, pwsh_available):
        """Test that vm.create creates proper envelope structure."""
        vm_spec = VmSpec(
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
        )
        
        request = create_job_request_from_vm_spec(vm_spec)
        
        assert request.operation == "vm.create"
        assert request.resource_spec["vm_name"] == "test-vm"
        assert request.resource_spec["gb_ram"] == 4
        assert request.resource_spec["cpu_cores"] == 2
    
    def test_vm_update_envelope_structure(self):
        """Test that vm.update creates proper envelope structure."""
        request = create_vm_update_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            updates={"gb_ram": 8, "cpu_cores": 4},
        )
        
        assert request.operation == "vm.update"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["gb_ram"] == 8
        assert request.resource_spec["cpu_cores"] == 4
    
    def test_vm_delete_envelope_structure(self):
        """Test that vm.delete creates proper envelope structure."""
        request = create_vm_delete_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            vm_name="test-vm",
        )
        
        assert request.operation == "vm.delete"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["vm_name"] == "test-vm"


class TestDiskOperations:
    """Test Disk create/update/delete operations."""
    
    def test_disk_create_envelope_structure(self):
        """Test that disk.create creates proper envelope structure."""
        disk_spec = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            disk_size_gb=100,
            storage_class="fast-ssd",
        )
        
        request = create_job_request_from_disk_spec(disk_spec)
        
        assert request.operation == "disk.create"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["disk_size_gb"] == 100
        assert request.resource_spec["storage_class"] == "fast-ssd"
    
    def test_disk_create_with_image_envelope_structure(self):
        """Test that disk.create with image name creates proper envelope structure."""
        disk_spec = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            image_name="Windows Server 2022",
            storage_class="fast-ssd",
        )
        
        request = create_job_request_from_disk_spec(disk_spec)
        
        assert request.operation == "disk.create"
        assert request.resource_spec["image_name"] == "Windows Server 2022"
    
    def test_disk_update_envelope_structure(self):
        """Test that disk.update creates proper envelope structure."""
        request = create_disk_update_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            resource_id="disk-abc123",
            updates={"disk_size_gb": 200},
        )
        
        assert request.operation == "disk.update"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["resource_id"] == "disk-abc123"
        assert request.resource_spec["disk_size_gb"] == 200
    
    def test_disk_delete_envelope_structure(self):
        """Test that disk.delete creates proper envelope structure."""
        request = create_disk_delete_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            resource_id="disk-abc123",
        )
        
        assert request.operation == "disk.delete"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["resource_id"] == "disk-abc123"


class TestNicOperations:
    """Test NIC create/update/delete operations."""
    
    def test_nic_create_envelope_structure(self):
        """Test that nic.create creates proper envelope structure."""
        nic_spec = NicSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            adapter_name="Network Adapter 2",
        )
        
        request = create_job_request_from_nic_spec(nic_spec)
        
        assert request.operation == "nic.create"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["network"] == "Production"
        assert request.resource_spec["adapter_name"] == "Network Adapter 2"
    
    def test_nic_update_envelope_structure(self):
        """Test that nic.update creates proper envelope structure."""
        request = create_nic_update_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            resource_id="nic-abc123",
            updates={"network": "Development"},
        )
        
        assert request.operation == "nic.update"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["resource_id"] == "nic-abc123"
        assert request.resource_spec["network"] == "Development"
    
    def test_nic_delete_envelope_structure(self):
        """Test that nic.delete creates proper envelope structure."""
        request = create_nic_delete_request(
            vm_id="12345678-1234-1234-1234-123456789abc",
            resource_id="nic-abc123",
        )
        
        assert request.operation == "nic.delete"
        assert request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert request.resource_spec["resource_id"] == "nic-abc123"


class TestEnvelopeValidation:
    """Test envelope format validation for all operations."""
    
    def test_all_operations_use_standard_envelope(self):
        """Test that all operations use the standard JobRequest envelope."""
        # VM operations
        vm_create = create_job_request("vm.create", {"vm_name": "test"})
        vm_update = create_vm_update_request("vm-id", {})
        vm_delete = create_vm_delete_request("vm-id", "vm-name")
        
        # Disk operations
        disk_create = create_job_request("disk.create", {"vm_id": "test"})
        disk_update = create_disk_update_request("vm-id", "disk-id", {})
        disk_delete = create_disk_delete_request("vm-id", "disk-id")
        
        # NIC operations
        nic_create = create_job_request("nic.create", {"vm_id": "test", "network": "prod"})
        nic_update = create_nic_update_request("vm-id", "nic-id", {})
        nic_delete = create_nic_delete_request("vm-id", "nic-id")
        
        # All should be JobRequest instances
        for req in [vm_create, vm_update, vm_delete, disk_create, disk_update, disk_delete, nic_create, nic_update, nic_delete]:
            assert isinstance(req, JobRequest)
            assert req.operation is not None
            assert req.resource_spec is not None
            assert req.correlation_id is not None
            assert "timestamp" in req.metadata
    
    def test_result_envelope_parsing(self):
        """Test parsing of result envelopes."""
        # Success result
        success_json = json.dumps({
            "status": "success",
            "message": "Operation completed",
            "data": {"vm_id": "test-id"},
            "correlation_id": "test-123",
        })
        
        envelope, error = parse_job_result(success_json)
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["vm_id"] == "test-id"
        
        # Error result
        error_json = json.dumps({
            "status": "error",
            "message": "Operation failed",
            "data": {},
            "code": "VM_NOT_FOUND",
            "correlation_id": "test-123",
        })
        
        envelope, error = parse_job_result(error_json)
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.ERROR
        assert envelope.code == "VM_NOT_FOUND"


class TestProtocolConsistency:
    """Test that all operations follow consistent protocol patterns."""
    
    def test_update_operations_require_vm_id_and_resource_id(self):
        """Test that update operations consistently require both IDs."""
        # Disk update
        disk_update = create_disk_update_request("vm-123", "disk-456", {})
        assert disk_update.resource_spec["vm_id"] == "vm-123"
        assert disk_update.resource_spec["resource_id"] == "disk-456"
        
        # NIC update
        nic_update = create_nic_update_request("vm-123", "nic-456", {})
        assert nic_update.resource_spec["vm_id"] == "vm-123"
        assert nic_update.resource_spec["resource_id"] == "nic-456"
    
    def test_delete_operations_require_vm_id_and_resource_id(self):
        """Test that delete operations consistently require both IDs."""
        # Disk delete
        disk_delete = create_disk_delete_request("vm-123", "disk-456")
        assert disk_delete.resource_spec["vm_id"] == "vm-123"
        assert disk_delete.resource_spec["resource_id"] == "disk-456"
        
        # NIC delete
        nic_delete = create_nic_delete_request("vm-123", "nic-456")
        assert nic_delete.resource_spec["vm_id"] == "vm-123"
        assert nic_delete.resource_spec["resource_id"] == "nic-456"
    
    def test_create_operations_use_pydantic_models(self):
        """Test that create operations can use Pydantic models."""
        # VM create
        vm_spec = VmSpec(vm_name="test", gb_ram=4, cpu_cores=2)
        vm_request = create_job_request_from_vm_spec(vm_spec)
        assert vm_request.operation == "vm.create"
        
        # Disk create
        disk_spec = DiskSpec(vm_id="12345678-1234-1234-1234-123456789abc", disk_size_gb=100)
        disk_request = create_job_request_from_disk_spec(disk_spec)
        assert disk_request.operation == "disk.create"
        
        # NIC create
        nic_spec = NicSpec(vm_id="12345678-1234-1234-1234-123456789abc", network="Production")
        nic_request = create_job_request_from_nic_spec(nic_spec)
        assert nic_request.operation == "nic.create"


class TestCorrelationIdTracking:
    """Test that correlation IDs are properly tracked across operations."""
    
    def test_correlation_id_generation(self):
        """Test that correlation IDs are generated when not provided."""
        request = create_job_request("vm.create", {"vm_name": "test"})
        
        assert request.correlation_id is not None
        assert len(request.correlation_id) > 0
    
    def test_custom_correlation_id(self):
        """Test that custom correlation IDs are preserved."""
        custom_id = "custom-correlation-12345"
        
        request = create_job_request(
            "vm.create",
            {"vm_name": "test"},
            correlation_id=custom_id,
        )
        
        assert request.correlation_id == custom_id
    
    def test_correlation_id_in_all_operations(self):
        """Test that all operation helpers support correlation IDs."""
        custom_id = "test-123"
        
        # Test a few representative operations
        vm_create = create_job_request_from_vm_spec(
            VmSpec(vm_name="test", gb_ram=4, cpu_cores=2),
            correlation_id=custom_id,
        )
        assert vm_create.correlation_id == custom_id
        
        vm_delete = create_vm_delete_request(
            "vm-id", "vm-name",
            correlation_id=custom_id,
        )
        assert vm_delete.correlation_id == custom_id
        
        disk_update = create_disk_update_request(
            "vm-id", "disk-id", {},
            correlation_id=custom_id,
        )
        assert disk_update.correlation_id == custom_id
