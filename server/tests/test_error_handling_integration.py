"""Integration tests for error handling and failure scenarios.

This test suite validates that the system handles errors gracefully across
different layers and provides meaningful error messages to users.

Test coverage:
- JobResult envelope error handling
- Partial failure scenarios
- Large VM configuration validation
- Network connectivity errors
- Invalid input validation
- Resource constraint violations
"""
import pytest
from pydantic import ValidationError

from app.core.pydantic_models import (
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
    ManagedDeploymentRequest,
    JobResultEnvelope,
    JobResultStatus,
)
from app.core.job_envelope import parse_job_result, create_job_request


class TestJobResultErrorHandling:
    """Test error handling in JobResult envelope parsing."""

    def test_parse_valid_success_result(self):
        """Parse a valid success result envelope."""
        result_json = '''
        {
            "status": "success",
            "message": "VM created successfully",
            "data": {"vm_id": "abc-123"},
            "correlation_id": "test-123"
        }
        '''
        envelope, error = parse_job_result(result_json)
        
        assert envelope is not None
        assert error is None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.message == "VM created successfully"
        assert envelope.data["vm_id"] == "abc-123"

    def test_parse_error_result_with_code(self):
        """Parse an error result with machine-readable error code."""
        result_json = '''
        {
            "status": "error",
            "message": "VM name already exists",
            "code": "VM_NAME_CONFLICT",
            "correlation_id": "test-456"
        }
        '''
        envelope, error = parse_job_result(result_json)
        
        assert envelope is not None
        assert error is None
        assert envelope.status == JobResultStatus.ERROR
        assert envelope.code == "VM_NAME_CONFLICT"

    def test_parse_partial_failure_result(self):
        """Parse a partial failure result."""
        result_json = '''
        {
            "status": "partial",
            "message": "VM created but NIC attachment failed",
            "data": {"vm_id": "def-456"},
            "code": "NIC_ATTACHMENT_FAILED",
            "logs": ["VM created", "NIC attachment error: network not found"]
        }
        '''
        envelope, error = parse_job_result(result_json)
        
        assert envelope is not None
        assert error is None
        assert envelope.status == JobResultStatus.PARTIAL
        assert len(envelope.logs) == 2

    def test_parse_invalid_json(self):
        """Handle invalid JSON gracefully."""
        result_json = '{ invalid json }'
        envelope, error = parse_job_result(result_json)
        
        assert envelope is None
        assert error is not None
        assert "Invalid JSON" in error

    def test_parse_empty_result(self):
        """Handle empty result gracefully."""
        envelope, error = parse_job_result("")
        
        assert envelope is None
        assert error is not None
        assert "Empty" in error

    def test_parse_non_object_json(self):
        """Handle non-object JSON gracefully."""
        envelope, error = parse_job_result('["array", "not", "object"]')
        
        assert envelope is None
        assert error is not None
        assert "Expected JSON object" in error

    def test_parse_missing_required_fields(self):
        """Handle missing required fields."""
        result_json = '{"message": "test"}'  # Missing status
        envelope, error = parse_job_result(result_json)
        
        assert envelope is None
        assert error is not None


class TestValidationErrorHandling:
    """Test input validation error handling."""

    def test_vm_name_too_long(self):
        """Reject VM name that exceeds maximum length."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="a" * 65,  # Max is 64
                gb_ram=4,
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert any("vm_name" in str(e) for e in errors)

    def test_vm_ram_below_minimum(self):
        """Reject RAM below minimum."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test-vm",
                gb_ram=0,  # Min is 1
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert any("gb_ram" in str(e) for e in errors)

    def test_vm_ram_above_maximum(self):
        """Reject RAM above maximum."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test-vm",
                gb_ram=513,  # Max is 512
                cpu_cores=2,
            )
        
        errors = exc_info.value.errors()
        assert any("gb_ram" in str(e) for e in errors)

    def test_vm_cpu_below_minimum(self):
        """Reject CPU cores below minimum."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=0,  # Min is 1
            )
        
        errors = exc_info.value.errors()
        assert any("cpu_cores" in str(e) for e in errors)

    def test_vm_cpu_above_maximum(self):
        """Reject CPU cores above maximum."""
        with pytest.raises(ValidationError) as exc_info:
            VmSpec(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=65,  # Max is 64
            )
        
        errors = exc_info.value.errors()
        assert any("cpu_cores" in str(e) for e in errors)

    def test_disk_size_below_minimum(self):
        """Reject disk size below minimum."""
        with pytest.raises(ValidationError) as exc_info:
            DiskSpec(disk_size_gb=0)  # Min is 1
        
        errors = exc_info.value.errors()
        assert any("disk_size_gb" in str(e) for e in errors)

    def test_disk_size_above_maximum(self):
        """Reject disk size above maximum."""
        with pytest.raises(ValidationError) as exc_info:
            DiskSpec(disk_size_gb=65537)  # Max is 65536
        
        errors = exc_info.value.errors()
        assert any("disk_size_gb" in str(e) for e in errors)


