"""Pydantic Models Tests

This test suite validates that the Pydantic models work correctly.

Tests cover:
1. Pydantic model validation (positive and negative cases)
2. Validation error formatting and bubbling
3. Model serialization and deserialization
"""
import pytest
from pydantic import ValidationError

from app.core.pydantic_models import (
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
    ManagedDeploymentRequest,
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
)


class TestVmSpecModel:
    """Test VmSpec Pydantic model."""
    
    def test_valid_vm_spec(self):
        """Test valid VM specification."""
        vm = VmSpec(
            vm_name="web-01",
            gb_ram=4,
            cpu_cores=2,
            storage_class="fast-ssd",
            vm_clustered=False,
        )
        
        assert vm.vm_name == "web-01"
        assert vm.gb_ram == 4
        assert vm.cpu_cores == 2
        assert vm.storage_class == "fast-ssd"
        assert vm.vm_clustered is False
    
    def test_vm_spec_with_defaults(self):
        """Test VM spec with default values."""
        vm = VmSpec(
            vm_name="test-vm",
            gb_ram=8,
            cpu_cores=4,
        )
        
        assert vm.vm_clustered is False  # Default value
        assert vm.storage_class is None  # Optional field
    
    def test_vm_spec_name_too_long(self):
        """Test VM name length validation."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="a" * 65,  # Max is 64
                gb_ram=4,
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert any("vm_name" in str(e["loc"]) for e in errors)
    
    def test_vm_spec_invalid_ram(self):
        """Test RAM validation."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test",
                gb_ram=0,  # Min is 1
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert any("gb_ram" in str(e["loc"]) for e in errors)
    
    def test_vm_spec_invalid_cpu(self):
        """Test CPU validation."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test",
                gb_ram=4,
                cpu_cores=100,  # Max is 64
            )
        
        errors = exc_info.value.errors()
        assert any("cpu_cores" in str(e["loc"]) for e in errors)


class TestDiskSpecModel:
    """Test DiskSpec Pydantic model."""
    
    def test_valid_disk_spec_with_image(self):
        """Test disk spec for cloning from image."""
        disk = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            image_name="Windows Server 2022",
            storage_class="fast-ssd",
        )
        
        assert disk.vm_id == "12345678-1234-1234-1234-123456789abc"
        assert disk.image_name == "Windows Server 2022"
        assert disk.disk_type == "Dynamic"  # Default
    
    def test_valid_disk_spec_blank(self):
        """Test disk spec for blank disk."""
        disk = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            disk_size_gb=200,
        )
        
        assert disk.disk_size_gb == 200
        assert disk.image_name is None
    
    def test_disk_spec_invalid_size(self):
        """Test disk size validation."""
        with pytest.raises(ValidationError) as exc_info:
            DiskSpec(
                disk_size_gb=100000,  # Max is 65536
            )
        
        errors = exc_info.value.errors()
        assert any("disk_size_gb" in str(e["loc"]) for e in errors)


class TestNicSpecModel:
    """Test NicSpec Pydantic model."""
    
    def test_valid_nic_spec(self):
        """Test valid NIC specification."""
        nic = NicSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            adapter_name="Network Adapter 2",
        )
        
        assert nic.network == "Production"
        assert nic.adapter_name == "Network Adapter 2"
    
    def test_nic_spec_minimal(self):
        """Test NIC spec with minimal required fields."""
        nic = NicSpec(network="Production")
        
        assert nic.network == "Production"
        assert nic.vm_id is None
        assert nic.adapter_name is None


class TestGuestConfigSpecModel:
    """Test GuestConfigSpec Pydantic model."""
    
    def test_valid_guest_config_minimal(self):
        """Test guest config with minimal fields."""
        config = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        assert config.guest_la_uid == "Administrator"
        assert config.guest_la_pw == "SecurePass123!"
    
    def test_guest_config_with_domain_join(self):
        """Test guest config with complete domain join."""
        config = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="corp.example.com",
            guest_domain_joinuid="EXAMPLE\\svc_join",
            guest_domain_joinpw="DomainPass456!",
            guest_domain_joinou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        assert config.guest_domain_jointarget == "corp.example.com"
    
    def test_guest_config_partial_domain_join_fails(self):
        """Test that partial domain join config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_domain_jointarget="corp.example.com",
                # Missing other domain join fields
            )
        
        error_msg = str(exc_info.value)
        assert "domain join" in error_msg.lower()
    
    def test_guest_config_with_static_ip(self):
        """Test guest config with static IP configuration."""
        config = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="192.168.1.100",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        assert config.guest_v4_ipaddr == "192.168.1.100"
        assert config.guest_v4_cidrprefix == 24
    
    def test_guest_config_partial_static_ip_fails(self):
        """Test that partial static IP config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_v4_ipaddr="192.168.1.100",
                guest_v4_cidrprefix=24,
                # Missing gateway and DNS
            )
        
        error_msg = str(exc_info.value)
        assert "static ip" in error_msg.lower()
    
    def test_guest_config_partial_ansible_fails(self):
        """Test that partial Ansible config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                cnf_ansible_ssh_user="ansible",
                # Missing SSH key
            )
        
        error_msg = str(exc_info.value)
        assert "ansible" in error_msg.lower()


