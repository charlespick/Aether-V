"""Phase 1 Tests: Pydantic Models and Converters

This test suite validates that the new Pydantic models work correctly
alongside the existing schema system without breaking anything.

Tests cover:
1. Pydantic model validation (positive and negative cases)
2. Schema-to-Pydantic conversion functions
3. Validation error formatting and bubbling
4. Side-by-side comparison with schema validation
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
from app.core.pydantic_converters import (
    convert_vm_schema_to_spec,
    convert_disk_schema_to_spec,
    convert_nic_schema_to_spec,
    convert_guest_config_schema_to_spec,
    convert_managed_deployment_schema_to_spec,
    validate_job_result,
    log_validation_comparison,
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


class TestSchemaToVmSpecConverter:
    """Test conversion from VM schema to VmSpec."""
    
    def test_convert_valid_vm_schema(self):
        """Test converting valid VM schema values."""
        schema_values = {
            "vm_name": "web-01",
            "gb_ram": 4,
            "cpu_cores": 2,
            "storage_class": "fast-ssd",
            "vm_clustered": True,
        }
        
        result_dict, error = convert_vm_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["vm_name"] == "web-01"
        assert result_dict["gb_ram"] == 4
        assert result_dict["cpu_cores"] == 2
    
    def test_convert_vm_schema_filters_guest_fields(self):
        """Test that guest config fields are filtered out."""
        schema_values = {
            "vm_name": "web-01",
            "gb_ram": 4,
            "cpu_cores": 2,
            # These should be filtered out
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
        }
        
        result_dict, error = convert_vm_schema_to_spec(schema_values)
        
        assert error is None
        assert "vm_name" in result_dict
        assert "guest_la_uid" not in result_dict
        assert "guest_la_pw" not in result_dict
    
    def test_convert_invalid_vm_schema(self):
        """Test converting invalid VM schema values."""
        schema_values = {
            "vm_name": "a" * 100,  # Too long
            "gb_ram": 4,
            "cpu_cores": 2,
        }
        
        result_dict, error = convert_vm_schema_to_spec(schema_values)
        
        assert error is not None
        assert "vm_name" in error


class TestSchemaToDiskSpecConverter:
    """Test conversion from disk schema to DiskSpec."""
    
    def test_convert_valid_disk_schema(self):
        """Test converting valid disk schema values."""
        schema_values = {
            "vm_id": "12345678-1234-1234-1234-123456789abc",
            "image_name": "Windows Server 2022",
            "storage_class": "fast-ssd",
        }
        
        result_dict, error = convert_disk_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert result_dict["image_name"] == "Windows Server 2022"


class TestSchemaToNicSpecConverter:
    """Test conversion from NIC schema to NicSpec."""
    
    def test_convert_valid_nic_schema(self):
        """Test converting valid NIC schema values."""
        schema_values = {
            "vm_id": "12345678-1234-1234-1234-123456789abc",
            "network": "Production",
            "adapter_name": "Network Adapter 2",
        }
        
        result_dict, error = convert_nic_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["network"] == "Production"
    
    def test_convert_nic_schema_filters_guest_fields(self):
        """Test that guest IP config fields are filtered out."""
        schema_values = {
            "network": "Production",
            # These should be filtered out
            "guest_v4_ipaddr": "192.168.1.100",
            "guest_v4_cidrprefix": 24,
        }
        
        result_dict, error = convert_nic_schema_to_spec(schema_values)
        
        assert error is None
        assert "network" in result_dict
        assert "guest_v4_ipaddr" not in result_dict


class TestSchemaToGuestConfigConverter:
    """Test conversion from schema to GuestConfigSpec."""
    
    def test_convert_valid_guest_config(self):
        """Test converting valid guest config fields."""
        schema_values = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
            "guest_domain_jointarget": "corp.example.com",
            "guest_domain_joinuid": "EXAMPLE\\svc_join",
            "guest_domain_joinpw": "DomainPass456!",
            "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
        }
        
        result_dict, error = convert_guest_config_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["guest_la_uid"] == "Administrator"
        assert result_dict["guest_domain_jointarget"] == "corp.example.com"
    
    def test_convert_guest_config_with_static_ip(self):
        """Test converting guest config with static IP."""
        schema_values = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
            "guest_v4_ipaddr": "192.168.1.100",
            "guest_v4_cidrprefix": 24,
            "guest_v4_defaultgw": "192.168.1.1",
            "guest_v4_dns1": "192.168.1.10",
        }
        
        result_dict, error = convert_guest_config_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["guest_v4_ipaddr"] == "192.168.1.100"
    
    def test_convert_guest_config_missing_credentials(self):
        """Test that missing credentials causes error."""
        schema_values = {
            "guest_domain_jointarget": "corp.example.com",
        }
        
        result_dict, error = convert_guest_config_schema_to_spec(schema_values)
        
        assert error is not None
        assert "guest_la_uid" in error or "guest_la_pw" in error
    
    def test_convert_empty_guest_config(self):
        """Test converting when no guest config fields present."""
        schema_values = {
            "vm_name": "test",
        }
        
        result_dict, error = convert_guest_config_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict == {}


class TestManagedDeploymentConverter:
    """Test conversion to ManagedDeploymentRequest."""
    
    def test_convert_full_managed_deployment(self):
        """Test converting complete managed deployment."""
        schema_values = {
            "vm_name": "web-01",
            "gb_ram": 4,
            "cpu_cores": 2,
            "image_name": "Windows Server 2022",
            "network": "Production",
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
        }
        
        request, error = convert_managed_deployment_schema_to_spec(
            schema_values,
            "hyperv-01",
        )
        
        assert error is None
        assert request is not None
        assert request.vm_spec.vm_name == "web-01"
        assert request.disk_spec.image_name == "Windows Server 2022"
        assert request.nic_spec.network == "Production"
        assert request.guest_config.guest_la_uid == "Administrator"
        assert request.target_host == "hyperv-01"
    
    def test_convert_minimal_managed_deployment(self):
        """Test converting minimal managed deployment (VM only)."""
        schema_values = {
            "vm_name": "test-vm",
            "gb_ram": 2,
            "cpu_cores": 1,
        }
        
        request, error = convert_managed_deployment_schema_to_spec(
            schema_values,
            "hyperv-01",
        )
        
        assert error is None
        assert request is not None
        assert request.vm_spec.vm_name == "test-vm"
        assert request.disk_spec is None
        assert request.nic_spec is None
        assert request.guest_config is None
    
    def test_convert_invalid_managed_deployment(self):
        """Test that invalid VM spec causes deployment conversion to fail."""
        schema_values = {
            "vm_name": "",  # Invalid: too short
            "gb_ram": 4,
            "cpu_cores": 2,
        }
        
        request, error = convert_managed_deployment_schema_to_spec(
            schema_values,
            "hyperv-01",
        )
        
        assert error is not None
        assert request is None


class TestJobResultValidator:
    """Test job result validation."""
    
    def test_validate_success_result(self):
        """Test validating successful job result."""
        result_data = {
            "status": "success",
            "message": "VM created successfully",
            "data": {"vm_id": "12345678-1234-1234-1234-123456789abc"},
        }
        
        result, error = validate_job_result(result_data)
        
        assert error is None
        assert result is not None
        assert result.status == JobResultStatus.SUCCESS
    
    def test_validate_error_result(self):
        """Test validating error job result."""
        result_data = {
            "status": "error",
            "message": "VM creation failed",
            "code": "VM_NAME_CONFLICT",
            "data": {},
        }
        
        result, error = validate_job_result(result_data)
        
        assert error is None
        assert result is not None
        assert result.status == JobResultStatus.ERROR
        assert result.code == "VM_NAME_CONFLICT"
    
    def test_validate_invalid_result(self):
        """Test that invalid result structure is caught."""
        result_data = {
            "status": "invalid_status",  # Invalid status
            "message": "Test",
        }
        
        result, error = validate_job_result(result_data)
        
        assert error is not None
        assert result is None


class TestValidationComparison:
    """Test validation comparison logging."""
    
    def test_log_validation_comparison_both_pass(self):
        """Test logging when both validations pass."""
        # Should not raise any exceptions
        log_validation_comparison(
            schema_passed=True,
            pydantic_error=None,
            operation="test_operation",
        )
    
    def test_log_validation_comparison_both_fail(self):
        """Test logging when both validations fail."""
        log_validation_comparison(
            schema_passed=False,
            pydantic_error="Test error",
            operation="test_operation",
        )
    
    def test_log_validation_comparison_disagreement(self):
        """Test logging when validations disagree."""
        log_validation_comparison(
            schema_passed=True,
            pydantic_error="Pydantic failed",
            operation="test_operation",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
