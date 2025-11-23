"""Phase 3 Tests: Noop-Test Round-Trip Validation

This test suite validates the first operation to use the new protocol end-to-end.
The noop-test operation proves that:

1. The server can create JobRequest envelopes
2. PowerShell Main-NewProtocol.ps1 can receive and parse the envelope
3. PowerShell can execute the operation and return a JobResult
4. The server can parse the JobResult and complete the job

This is a critical milestone that validates the entire new protocol stack before
converting any production operations.
"""
import json
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any

import pytest

from app.core.job_envelope import (
    create_job_request,
    parse_job_result,
)
from app.core.pydantic_models import (
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
)


class TestNoopTestPowerShellExecution:
    """Test noop-test operation execution in PowerShell."""
    
    @pytest.fixture
    def script_path(self):
        """Get path to Main-NewProtocol.ps1."""
        repo_root = Path(__file__).parent.parent.parent
        script_path = repo_root / "Powershell" / "Main-NewProtocol.ps1"
        
        if not script_path.exists():
            pytest.skip(f"Script not found at {script_path}")
        
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
    
    def test_noop_test_basic_execution(self, script_path, pwsh_available):
        """Test basic noop-test operation execution."""
        # Create a noop-test job request
        resource_spec = {
            "test_field": "test_value",
            "test_number": 42,
        }
        
        request = create_job_request(
            operation="noop-test",
            resource_spec=resource_spec,
        )
        
        # Serialize to JSON
        json_input = request.model_dump_json()
        
        # Invoke PowerShell script
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Check execution succeeded
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        
        # Parse result
        envelope, error = parse_job_result(result.stdout)
        assert error is None, f"Failed to parse result: {error}"
        assert envelope is not None
        
        # Verify result structure
        assert envelope.status == JobResultStatus.SUCCESS
        assert "noop-test" in envelope.message.lower()
        assert envelope.correlation_id == request.correlation_id
        
        # Verify operation was validated
        assert envelope.data["operation_validated"] is True
        assert envelope.data["envelope_parsed"] is True
        assert envelope.data["json_valid"] is True
        
        # Verify test fields were echoed back
        assert envelope.data["test_field_echo"] == "test_value"
        assert envelope.data["test_number_echo"] == 42
    
    def test_noop_test_with_empty_resource_spec(self, script_path, pwsh_available):
        """Test noop-test with empty resource spec."""
        request = create_job_request(
            operation="noop-test",
            resource_spec={},
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["operation_validated"] is True
    
    def test_noop_test_preserves_correlation_id(self, script_path, pwsh_available):
        """Test that correlation_id is preserved in round-trip."""
        custom_corr_id = "custom-test-correlation-12345"
        
        request = create_job_request(
            operation="noop-test",
            resource_spec={"test": "data"},
            correlation_id=custom_corr_id,
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.correlation_id == custom_corr_id
    
    def test_noop_test_returns_logs(self, script_path, pwsh_available):
        """Test that noop-test returns diagnostic logs."""
        request = create_job_request(
            operation="noop-test",
            resource_spec={"test": "value"},
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert len(envelope.logs) > 0
        
        # Verify logs contain expected entries
        log_text = " ".join(envelope.logs).lower()
        assert "noop-test" in log_text
        assert "correlation id" in log_text
    
    def test_noop_test_validates_json_parsing(self, script_path, pwsh_available):
        """Test that noop-test validates STDIN JSON parsing."""
        request = create_job_request(
            operation="noop-test",
            resource_spec={
                "complex_field": {"nested": "value"},
                "array_field": [1, 2, 3],
            },
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["json_valid"] is True
        assert envelope.data["envelope_parsed"] is True


class TestNoopTestProtocolIsolation:
    """Test that noop-test uses new protocol while old operations use old protocol."""
    
    @pytest.fixture
    def script_path(self):
        """Get path to Main-NewProtocol.ps1."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "Powershell" / "Main-NewProtocol.ps1"
    
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
    
    def test_noop_test_operation_uses_new_protocol(self, script_path, pwsh_available):
        """Verify noop-test operation is handled by new protocol code path."""
        request = create_job_request(
            operation="noop-test",
            resource_spec={"test": "data"},
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        # Verify this is not the stub response
        assert "stub_operation" not in envelope.data
        assert "operation_validated" in envelope.data
        assert envelope.data["operation_validated"] is True
    
    def test_other_operations_still_use_stub(self, script_path, pwsh_available):
        """Verify non-implemented operations return appropriate errors.
        
        Phase 4 update: vm.create is now fully implemented, so this test
        has been updated to reflect that all resource operations are implemented.
        Unsupported operations should return error status.
        """
        # Test an unsupported operation
        request = create_job_request(
            operation="unsupported.operation",
            resource_spec={"test": "data"},
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Should return exit code 0 (PowerShell script ran)
        # but with error status in the envelope
        assert result.returncode == 0
        envelope, error = parse_job_result(result.stdout)
        
        assert envelope is not None
        # Verify this returns an error (not a stub)
        assert envelope.status == "error"
        assert "unsupported" in envelope.message.lower() or "operation error" in envelope.message.lower()


class TestNoopTestEnvelopeValidation:
    """Test envelope format validation for noop-test."""
    
    def test_create_noop_test_request_envelope(self):
        """Test creating a properly formatted noop-test request."""
        resource_spec = {
            "test_string": "hello",
            "test_int": 123,
            "test_bool": True,
        }
        
        request = create_job_request(
            operation="noop-test",
            resource_spec=resource_spec,
        )
        
        assert isinstance(request, JobRequest)
        assert request.operation == "noop-test"
        assert request.resource_spec == resource_spec
        assert request.correlation_id is not None
        assert "timestamp" in request.metadata
    
    def test_noop_test_request_serialization(self):
        """Test that noop-test request serializes to valid JSON."""
        resource_spec = {"test": "data"}
        
        request = create_job_request(
            operation="noop-test",
            resource_spec=resource_spec,
        )
        
        json_str = request.model_dump_json()
        assert isinstance(json_str, str)
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["operation"] == "noop-test"
        assert parsed["resource_spec"]["test"] == "data"
        assert "correlation_id" in parsed
        assert "metadata" in parsed
    
    def test_parse_noop_test_result_success(self):
        """Test parsing a successful noop-test result."""
        result_json = json.dumps({
            "status": "success",
            "message": "Noop-test operation completed successfully",
            "data": {
                "operation_validated": True,
                "envelope_parsed": True,
                "json_valid": True,
            },
            "correlation_id": "test-123",
            "logs": ["Executing noop-test operation"],
        })
        
        envelope, error = parse_job_result(result_json)
        
        assert error is None
        assert envelope is not None
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["operation_validated"] is True


class TestNoopTestRoundTripIntegration:
    """Integration tests for noop-test round-trip through the full stack."""
    
    @pytest.fixture
    def script_path(self):
        """Get path to Main-NewProtocol.ps1."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "Powershell" / "Main-NewProtocol.ps1"
    
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
    
    def _execute_noop_test(
        self,
        script_path: Path,
        resource_spec: Dict[str, Any],
        correlation_id: str = None,
    ) -> JobResultEnvelope:
        """Helper to execute a noop-test and return the parsed result."""
        request = create_job_request(
            operation="noop-test",
            resource_spec=resource_spec,
            correlation_id=correlation_id,
        )
        
        json_input = request.model_dump_json()
        
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        
        envelope, error = parse_job_result(result.stdout)
        assert error is None, f"Parse failed: {error}"
        assert envelope is not None
        
        return envelope
    
    def test_round_trip_with_string_data(self, script_path, pwsh_available):
        """Test round-trip with string test data."""
        resource_spec = {"test_field": "hello world"}
        
        envelope = self._execute_noop_test(script_path, resource_spec)
        
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["test_field_echo"] == "hello world"
    
    def test_round_trip_with_numeric_data(self, script_path, pwsh_available):
        """Test round-trip with numeric test data."""
        resource_spec = {"test_number": 12345}
        
        envelope = self._execute_noop_test(script_path, resource_spec)
        
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["test_number_echo"] == 12345
    
    def test_round_trip_with_multiple_fields(self, script_path, pwsh_available):
        """Test round-trip with multiple test fields."""
        resource_spec = {
            "test_field": "value1",
            "test_number": 999,
        }
        
        envelope = self._execute_noop_test(script_path, resource_spec)
        
        assert envelope.status == JobResultStatus.SUCCESS
        assert envelope.data["test_field_echo"] == "value1"
        assert envelope.data["test_number_echo"] == 999
    
    def test_round_trip_correlation_tracking(self, script_path, pwsh_available):
        """Test that correlation IDs are tracked through round-trip."""
        custom_id = f"test-{uuid.uuid4()}"
        resource_spec = {"test": "data"}
        
        envelope = self._execute_noop_test(
            script_path, resource_spec, correlation_id=custom_id
        )
        
        assert envelope.correlation_id == custom_id
    
    def test_multiple_sequential_round_trips(self, script_path, pwsh_available):
        """Test multiple sequential noop-test executions."""
        for i in range(3):
            resource_spec = {"iteration": i}
            
            envelope = self._execute_noop_test(script_path, resource_spec)
            
            assert envelope.status == JobResultStatus.SUCCESS
            assert envelope.data["operation_validated"] is True