class TestGuestConfigParameterSets:
    """Test parameter set validation in guest configuration."""

    def test_partial_domain_join_rejected(self):
        """Reject partial domain join configuration (all-or-none)."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="admin",
                guest_la_pw="password123",
                guest_domain_jointarget="domain.com",  # Partial - missing other fields
            )
        
        errors = exc_info.value.errors()
        assert any("domain" in str(e).lower() for e in errors)

    def test_complete_domain_join_accepted(self):
        """Accept complete domain join configuration."""
        config = GuestConfigSpec(
            guest_la_uid="admin",
            guest_la_pw="password123",
            guest_domain_jointarget="domain.com",
            guest_domain_joinuid="domain\\admin",
            guest_domain_joinpw="domainpass",
            guest_domain_joinou="OU=Servers,DC=domain,DC=com",
        )
        
        assert config.guest_domain_jointarget == "domain.com"

    def test_partial_static_ip_rejected(self):
        """Reject partial static IP configuration (all-or-none for required fields)."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="admin",
                guest_la_pw="password123",
                guest_v4_ipaddr="192.168.1.10",  # Partial - missing gateway, DNS, etc.
            )
        
        errors = exc_info.value.errors()
        assert any("static" in str(e).lower() or "ip" in str(e).lower() for e in errors)

    def test_complete_static_ip_accepted(self):
        """Accept complete static IP configuration."""
        config = GuestConfigSpec(
            guest_la_uid="admin",
            guest_la_pw="password123",
            guest_v4_ipaddr="192.168.1.10",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="8.8.8.8",
        )
        
        assert config.guest_v4_ipaddr == "192.168.1.10"

    def test_partial_ansible_config_rejected(self):
        """Reject partial Ansible configuration (all-or-none)."""
        with pytest.raises(ValidationError) as exc_info:
            GuestConfigSpec(
                guest_la_uid="admin",
                guest_la_pw="password123",
                cnf_ansible_ssh_user="ansible",  # Partial - missing SSH key
            )
        
        errors = exc_info.value.errors()
        assert any("ansible" in str(e).lower() for e in errors)

    def test_complete_ansible_config_accepted(self):
        """Accept complete Ansible configuration."""
        config = GuestConfigSpec(
            guest_la_uid="admin",
            guest_la_pw="password123",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-rsa AAAAB3...",
        )
        
        assert config.cnf_ansible_ssh_user == "ansible"