class TestManagedDeploymentRequestModel:
    """Test ManagedDeploymentRequest Pydantic model."""
    
    def test_valid_managed_deployment_full(self):
        """Test complete managed deployment request."""
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="web-01",
                gb_ram=4,
                cpu_cores=2,
            ),
            disk_spec=DiskSpec(
                image_name="Windows Server 2022",
            ),
            nic_spec=NicSpec(
                network="Production",
            ),
            guest_config=GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
            ),
            target_host="hyperv-01.example.com",
        )
        
        assert request.vm_spec.vm_name == "web-01"
        assert request.disk_spec.image_name == "Windows Server 2022"
        assert request.nic_spec.network == "Production"
        assert request.target_host == "hyperv-01.example.com"
    
    def test_managed_deployment_minimal(self):
        """Test minimal managed deployment (VM only)."""
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="test-vm",
                gb_ram=2,
                cpu_cores=1,
            ),
            target_host="hyperv-01",
        )
        
        assert request.vm_spec.vm_name == "test-vm"
        assert request.disk_spec is None
        assert request.nic_spec is None
        assert request.guest_config is None


class TestJobEnvelopeModels:
    """Test JobRequest and JobResultEnvelope models."""
    
    def test_valid_job_request(self):
        """Test job request envelope."""
        request = JobRequest(
            operation="vm.create",
            resource_spec={
                "vm_name": "web-01",
                "gb_ram": 4,
                "cpu_cores": 2,
            },
            correlation_id="test-correlation-id",
            metadata={"timestamp": "2025-11-22T04:43:48.376Z"},
        )
        
        assert request.operation == "vm.create"
        assert request.resource_spec["vm_name"] == "web-01"
        assert request.correlation_id == "test-correlation-id"
    
    def test_valid_job_result_success(self):
        """Test successful job result envelope."""
        result = JobResultEnvelope(
            status=JobResultStatus.SUCCESS,
            message="VM created successfully",
            data={"vm_id": "12345678-1234-1234-1234-123456789abc"},
            correlation_id="test-correlation-id",
        )
        
        assert result.status == JobResultStatus.SUCCESS
        assert result.message == "VM created successfully"
        assert "vm_id" in result.data
    
    def test_valid_job_result_error(self):
        """Test error job result envelope."""
        result = JobResultEnvelope(
            status=JobResultStatus.ERROR,
            message="VM creation failed",
            code="VM_NAME_CONFLICT",
            logs=["Line 1", "Line 2"],
        )
        
        assert result.status == JobResultStatus.ERROR
        assert result.code == "VM_NAME_CONFLICT"
        assert len(result.logs) == 2

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
