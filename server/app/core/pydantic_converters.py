"""Conversion functions between YAML schemas and Pydantic models.

Phase 1: These converters bridge the gap between the existing schema-based
validation and the new Pydantic models. They:
1. Take schema-validated dicts from the old system
2. Validate them with Pydantic models
3. Return the dict shape the old system expects

This allows both validation systems to run in parallel without breaking
existing functionality.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from pydantic import ValidationError

from .pydantic_models import (
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
    ManagedDeploymentRequest,
    JobResultEnvelope,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Schema to Pydantic Converters
# ============================================================================


def convert_vm_schema_to_spec(schema_values: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Convert VM schema values to VmSpec model and back to dict.
    
    Args:
        schema_values: Dictionary from schema validation containing VM fields
        
    Returns:
        Tuple of (validated_dict, error_message)
        - validated_dict: The original dict if validation passes, or empty dict if it fails
        - error_message: None if validation passes, or error string if it fails
        
    This function validates using Pydantic but returns the same structure
    the old system expects, allowing both systems to coexist.
    """
    # Extract only VM hardware fields (not guest config)
    vm_fields = {
        "vm_name": schema_values.get("vm_name"),
        "gb_ram": schema_values.get("gb_ram"),
        "cpu_cores": schema_values.get("cpu_cores"),
        "storage_class": schema_values.get("storage_class"),
        "vm_clustered": schema_values.get("vm_clustered", False),
    }
    
    # Remove None values
    vm_fields = {k: v for k, v in vm_fields.items() if v is not None}
    
    try:
        # Validate with Pydantic
        vm_spec = VmSpec(**vm_fields)
        
        # Log successful validation
        logger.debug(
            "Pydantic validation succeeded for VM spec: %s",
            vm_spec.vm_name,
        )
        
        # Return the original dict shape for backwards compatibility
        return vm_fields, None
        
    except ValidationError as e:
        # Format Pydantic errors for logging
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Pydantic validation failed for VM spec: %s",
            error_msg,
        )
        return {}, error_msg


def convert_disk_schema_to_spec(schema_values: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Convert disk schema values to DiskSpec model and back to dict.
    
    Args:
        schema_values: Dictionary from schema validation containing disk fields
        
    Returns:
        Tuple of (validated_dict, error_message)
    """
    disk_fields = {
        "vm_id": schema_values.get("vm_id"),
        "image_name": schema_values.get("image_name"),
        "disk_size_gb": schema_values.get("disk_size_gb", 100),
        "storage_class": schema_values.get("storage_class"),
        "disk_type": schema_values.get("disk_type", "Dynamic"),
        "controller_type": schema_values.get("controller_type", "SCSI"),
    }
    
    # Remove None values except for defaults
    disk_fields = {k: v for k, v in disk_fields.items() if v is not None}
    
    try:
        disk_spec = DiskSpec(**disk_fields)
        
        logger.debug(
            "Pydantic validation succeeded for disk spec (vm_id: %s)",
            disk_spec.vm_id or "N/A",
        )
        
        return disk_fields, None
        
    except ValidationError as e:
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Pydantic validation failed for disk spec: %s",
            error_msg,
        )
        return {}, error_msg


def convert_nic_schema_to_spec(schema_values: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Convert NIC schema values to NicSpec model and back to dict.
    
    Args:
        schema_values: Dictionary from schema validation containing NIC hardware fields
        
    Returns:
        Tuple of (validated_dict, error_message)
        
    Note: This only validates NIC hardware fields. Guest IP configuration
    is handled separately in GuestConfigSpec.
    """
    nic_fields = {
        "vm_id": schema_values.get("vm_id"),
        "network": schema_values.get("network"),
        "adapter_name": schema_values.get("adapter_name"),
    }
    
    # Remove None values
    nic_fields = {k: v for k, v in nic_fields.items() if v is not None}
    
    try:
        nic_spec = NicSpec(**nic_fields)
        
        logger.debug(
            "Pydantic validation succeeded for NIC spec: %s",
            nic_spec.network,
        )
        
        return nic_fields, None
        
    except ValidationError as e:
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Pydantic validation failed for NIC spec: %s",
            error_msg,
        )
        return {}, error_msg


