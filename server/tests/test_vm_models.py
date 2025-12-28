"""VM Resource Request Models Tests

This test suite validates the VM resource request models (VMCreateRequest, etc.).
These models are used for the resource API endpoints.
"""
import pytest
from pydantic import ValidationError

from app.core.models import VMCreateRequest, OSFamily


class TestVMCreateRequest:
    """Test VMCreateRequest model with cluster targeting support."""
    
    def test_valid_with_target_host(self):
        """Test valid VM creation request with direct host targeting."""
        request = VMCreateRequest(
            target_host="hyperv-01",
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
            storage_class="fast-ssd",
            os_family=OSFamily.WINDOWS,
        )
        
        assert request.target_host == "hyperv-01"
        assert request.target_cluster is None
        assert request.vm_name == "test-vm"
        assert request.gb_ram == 4
        assert request.cpu_cores == 2
    
    def test_valid_with_target_cluster(self):
        """Test valid VM creation request with cluster targeting."""
        request = VMCreateRequest(
            target_cluster="prod-cluster",
            vm_name="test-vm",
            gb_ram=8,
            cpu_cores=4,
            storage_class="standard",
        )
        
        assert request.target_cluster == "prod-cluster"
        assert request.target_host is None
        assert request.vm_name == "test-vm"
        assert request.gb_ram == 8
    
    def test_minimal_with_host(self):
        """Test minimal VM creation with only required fields and host."""
        request = VMCreateRequest(
            target_host="hyperv-02",
            vm_name="minimal-vm",
            gb_ram=2,
            cpu_cores=1,
        )
        
        assert request.target_host == "hyperv-02"
        assert request.storage_class is None
        assert request.os_family is None
    
    def test_minimal_with_cluster(self):
        """Test minimal VM creation with only required fields and cluster."""
        request = VMCreateRequest(
            target_cluster="dev-cluster",
            vm_name="minimal-vm",
            gb_ram=2,
            cpu_cores=1,
        )
        
        assert request.target_cluster == "dev-cluster"
        assert request.storage_class is None
    
    def test_both_targets_fails(self):
        """Test validation fails when both target_host and target_cluster are specified."""
        with pytest.raises(ValidationError) as exc_info:
            VMCreateRequest(
                target_host="hyperv-01",
                target_cluster="prod-cluster",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        error_msg = str(errors[0]["ctx"]["error"])
        assert "Cannot specify both target_host and target_cluster" in error_msg
    
    def test_neither_target_fails(self):
        """Test validation fails when neither target_host nor target_cluster is specified."""
        with pytest.raises(ValidationError) as exc_info:
            VMCreateRequest(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        error_msg = str(errors[0]["ctx"]["error"])
        assert "Must specify either target_host or target_cluster" in error_msg
    
    def test_validation_ram_range(self):
        """Test RAM validation enforces reasonable bounds."""
        with pytest.raises(ValidationError):
            VMCreateRequest(
                target_host="hyperv-01",
                vm_name="test-vm",
                gb_ram=1000,  # Exceeds max of 512
                cpu_cores=2,
            )
    
    def test_validation_cpu_range(self):
        """Test CPU validation enforces reasonable bounds."""
        with pytest.raises(ValidationError):
            VMCreateRequest(
                target_host="hyperv-01",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=100,  # Exceeds max of 64
            )
    
    def test_validation_vm_name_length(self):
        """Test VM name length validation."""
        with pytest.raises(ValidationError):
            VMCreateRequest(
                target_host="hyperv-01",
                vm_name="a" * 100,  # Exceeds max of 64
                gb_ram=4,
                cpu_cores=2,
            )
    
    def test_os_family_linux(self):
        """Test VM creation with Linux OS family."""
        request = VMCreateRequest(
            target_host="hyperv-01",
            vm_name="linux-vm",
            gb_ram=4,
            cpu_cores=2,
            os_family=OSFamily.LINUX,
        )
        
        assert request.os_family == OSFamily.LINUX
