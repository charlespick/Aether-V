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
        )
        
        assert vm.vm_name == "web-01"
        assert vm.gb_ram == 4
        assert vm.cpu_cores == 2
        assert vm.storage_class == "fast-ssd"
        assert vm.vm_clustered is None  # Not used during creation
    
    def test_vm_spec_with_defaults(self):
        """Test VM spec with default values."""
        vm = VmSpec(
            vm_name="test-vm",
            gb_ram=8,
            cpu_cores=4,
        )
        
        assert vm.vm_clustered is None  # Optional, used only in updates
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


class TestManagedDeploymentValidation:
    """Test ManagedDeploymentRequest validation rules."""
    
    def test_minimal_managed_deployment(self):
        """Test minimal managed deployment request."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01.example.com",
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
            network="Production",
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        assert request.guest_la_uid == "Administrator"
        assert request.guest_la_pw == "SecurePass123!"
    
    def test_managed_deployment_with_domain_join(self):
        """Test managed deployment with complete domain join."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01.example.com",
            vm_name="web-01",
            gb_ram=4,
            cpu_cores=2,
            network="Production",
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_join_target="corp.example.com",
            guest_domain_join_uid="EXAMPLE\\svc_join",
            guest_domain_join_pw="DomainPass456!",
            guest_domain_join_ou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        assert request.guest_domain_join_target == "corp.example.com"
    
    def test_partial_domain_join_fails(self):
        """Test that partial domain join config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ManagedDeploymentRequest(
                target_host="hyperv-01.example.com",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
                network="Production",
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_domain_join_target="corp.example.com",
                # Missing other domain join fields
            )
        
        error_msg = str(exc_info.value)
        assert "domain join" in error_msg.lower()
    
    def test_managed_deployment_with_static_ip(self):
        """Test managed deployment with static IP configuration."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01.example.com",
            vm_name="web-01",
            gb_ram=4,
            cpu_cores=2,
            network="Production",
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ip_addr="192.168.1.100",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        assert request.guest_v4_ip_addr == "192.168.1.100"
        assert request.guest_v4_cidr_prefix == 24
    
    def test_partial_static_ip_fails(self):
        """Test that partial static IP config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ManagedDeploymentRequest(
                target_host="hyperv-01.example.com",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
                network="Production",
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_v4_ip_addr="192.168.1.100",
                guest_v4_cidr_prefix=24,
                # Missing gateway and DNS
            )
        
        error_msg = str(exc_info.value)
        assert "static ip" in error_msg.lower()
    
    def test_partial_ansible_fails(self):
        """Test that partial Ansible config is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ManagedDeploymentRequest(
                target_host="hyperv-01.example.com",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
                network="Production",
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
        """Test complete managed deployment request with all guest config."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01.example.com",
            vm_name="web-01",
            gb_ram=4,
            cpu_cores=2,
            image_name="Windows Server 2022",
            network="Production",
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_join_target="corp.example.com",
            guest_domain_join_uid="EXAMPLE\\svc_join",
            guest_domain_join_pw="DomainPass456!",
            guest_domain_join_ou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        assert request.vm_name == "web-01"
        assert request.image_name == "Windows Server 2022"
        assert request.network == "Production"
        assert request.target_host == "hyperv-01.example.com"
        assert request.guest_domain_join_target == "corp.example.com"
    
    def test_managed_deployment_minimal(self):
        """Test minimal managed deployment."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01",
            vm_name="test-vm",
            gb_ram=2,
            cpu_cores=1,
            network="Production",
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        assert request.vm_name == "test-vm"
        assert request.image_name is None
        assert request.guest_domain_join_target is None
    
    def test_cluster_targeting_valid(self):
        """Test valid cluster targeting - target_cluster specified without target_host."""
        request = ManagedDeploymentRequest(
            target_cluster="prod-cluster",
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
            disk_size_gb=50,
            disk_type="Dynamic",
            controller_type="SCSI",
            storage_class="fast-ssd",
            image_name="Windows Server 2022",
            network="Production",
            guest_la_uid="admin",
            guest_la_pw="P@ssw0rd123",
        )
        
        assert request.target_cluster == "prod-cluster"
        assert request.target_host is None
    
    def test_host_targeting_valid(self):
        """Test valid host targeting - target_host specified without target_cluster."""
        request = ManagedDeploymentRequest(
            target_host="hyperv-01",
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
            disk_size_gb=50,
            disk_type="Dynamic",
            controller_type="SCSI",
            storage_class="fast-ssd",
            image_name="Windows Server 2022",
            network="Production",
            guest_la_uid="admin",
            guest_la_pw="P@ssw0rd123",
        )
        
        assert request.target_host == "hyperv-01"
        assert request.target_cluster is None
    
    def test_both_target_host_and_cluster_fails(self):
        """Test validation fails when both target_host and target_cluster are provided."""
        with pytest.raises(ValidationError) as exc_info:
            ManagedDeploymentRequest(
                target_host="hyperv-01",
                target_cluster="prod-cluster",
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
                disk_size_gb=50,
                disk_type="Dynamic",
                controller_type="SCSI",
                storage_class="fast-ssd",
                image_name="Windows Server 2022",
                network="Production",
                guest_la_uid="admin",
                guest_la_pw="P@ssw0rd123",
            )
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        error_msg = str(errors[0]["ctx"]["error"])
        assert "Cannot specify both target_host and target_cluster" in error_msg
    
    def test_neither_target_host_nor_cluster_fails(self):
        """Test validation fails when neither target_host nor target_cluster is provided."""
        with pytest.raises(ValidationError) as exc_info:
            ManagedDeploymentRequest(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
                disk_size_gb=50,
                disk_type="Dynamic",
                controller_type="SCSI",
                storage_class="fast-ssd",
                image_name="Windows Server 2022",
                network="Production",
                guest_la_uid="admin",
                guest_la_pw="P@ssw0rd123",
            )
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        error_msg = str(errors[0]["ctx"]["error"])
        assert "Must specify either target_host or target_cluster" in error_msg


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