def convert_guest_config_schema_to_spec(schema_values: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Convert guest configuration fields to GuestConfigSpec model and back to dict.
    
    This extracts all fields marked with guest_config=True from the schema
    values and validates them as a cohesive unit.
    
    Args:
        schema_values: Dictionary from schema validation containing all fields
        
    Returns:
        Tuple of (validated_dict, error_message)
    """
    # Extract all guest config fields from VM schema
    vm_guest_fields = {
        "guest_la_uid": schema_values.get("guest_la_uid"),
        "guest_la_pw": schema_values.get("guest_la_pw"),
        "guest_domain_jointarget": schema_values.get("guest_domain_jointarget"),
        "guest_domain_joinuid": schema_values.get("guest_domain_joinuid"),
        "guest_domain_joinpw": schema_values.get("guest_domain_joinpw"),
        "guest_domain_joinou": schema_values.get("guest_domain_joinou"),
        "cnf_ansible_ssh_user": schema_values.get("cnf_ansible_ssh_user"),
        "cnf_ansible_ssh_key": schema_values.get("cnf_ansible_ssh_key"),
    }
    
    # Extract all guest config fields from NIC schema
    nic_guest_fields = {
        "guest_v4_ipaddr": schema_values.get("guest_v4_ipaddr"),
        "guest_v4_cidrprefix": schema_values.get("guest_v4_cidrprefix"),
        "guest_v4_defaultgw": schema_values.get("guest_v4_defaultgw"),
        "guest_v4_dns1": schema_values.get("guest_v4_dns1"),
        "guest_v4_dns2": schema_values.get("guest_v4_dns2"),
        "guest_net_dnssuffix": schema_values.get("guest_net_dnssuffix"),
    }
    
    # Combine all guest config fields
    guest_fields = {**vm_guest_fields, **nic_guest_fields}
    
    # Remove None and empty string values
    guest_fields = {
        k: v for k, v in guest_fields.items() 
        if v is not None and v != ""
    }
    
    # If no guest config fields provided, return empty
    if not guest_fields:
        return {}, None
    
    # Guest config requires at minimum the local admin credentials
    if "guest_la_uid" not in guest_fields or "guest_la_pw" not in guest_fields:
        error_msg = "Guest configuration requires guest_la_uid and guest_la_pw"
        logger.warning("Pydantic validation failed for guest config: %s", error_msg)
        return {}, error_msg
    
    try:
        guest_spec = GuestConfigSpec(**guest_fields)
        
        logger.debug(
            "Pydantic validation succeeded for guest config spec (user: %s)",
            guest_spec.guest_la_uid,
        )
        
        return guest_fields, None
        
    except ValidationError as e:
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Pydantic validation failed for guest config: %s",
            error_msg,
        )
        return {}, error_msg


def convert_managed_deployment_schema_to_spec(
    schema_values: Dict[str, Any],
    target_host: str,
) -> Tuple[Optional[ManagedDeploymentRequest], Optional[str]]:
    """Convert composed schema values to ManagedDeploymentRequest and validate.
    
    This is the top-level converter for managed deployments. It orchestrates
    conversion of all component specs (VM, Disk, NIC, GuestConfig) and
    validates them together.
    
    Args:
        schema_values: Dictionary from composed schema validation
        target_host: Target Hyper-V host for deployment
        
    Returns:
        Tuple of (managed_deployment_request, error_message)
        - Returns the Pydantic model instance if validation passes
        - Returns (None, error_msg) if validation fails
    """
    errors = []
    
    # Convert VM spec
    vm_dict, vm_error = convert_vm_schema_to_spec(schema_values)
    if vm_error:
        errors.append(f"VM spec: {vm_error}")
    
    # Convert disk spec if present
    disk_dict = None
    if schema_values.get("image_name") or schema_values.get("disk_size_gb"):
        disk_dict, disk_error = convert_disk_schema_to_spec(schema_values)
        if disk_error:
            errors.append(f"Disk spec: {disk_error}")
    
    # Convert NIC spec if present
    nic_dict = None
    if schema_values.get("network"):
        nic_dict, nic_error = convert_nic_schema_to_spec(schema_values)
        if nic_error:
            errors.append(f"NIC spec: {nic_error}")
    
    # Convert guest config if present
    guest_dict = None
    if schema_values.get("guest_la_uid"):
        guest_dict, guest_error = convert_guest_config_schema_to_spec(schema_values)
        if guest_error:
            errors.append(f"Guest config: {guest_error}")
    
    # If any component validation failed, return errors
    if errors:
        error_msg = "; ".join(errors)
        return None, error_msg
    
    # Build the managed deployment request
    try:
        request_dict = {
            "vm_spec": vm_dict,
            "target_host": target_host,
        }
        
        if disk_dict:
            request_dict["disk_spec"] = disk_dict
        
        if nic_dict:
            request_dict["nic_spec"] = nic_dict
        
        if guest_dict:
            request_dict["guest_config"] = guest_dict
        
        deployment_request = ManagedDeploymentRequest(**request_dict)
        
        logger.info(
            "Pydantic validation succeeded for managed deployment: %s on %s",
            deployment_request.vm_spec.vm_name,
            deployment_request.target_host,
        )
        
        return deployment_request, None
        
    except ValidationError as e:
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Pydantic validation failed for managed deployment: %s",
            error_msg,
        )
        return None, error_msg


def validate_job_result(result_data: Dict[str, Any]) -> Tuple[Optional[JobResultEnvelope], Optional[str]]:
    """Validate a job result envelope from the host agent.
    
    This validates that the PowerShell host agent returned a properly
    structured result.
    
    Args:
        result_data: Dictionary parsed from host agent JSON response
        
    Returns:
        Tuple of (job_result, error_message)
    """
    try:
        job_result = JobResultEnvelope(**result_data)
        
        logger.debug(
            "Job result validation succeeded: status=%s, correlation_id=%s",
            job_result.status.value,
            job_result.correlation_id or "N/A",
        )
        
        return job_result, None
        
    except ValidationError as e:
        error_msg = _format_pydantic_errors(e)
        logger.warning(
            "Job result validation failed: %s",
            error_msg,
        )
        return None, error_msg


# ============================================================================
# Helper Functions
# ============================================================================


def _format_pydantic_errors(e: ValidationError) -> str:
    """Format Pydantic validation errors into a readable string.
    
    Args:
        e: ValidationError from Pydantic
        
    Returns:
        Formatted error string
    """
    errors = []
    for error in e.errors():
        loc = " -> ".join(str(l) for l in error["loc"])
        msg = error["msg"]
        errors.append(f"{loc}: {msg}")
    
    return "; ".join(errors)


def log_validation_comparison(
    schema_passed: bool,
    pydantic_error: Optional[str],
    operation: str,
) -> None:
    """Log a comparison of schema vs Pydantic validation results.
    
    This is useful during Phase 1 to track where the two validation
    systems agree or disagree.
    
    Args:
        schema_passed: Whether schema validation passed
        pydantic_error: Error message from Pydantic (None if passed)
        operation: Operation being validated (for logging context)
    """
    pydantic_passed = pydantic_error is None
    
    if schema_passed and pydantic_passed:
        logger.debug(
            "Validation agreement for %s: both passed",
            operation,
        )
    elif not schema_passed and not pydantic_passed:
        logger.debug(
            "Validation agreement for %s: both failed",
            operation,
        )
    elif schema_passed and not pydantic_passed:
        logger.warning(
            "Validation disagreement for %s: schema passed but Pydantic failed: %s",
            operation,
            pydantic_error,
        )
    else:  # not schema_passed and pydantic_passed
        logger.warning(
            "Validation disagreement for %s: schema failed but Pydantic passed",
            operation,
        )
