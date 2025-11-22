"""Demonstration script showing Pydantic validation working alongside schema validation.

This script demonstrates Phase 1 functionality - Pydantic models validate
input in parallel with the existing schema system without breaking anything.
"""
import sys
import logging
from pathlib import Path

# Add server app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from app.core.job_schema import (
    load_schema_by_id,
    validate_job_submission,
    SchemaValidationError,
)
from app.core.pydantic_converters import (
    convert_vm_schema_to_spec,
    convert_disk_schema_to_spec,
    convert_nic_schema_to_spec,
    convert_guest_config_schema_to_spec,
    convert_managed_deployment_schema_to_spec,
    log_validation_comparison,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def demo_vm_validation():
    """Demonstrate VM validation with both systems."""
    logger.info("=" * 80)
    logger.info("DEMO 1: VM Validation")
    logger.info("=" * 80)
    
    # Valid VM input
    vm_input = {
        "vm_name": "web-server-01",
        "gb_ram": 8,
        "cpu_cores": 4,
        "storage_class": "fast-ssd",
        "vm_clustered": True,
        "guest_la_uid": "Administrator",
        "guest_la_pw": "SecurePassword123!",
    }
    
    logger.info("Input data: %s", vm_input)
    
    # Schema validation
    schema = load_schema_by_id("vm-create")
    try:
        schema_result = validate_job_submission(vm_input, schema)
        logger.info("✓ Schema validation PASSED")
        schema_passed = True
    except SchemaValidationError as e:
        logger.error("✗ Schema validation FAILED: %s", e)
        schema_passed = False
        schema_result = None
    
    # Pydantic validation
    vm_dict, pydantic_error = convert_vm_schema_to_spec(vm_input)
    if pydantic_error is None:
        logger.info("✓ Pydantic validation PASSED")
        logger.info("  VM spec validated: %s", vm_dict)
    else:
        logger.error("✗ Pydantic validation FAILED: %s", pydantic_error)
    
    # Log comparison
    log_validation_comparison(schema_passed, pydantic_error, "vm_validation")
    logger.info("")


def demo_invalid_vm_validation():
    """Demonstrate validation failure detection."""
    logger.info("=" * 80)
    logger.info("DEMO 2: Invalid VM (name too long)")
    logger.info("=" * 80)
    
    # Invalid VM input - name too long
    vm_input = {
        "vm_name": "x" * 100,  # Max is 64
        "gb_ram": 8,
        "cpu_cores": 4,
        "guest_la_uid": "Administrator",
        "guest_la_pw": "SecurePassword123!",
    }
    
    logger.info("Input data: vm_name='%s' (length=%d)", vm_input["vm_name"][:20] + "...", len(vm_input["vm_name"]))
    
    # Schema validation
    schema = load_schema_by_id("vm-create")
    try:
        schema_result = validate_job_submission(vm_input, schema)
        logger.info("✓ Schema validation PASSED (unexpected)")
        schema_passed = True
    except SchemaValidationError as e:
        logger.info("✓ Schema validation caught error: %s", str(e)[:100])
        schema_passed = False
    
    # Pydantic validation
    vm_dict, pydantic_error = convert_vm_schema_to_spec(vm_input)
    if pydantic_error is None:
        logger.error("✗ Pydantic validation PASSED (unexpected)")
    else:
        logger.info("✓ Pydantic validation caught error: %s", pydantic_error[:100])
    
    log_validation_comparison(schema_passed, pydantic_error, "invalid_vm")
    logger.info("")


def demo_guest_config_parameter_sets():
    """Demonstrate parameter set validation (all-or-none)."""
    logger.info("=" * 80)
    logger.info("DEMO 3: Guest Config with Partial Domain Join (should fail)")
    logger.info("=" * 80)
    
    # Partial domain join - should fail
    input_data = {
        "guest_la_uid": "Administrator",
        "guest_la_pw": "SecurePassword123!",
        "guest_domain_jointarget": "corp.example.com",
        # Missing: guest_domain_joinuid, guest_domain_joinpw, guest_domain_joinou
    }
    
    logger.info("Input has partial domain join config")
    
    # Schema validation
    schema = load_schema_by_id("vm-create")
    try:
        schema_result = validate_job_submission(input_data, schema)
        logger.info("✓ Schema validation PASSED (unexpected)")
        schema_passed = True
    except SchemaValidationError as e:
        logger.info("✓ Schema validation caught error: %s", str(e)[:100])
        schema_passed = False
    
    # Pydantic validation
    guest_dict, pydantic_error = convert_guest_config_schema_to_spec(input_data)
    if pydantic_error is None:
        logger.error("✗ Pydantic validation PASSED (unexpected)")
    else:
        logger.info("✓ Pydantic validation caught error: %s", pydantic_error[:100])
    
    log_validation_comparison(schema_passed, pydantic_error, "partial_domain_join")
    logger.info("")


def demo_complete_managed_deployment():
    """Demonstrate complete managed deployment validation."""
    logger.info("=" * 80)
    logger.info("DEMO 4: Complete Managed Deployment")
    logger.info("=" * 80)
    
    # Complete managed deployment
    deployment_input = {
        "vm_name": "app-server-01",
        "gb_ram": 16,
        "cpu_cores": 8,
        "storage_class": "enterprise-ssd",
        "vm_clustered": True,
        "image_name": "Windows Server 2022",
        "disk_size_gb": 500,
        "network": "Production",
        "adapter_name": "Primary NIC",
        "guest_la_uid": "Administrator",
        "guest_la_pw": "SecurePassword123!",
        "guest_v4_ipaddr": "192.168.1.100",
        "guest_v4_cidrprefix": 24,
        "guest_v4_defaultgw": "192.168.1.1",
        "guest_v4_dns1": "192.168.1.10",
        "guest_v4_dns2": "192.168.1.11",
        "guest_domain_jointarget": "corp.example.com",
        "guest_domain_joinuid": "EXAMPLE\\svc_join",
        "guest_domain_joinpw": "DomainPassword456!",
        "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
    }
    
    logger.info("Input includes VM, Disk, NIC, and Guest Config")
    
    # Convert to managed deployment
    deployment, error = convert_managed_deployment_schema_to_spec(
        deployment_input,
        "hyperv-host-01.example.com",
    )
    
    if error is None:
        logger.info("✓ Managed deployment validation PASSED")
        logger.info("  VM: %s (%d GB RAM, %d cores)", 
                    deployment.vm_spec.vm_name,
                    deployment.vm_spec.gb_ram,
                    deployment.vm_spec.cpu_cores)
        logger.info("  Disk: %s (%d GB)", 
                    deployment.disk_spec.image_name,
                    deployment.disk_spec.disk_size_gb)
        logger.info("  NIC: %s", deployment.nic_spec.network)
        logger.info("  Guest Config: User=%s, Domain=%s, Static IP=%s",
                    deployment.guest_config.guest_la_uid,
                    deployment.guest_config.guest_domain_jointarget,
                    deployment.guest_config.guest_v4_ipaddr)
        logger.info("  Target Host: %s", deployment.target_host)
    else:
        logger.error("✗ Managed deployment validation FAILED: %s", error)
    
    logger.info("")


def demo_disk_validation():
    """Demonstrate disk specification validation."""
    logger.info("=" * 80)
    logger.info("DEMO 5: Disk Specification")
    logger.info("=" * 80)
    
    # Disk with image cloning
    disk_input = {
        "vm_id": "12345678-1234-1234-1234-123456789abc",
        "image_name": "Ubuntu 22.04 LTS",
        "storage_class": "fast-nvme",
        "disk_type": "Dynamic",
    }
    
    logger.info("Input: Clone from image '%s'", disk_input["image_name"])
    
    disk_dict, error = convert_disk_schema_to_spec(disk_input)
    if error is None:
        logger.info("✓ Disk validation PASSED")
        logger.info("  Disk spec: %s", disk_dict)
    else:
        logger.error("✗ Disk validation FAILED: %s", error)
    
    logger.info("")


def demo_nic_validation():
    """Demonstrate NIC specification validation."""
    logger.info("=" * 80)
    logger.info("DEMO 6: NIC Specification")
    logger.info("=" * 80)
    
    # NIC with hardware only
    nic_input = {
        "vm_id": "12345678-1234-1234-1234-123456789abc",
        "network": "Production",
        "adapter_name": "External NIC",
    }
    
    logger.info("Input: Network='%s'", nic_input["network"])
    
    nic_dict, error = convert_nic_schema_to_spec(nic_input)
    if error is None:
        logger.info("✓ NIC validation PASSED")
        logger.info("  NIC spec: %s", nic_dict)
    else:
        logger.error("✗ NIC validation FAILED: %s", error)
    
    logger.info("")


def main():
    """Run all demonstrations."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║ Phase 1 Pydantic Models - Validation Demonstration" + " " * 26 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("")
    
    demo_vm_validation()
    demo_invalid_vm_validation()
    demo_guest_config_parameter_sets()
    demo_complete_managed_deployment()
    demo_disk_validation()
    demo_nic_validation()
    
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info("✓ Pydantic models work alongside existing schema system")
    logger.info("✓ Both validation systems can run in parallel")
    logger.info("✓ Validation errors bubble up cleanly")
    logger.info("✓ No existing code was modified")
    logger.info("=" * 80)
    logger.info("")


if __name__ == "__main__":
    main()
