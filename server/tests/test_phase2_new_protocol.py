"""Phase 2 Tests: New JSON Envelope Protocol

This test suite validates the new JSON envelope protocol components introduced
in Phase 2. These tests ensure that:

1. Job envelope generation works correctly
2. Job result parsing handles various response formats
3. The PowerShell stub entry point (Main-NewProtocol.ps1) works end-to-end
4. Both old and new protocols can coexist

The new protocol is tested but not yet connected to production code paths.
"""
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from app.core.job_envelope import (
    generate_correlation_id,
    create_job_request,
    parse_job_result,
    create_job_request_from_vm_spec,
    create_job_request_from_disk_spec,
    create_job_request_from_nic_spec,
)
from app.core.pydantic_models import (
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
    VmSpec,
    DiskSpec,
    NicSpec,
)


class TestCorrelationIdGeneration:
    """Test correlation ID generation."""
    
    def test_generate_correlation_id_returns_uuid(self):
        """Test that correlation ID is a valid UUID."""
        corr_id = generate_correlation_id()
        
        # Should be a valid UUID string
        assert isinstance(corr_id, str)
        assert len(corr_id) == 36  # Standard UUID format with hyphens
        
        # Should parse as UUID
        parsed_uuid = uuid.UUID(corr_id)
        assert str(parsed_uuid) == corr_id
    
    def test_generate_correlation_id_is_unique(self):
        """Test that multiple calls generate unique IDs."""
        ids = [generate_correlation_id() for _ in range(100)]
        
        # All IDs should be unique
        assert len(set(ids)) == 100


class TestJobRequestCreation:
    """Test JobRequest envelope creation."""
    
    def test_create_job_request_basic(self):
        """Test basic job request creation."""
        resource_spec = {"vm_name": "test-vm", "gb_ram": 4, "cpu_cores": 2}
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=resource_spec,
        )
        
        assert isinstance(request, JobRequest)
        assert request.operation == "vm.create"
        assert request.resource_spec == resource_spec
        assert request.correlation_id is not None
        assert "timestamp" in request.metadata
    
    def test_create_job_request_with_correlation_id(self):
        """Test job request with explicit correlation ID."""
        corr_id = "test-correlation-123"
        resource_spec = {"vm_name": "test-vm"}
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=resource_spec,
            correlation_id=corr_id,
        )
        
        assert request.correlation_id == corr_id
    
    def test_create_job_request_with_metadata(self):
        """Test job request with custom metadata."""
        resource_spec = {"vm_name": "test-vm"}
        metadata = {"host": "hyperv-01", "user": "admin"}
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=resource_spec,
            metadata=metadata,
        )
        
        assert request.metadata["host"] == "hyperv-01"
        assert request.metadata["user"] == "admin"
        assert "timestamp" in request.metadata  # Auto-added
    
    def test_create_job_request_serialization(self):
        """Test that job request can be serialized to JSON."""
        resource_spec = {"vm_name": "test-vm", "gb_ram": 4, "cpu_cores": 2}
        
        request = create_job_request(
            operation="vm.create",
            resource_spec=resource_spec,
        )
        
        # Should serialize to JSON without errors
        json_str = request.model_dump_json()
        assert isinstance(json_str, str)
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["operation"] == "vm.create"
        assert parsed["resource_spec"]["vm_name"] == "test-vm"


