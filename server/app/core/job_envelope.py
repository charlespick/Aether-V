"""Job envelope utilities for the new server→agent protocol.

Phase 2: These utilities create JobRequest envelopes and parse JobResult responses.
They are introduced alongside the existing schema-driven protocol but are not yet
connected to production code paths.

Functions:
- create_job_request: Create a JobRequest envelope from operation and resource spec
- parse_job_result: Parse raw PowerShell JSON output into JobResultEnvelope
- generate_correlation_id: Generate unique correlation IDs for job tracking
"""
import json
import uuid
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

from .pydantic_models import (
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
    VmSpec,
    DiskSpec,
    NicSpec,
)


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for job tracking.
    
    Returns:
        A UUID4 string to be used as correlation_id
    """
    return str(uuid.uuid4())


def create_job_request(
    operation: str,
    resource_spec: Dict[str, Any],
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> JobRequest:
    """Create a JobRequest envelope for transmission to host agent.
    
    This function wraps a resource specification in the standard JobRequest
    envelope format expected by the new protocol.
    
    Args:
        operation: Operation identifier (e.g., 'vm.create', 'disk.clone', 'nic.update')
        resource_spec: Resource specification dict matching the operation's expected model
        correlation_id: Optional correlation ID. If None, one will be generated
        metadata: Optional metadata dict. If None, timestamp will be added automatically
    
    Returns:
        JobRequest envelope ready for JSON serialization
    
    Example:
        >>> vm_spec = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        >>> request = create_job_request(
        ...     operation="vm.create",
        ...     resource_spec=vm_spec.model_dump(),
        ... )
        >>> json_payload = request.model_dump_json()
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()
    
    if metadata is None:
        metadata = {}
    
    # Add timestamp if not provided
    if "timestamp" not in metadata:
        metadata["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    return JobRequest(
        operation=operation,
        resource_spec=resource_spec,
        correlation_id=correlation_id,
        metadata=metadata,
    )


def parse_job_result(raw_json: str) -> Tuple[Optional[JobResultEnvelope], Optional[str]]:
    """Parse raw PowerShell JSON output into a validated JobResultEnvelope.
    
    This function takes the JSON string returned by a PowerShell host agent
    and parses it into a validated JobResultEnvelope model.
    
    Args:
        raw_json: Raw JSON string from PowerShell host agent
    
    Returns:
        Tuple of (JobResultEnvelope, error_message)
        - On success: (JobResultEnvelope instance, None)
        - On failure: (None, error description string)
    
    Example:
        >>> result_json = '''{"status": "success", "message": "VM created"}'''
        >>> envelope, error = parse_job_result(result_json)
        >>> if envelope:
        ...     print(envelope.status)
        ...     print(envelope.message)
    """
    if not raw_json or not raw_json.strip():
        return None, "Empty or whitespace-only JSON response"
    
    try:
        # Parse JSON string to dict
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {str(exc)}"
    
    if not isinstance(data, dict):
        return None, f"Expected JSON object, got {type(data).__name__}"
    
    try:
        # Validate and construct JobResultEnvelope
        envelope = JobResultEnvelope(**data)
        return envelope, None
    except Exception as exc:
        return None, f"Failed to parse job result: {str(exc)}"


def create_job_request_from_vm_spec(
    vm_spec: VmSpec,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> JobRequest:
    """Create a vm.create JobRequest from a VmSpec.
    
    Convenience function for creating VM creation job requests.
    
    Args:
        vm_spec: VmSpec instance
        correlation_id: Optional correlation ID
        metadata: Optional metadata dict
    
    Returns:
        JobRequest envelope for vm.create operation
    """
    return create_job_request(
        operation="vm.create",
        resource_spec=vm_spec.model_dump(),
        correlation_id=correlation_id,
        metadata=metadata,
    )


def create_job_request_from_disk_spec(
    disk_spec: DiskSpec,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> JobRequest:
    """Create a disk.create JobRequest from a DiskSpec.
    
    Convenience function for creating disk creation job requests.
    
    Args:
        disk_spec: DiskSpec instance
        correlation_id: Optional correlation ID
        metadata: Optional metadata dict
    
    Returns:
        JobRequest envelope for disk.create operation
    """
    return create_job_request(
        operation="disk.create",
        resource_spec=disk_spec.model_dump(),
        correlation_id=correlation_id,
        metadata=metadata,
    )


def create_job_request_from_nic_spec(
    nic_spec: NicSpec,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> JobRequest:
    """Create a nic.create JobRequest from a NicSpec.
    
    Convenience function for creating NIC creation job requests.
    
    Args:
        nic_spec: NicSpec instance
        correlation_id: Optional correlation ID
        metadata: Optional metadata dict
    
    Returns:
        JobRequest envelope for nic.create operation
    """
    return create_job_request(
        operation="nic.create",
        resource_spec=nic_spec.model_dump(),
        correlation_id=correlation_id,
        metadata=metadata,
    )