class TestLargeVMConfiguration:
    """Test handling of large and complex VM configurations."""

    def test_maximum_valid_vm_config(self):
        """Create VM with maximum valid resources."""
        vm_spec = VmSpec(
            vm_name="large-vm-test",
            gb_ram=512,  # Maximum
            cpu_cores=64,  # Maximum
            storage_class="premium-ssd",
            vm_clustered=True,
        )
        
        assert vm_spec.gb_ram == 512
        assert vm_spec.cpu_cores == 64

    def test_maximum_valid_disk_config(self):
        """Create disk with maximum valid size."""
        disk_spec = DiskSpec(
            vm_id="a" * 36,  # Valid GUID length
            disk_size_gb=65536,  # Maximum (64 TB)
            storage_class="premium-ssd",
            disk_type="Fixed",
        )
        
        assert disk_spec.disk_size_gb == 65536

    def test_complete_deployment_with_all_features(self):
        """Test complete deployment with all optional features enabled."""
        deployment = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="full-featured-vm",
                gb_ram=64,
                cpu_cores=16,
                storage_class="premium-ssd",
                vm_clustered=True,
            ),
            disk_spec=DiskSpec(
                disk_size_gb=1024,
                storage_class="premium-ssd",
                disk_type="Dynamic",
                image_name="windows-server-2022",
            ),
            nic_spec=NicSpec(
                network="Production",
                adapter_name="Production-NIC",
            ),
            guest_config=GuestConfigSpec(
                guest_la_uid="administrator",
                guest_la_pw="P@ssw0rd123!",
                guest_domain_jointarget="corp.example.com",
                guest_domain_joinuid="CORP\\svc-provisioning",
                guest_domain_joinpw="DomainP@ss123!",
                guest_domain_joinou="OU=Servers,OU=Production,DC=corp,DC=example,DC=com",
                guest_v4_ipaddr="10.0.1.100",
                guest_v4_cidrprefix=24,
                guest_v4_defaultgw="10.0.1.1",
                guest_v4_dns1="10.0.1.10",
                guest_v4_dns2="10.0.1.11",
                guest_net_dnssuffix="corp.example.com",
                cnf_ansible_ssh_user="ansible",
                cnf_ansible_ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC...",
            ),
            target_host="hyperv-prod-01.corp.example.com",
        )
        
        assert deployment.vm_spec.vm_clustered is True
        assert deployment.disk_spec.image_name == "windows-server-2022"
        assert deployment.guest_config.guest_domain_jointarget == "corp.example.com"
        assert deployment.guest_config.guest_v4_ipaddr == "10.0.1.100"
        assert deployment.guest_config.cnf_ansible_ssh_user == "ansible"


class TestJobRequestEnvelopeCreation:
    """Test creation of job request envelopes."""

    def test_create_job_request_with_minimal_params(self):
        """Create job request with minimal parameters."""
        vm_spec = VmSpec(vm_name="test", gb_ram=4, cpu_cores=2)
        request = create_job_request(
            operation="vm.create",
            resource_spec=vm_spec.model_dump(),
        )
        
        assert request.operation == "vm.create"
        assert request.resource_spec["vm_name"] == "test"
        assert request.correlation_id is not None  # Auto-generated
        assert "timestamp" in request.metadata

    def test_create_job_request_with_custom_correlation_id(self):
        """Create job request with custom correlation ID."""
        vm_spec = VmSpec(vm_name="test", gb_ram=4, cpu_cores=2)
        custom_id = "custom-correlation-123"
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=vm_spec.model_dump(),
            correlation_id=custom_id,
        )
        
        assert request.correlation_id == custom_id

    def test_create_job_request_with_custom_metadata(self):
        """Create job request with custom metadata."""
        vm_spec = VmSpec(vm_name="test", gb_ram=4, cpu_cores=2)
        custom_metadata = {"user": "admin", "priority": "high"}
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=vm_spec.model_dump(),
            metadata=custom_metadata,
        )
        
        assert request.metadata["user"] == "admin"
        assert request.metadata["priority"] == "high"
        assert "timestamp" in request.metadata  # Still auto-added


class TestErrorCodeConsistency:
    """Test that error codes are consistent across the system."""

    def test_error_envelope_with_standard_codes(self):
        """Test standard error codes in result envelopes."""
        standard_codes = [
            "VM_NAME_CONFLICT",
            "VM_NOT_FOUND",
            "DISK_ATTACHMENT_FAILED",
            "NIC_CREATION_FAILED",
            "NETWORK_NOT_FOUND",
            "STORAGE_CLASS_NOT_FOUND",
            "INSUFFICIENT_RESOURCES",
            "HOST_UNREACHABLE",
            "UNKNOWN",
        ]
        
        for code in standard_codes:
            result_json = f'{{"status": "error", "message": "Test", "code": "{code}"}}'
            envelope, error = parse_job_result(result_json)
            
            assert envelope is not None
            assert envelope.code == code

    def test_error_envelope_without_code(self):
        """Test error envelope without error code (should be allowed)."""
        result_json = '{"status": "error", "message": "Generic error"}'
        envelope, error = parse_job_result(result_json)
        
        assert envelope is not None
        assert envelope.code is None