class TestJobRequestFromSpec:
    """Test convenience functions for creating JobRequests from specs."""
    
    def test_create_job_request_from_vm_spec(self):
        """Test creating vm.create JobRequest from VmSpec."""
        vm_spec = VmSpec(
            vm_name="web-01",
            gb_ram=4,
            cpu_cores=2,
        )
        
        request = create_job_request_from_vm_spec(vm_spec)
        
        assert request.operation == "vm.create"
        assert request.resource_spec["vm_name"] == "web-01"
        assert request.resource_spec["gb_ram"] == 4
        assert request.correlation_id is not None
    
    def test_create_job_request_from_disk_spec(self):
        """Test creating disk.create JobRequest from DiskSpec."""
        disk_spec = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            image_name="Windows Server 2022",
            disk_size_gb=100,
        )
        
        request = create_job_request_from_disk_spec(disk_spec)
        
        assert request.operation == "disk.create"
        assert request.resource_spec["image_name"] == "Windows Server 2022"
    
    def test_create_job_request_from_nic_spec(self):
        """Test creating nic.create JobRequest from NicSpec."""
        nic_spec = NicSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            network="Production",
        )
        
        request = create_job_request_from_nic_spec(nic_spec)
        
        assert request.operation == "nic.create"
        assert request.resource_spec["network"] == "Production"


class TestJobResultParsing:
    """Test JobResult parsing from PowerShell JSON."""
    
    def test_parse_job_result_success(self):
        """Test parsing a successful job result."""
        raw_json = json.dumps({
            "status": "success",
            "message": "VM created successfully",
            "data": {"vm_id": "12345678-1234-1234-1234-123456789abc"},
            "correlation_id": "test-123",
        })
        
        envelope, error = parse_job_result(raw_json)
        
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.message == "VM created successfully"
        assert envelope.data["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert envelope.correlation_id == "test-123"
    
    def test_parse_job_result_error(self):
        """Test parsing an error job result."""
        raw_json = json.dumps({
            "status": "error",
            "message": "VM creation failed",
            "code": "VM_NAME_CONFLICT",
            "data": {},
            "logs": ["Error: VM already exists", "Stack trace..."],
        })
        
        envelope, error = parse_job_result(raw_json)
        
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.ERROR
        assert envelope.code == "VM_NAME_CONFLICT"
        assert len(envelope.logs) == 2
    
    def test_parse_job_result_partial(self):
        """Test parsing a partial success job result."""
        raw_json = json.dumps({
            "status": "partial",
            "message": "VM created but disk attachment failed",
            "data": {"vm_id": "12345678-1234-1234-1234-123456789abc"},
        })
        
        envelope, error = parse_job_result(raw_json)
        
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.PARTIAL
    
    def test_parse_job_result_invalid_json(self):
        """Test parsing invalid JSON."""
        raw_json = "not valid json {"
        
        envelope, error = parse_job_result(raw_json)
        
        assert envelope is None
        assert error is not None
        assert "Invalid JSON" in error
    
    def test_parse_job_result_empty_string(self):
        """Test parsing empty string."""
        envelope, error = parse_job_result("")
        
        assert envelope is None
        assert error is not None
        assert "Empty or whitespace" in error
    
    def test_parse_job_result_missing_required_fields(self):
        """Test parsing JSON with missing required fields."""
        raw_json = json.dumps({
            "status": "success",
            # Missing 'message' field
        })
        
        envelope, error = parse_job_result(raw_json)
        
        assert envelope is None
        assert error is not None
        assert "Failed to parse" in error
    
    def test_parse_job_result_invalid_status(self):
        """Test parsing JSON with invalid status value."""
        raw_json = json.dumps({
            "status": "invalid_status",
            "message": "Test",
        })
        
        envelope, error = parse_job_result(raw_json)
        
        assert envelope is None
        assert error is not None


class TestNewProtocolStubEndToEnd:
    """End-to-end tests for the PowerShell stub (Main-NewProtocol.ps1)."""
    
    @pytest.fixture
    def stub_script_path(self):
        """Get path to Main-NewProtocol.ps1."""
        repo_root = Path(__file__).parent.parent.parent
        script_path = repo_root / "Powershell" / "Main-NewProtocol.ps1"
        
        if not script_path.exists():
            pytest.skip(f"Stub script not found at {script_path}")
        
        return script_path
    
    @pytest.fixture
    def pwsh_available(self):
        """Check if pwsh is available."""
        try:
            result = subprocess.run(
                ["pwsh", "-Version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                pytest.skip("PowerShell (pwsh) not available")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("PowerShell (pwsh) not available")
    
    def test_stub_vm_create_operation(self, stub_script_path, pwsh_available):
        """Test stub with vm.create operation."""
        # Create job request
        vm_spec = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        request = create_job_request_from_vm_spec(vm_spec)
        
        # Serialize to JSON
        json_input = request.model_dump_json()
        
        # Invoke PowerShell stub
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Check execution succeeded
        assert result.returncode == 0, f"Stub failed: {result.stderr}"
        
        # Parse result
        envelope, error = parse_job_result(result.stdout)
        assert error is None, f"Failed to parse result: {error}"
        assert envelope is not None
        
        # Verify result
        assert envelope.status == JobResultStatus.SUCCESS
        assert "vm.create" in envelope.message
        assert envelope.data["stub_operation"] == "vm.create"
        assert envelope.data["stub_received"] is True
        assert envelope.correlation_id == request.correlation_id
        
        # Should have created a fake ID
        assert "created_id" in envelope.data
        uuid.UUID(envelope.data["created_id"])  # Validate it's a UUID
    
    def test_stub_disk_create_operation(self, stub_script_path, pwsh_available):
        """Test stub with disk.create operation."""
        disk_spec = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            image_name="Windows Server 2022",
        )
        request = create_job_request_from_disk_spec(disk_spec)
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["stub_operation"] == "disk.create"
    
    def test_stub_nic_create_operation(self, stub_script_path, pwsh_available):
        """Test stub with nic.create operation."""
        nic_spec = NicSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            network="Production",
        )
        request = create_job_request_from_nic_spec(nic_spec)
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["stub_operation"] == "nic.create"
    
    def test_stub_with_invalid_envelope(self, stub_script_path, pwsh_available):
        """Test stub with invalid JSON envelope."""
        # Send invalid JSON
        json_input = '{"invalid": "no operation field"}'
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0  # Script should handle errors gracefully
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.status == JobResultStatus.ERROR
        assert "operation" in envelope.message.lower()
    
    def test_stub_preserves_correlation_id(self, stub_script_path, pwsh_available):
        """Test that stub preserves correlation_id from request."""
        custom_corr_id = "custom-correlation-id-12345"
        
        vm_spec = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        request = create_job_request_from_vm_spec(
            vm_spec,
            correlation_id=custom_corr_id,
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.correlation_id == custom_corr_id
    
    def test_stub_returns_logs(self, stub_script_path, pwsh_available):
        """Test that stub returns logs in the result."""
        vm_spec = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        request = create_job_request_from_vm_spec(vm_spec)
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(stub_script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert len(envelope.logs) > 0
        assert any("operation" in log.lower() for log in envelope.logs)


class TestProtocolCoexistence:
    """Test that new and old protocols can coexist."""
    
    def test_new_protocol_models_exist(self):
        """Verify new protocol models are defined."""
        # These should all be importable and usable
        from app.core.pydantic_models import JobRequest, JobResultEnvelope
        from app.core.job_envelope import create_job_request, parse_job_result
        
        assert JobRequest is not None
        assert JobResultEnvelope is not None
        assert callable(create_job_request)
        assert callable(parse_job_result)
    
    def test_old_protocol_still_works(self):
        """Verify old protocol functions still exist."""
        # Old protocol components should still be importable
        from app.core.job_schema import (
            load_schema_by_id,
            validate_job_submission,
        )
        
        assert callable(load_schema_by_id)
        assert callable(validate_job_submission)
    
    def test_pydantic_converters_still_work(self):
        """Verify Phase 1 converters still work."""
        from app.core.pydantic_converters import (
            convert_vm_schema_to_spec,
            convert_disk_schema_to_spec,
        )
        
        # Old converters should still function
        schema_values = {"vm_name": "test", "gb_ram": 4, "cpu_cores": 2}
        result_dict, error = convert_vm_schema_to_spec(schema_values)
        
        assert error is None
        assert result_dict["vm_name"] == "test"
