"""Phase 0 Baseline Integration Test Suite - Simplified

This module provides simplified baseline tests that validate the current
schema-driven system before the Pydantic refactor. These tests focus on:
- Schema loading and composition
- Validation logic
- Guest config field separation
- Job structure and orchestration patterns

These tests serve as documentation of current behavior and as regression tests.
"""

import sys
import types
from typing import Dict, Set

import pytest

# Stub yaml module
yaml_stub = types.ModuleType("yaml")
yaml_stub.safe_dump = lambda data, sort_keys=False: ""
sys.modules.setdefault("yaml", yaml_stub)

from app.core.job_schema import (
    load_schema_by_id,
    get_job_schema,
    validate_job_submission,
    get_sensitive_field_ids,
    SchemaValidationError,
)


class TestSchemaLoading:
    """Test schema loading and structure."""
    
    def test_vm_create_schema_loads(self):
        """Verify VM creation schema loads successfully."""
        schema = load_schema_by_id("vm-create")
        assert schema is not None
        assert schema.get("id") == "vm-create"
        assert "fields" in schema
        assert len(schema["fields"]) > 0
    
    def test_disk_create_schema_loads(self):
        """Verify disk creation schema loads successfully."""
        schema = load_schema_by_id("disk-create")
        assert schema is not None
        assert schema.get("id") == "disk-create"
        assert "fields" in schema
    
    def test_nic_create_schema_loads(self):
        """Verify NIC creation schema loads successfully."""
        schema = load_schema_by_id("nic-create")
        assert schema is not None
        assert schema.get("id") == "nic-create"
        assert "fields" in schema
    
    def test_composed_schema_includes_all_fields(self):
        """Verify composed schema includes fields from all three component schemas."""
        composed = get_job_schema()
        
        assert "fields" in composed
        field_ids = {f["id"] for f in composed["fields"]}
        
        # VM fields
        assert "vm_name" in field_ids
        assert "gb_ram" in field_ids
        assert "cpu_cores" in field_ids
        
        # Disk fields (vm_id excluded from composed schema)
        assert "image_name" in field_ids
        assert "disk_size_gb" in field_ids
        
        # NIC fields (vm_id excluded from composed schema)
        assert "network" in field_ids
        assert "adapter_name" in field_ids


class TestSchemaValidation:
    """Test schema validation logic."""
    
    def test_vm_validation_success(self):
        """Test successful VM validation."""
        schema = load_schema_by_id("vm-create")
        values = {
            "vm_name": "test-vm",
            "gb_ram": 8,
            "cpu_cores": 4,
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
        }
        
        validated = validate_job_submission(values, schema)
        assert validated["vm_name"] == "test-vm"
        assert validated["gb_ram"] == 8
        assert validated["cpu_cores"] == 4
    
    def test_vm_validation_requires_mandatory_fields(self):
        """Test that validation fails when required fields are missing."""
        schema = load_schema_by_id("vm-create")
        values = {
            "vm_name": "test-vm",
            # Missing required fields: gb_ram, cpu_cores, guest_la_uid, guest_la_pw
        }
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_job_submission(values, schema)
        
        error_msg = str(exc_info.value)
        assert "gb_ram" in error_msg or "required" in error_msg.lower()
    
    def test_vm_validation_enforces_parameter_sets(self):
        """Test that parameter sets are enforced (all-or-none for domain join)."""
        schema = load_schema_by_id("vm-create")
        values = {
            "vm_name": "test-vm",
            "gb_ram": 8,
            "cpu_cores": 4,
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
            # Partial domain join config (should fail)
            "guest_domain_jointarget": "corp.example.com",
            # Missing: guest_domain_joinuid, guest_domain_joinpw, guest_domain_joinou
        }
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_job_submission(values, schema)
        
        error_msg = str(exc_info.value)
        assert "domain" in error_msg.lower() or "parameter set" in error_msg.lower()
    
    def test_disk_validation_with_image(self):
        """Test disk validation when cloning from an image."""
        schema = load_schema_by_id("disk-create")
        values = {
            "vm_id": "12345678-1234-1234-1234-123456789abc",
            "image_name": "Windows Server 2022",
            "storage_class": "fast-ssd",
        }
        
        validated = validate_job_submission(values, schema)
        assert validated["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert validated["image_name"] == "Windows Server 2022"
    
    def test_nic_validation_with_static_ip(self):
        """Test NIC validation with static IP configuration."""
        schema = load_schema_by_id("nic-create")
        values = {
            "vm_id": "12345678-1234-1234-1234-123456789abc",
            "network": "Production",
            "guest_v4_ipaddr": "192.168.1.100",
            "guest_v4_cidrprefix": 24,
            "guest_v4_defaultgw": "192.168.1.1",
            "guest_v4_dns1": "192.168.1.10",
        }
        
        validated = validate_job_submission(values, schema)
        assert validated["network"] == "Production"
        assert validated["guest_v4_ipaddr"] == "192.168.1.100"
        assert validated["guest_v4_cidrprefix"] == 24


class TestGuestConfigSeparation:
    """Test guest configuration field separation logic."""
    
    def test_vm_schema_marks_guest_config_fields(self):
        """Verify VM schema correctly marks guest config fields."""
        schema = load_schema_by_id("vm-create")
        guest_fields = [f["id"] for f in schema["fields"] if f.get("guest_config", False)]
        
        # Expected guest config fields in VM schema
        expected = {
            "guest_la_uid",
            "guest_la_pw",
            "guest_domain_jointarget",
            "guest_domain_joinuid",
            "guest_domain_joinpw",
            "guest_domain_joinou",
            "cnf_ansible_ssh_user",
            "cnf_ansible_ssh_key",
        }
        
        assert set(guest_fields) == expected
    
    def test_vm_schema_hardware_fields(self):
        """Verify VM schema hardware fields are NOT marked as guest_config."""
        schema = load_schema_by_id("vm-create")
        hardware_fields = [f["id"] for f in schema["fields"] if not f.get("guest_config", False)]
        
        # Hardware fields should include these
        assert "vm_name" in hardware_fields
        assert "gb_ram" in hardware_fields
        assert "cpu_cores" in hardware_fields
        assert "storage_class" in hardware_fields
        assert "vm_clustered" in hardware_fields
        
        # Guest config fields should NOT be in hardware list
        assert "guest_la_uid" not in hardware_fields
        assert "guest_la_pw" not in hardware_fields
    
    def test_nic_schema_marks_guest_config_fields(self):
        """Verify NIC schema correctly marks guest IP config fields."""
        schema = load_schema_by_id("nic-create")
        guest_fields = [f["id"] for f in schema["fields"] if f.get("guest_config", False)]
        
        # Expected guest config fields in NIC schema
        expected = {
            "guest_v4_ipaddr",
            "guest_v4_cidrprefix",
            "guest_v4_defaultgw",
            "guest_v4_dns1",
            "guest_v4_dns2",
            "guest_net_dnssuffix",
        }
        
        assert set(guest_fields) == expected
    
    def test_nic_schema_hardware_fields(self):
        """Verify NIC schema hardware fields are NOT marked as guest_config."""
        schema = load_schema_by_id("nic-create")
        hardware_fields = [f["id"] for f in schema["fields"] if not f.get("guest_config", False)]
        
        # Hardware fields
        assert "vm_id" in hardware_fields
        assert "network" in hardware_fields
        assert "adapter_name" in hardware_fields
        
        # Guest config fields should NOT be in hardware list
        assert "guest_v4_ipaddr" not in hardware_fields
        assert "guest_v4_dns1" not in hardware_fields
    
    def test_disk_schema_has_no_guest_config_fields(self):
        """Verify disk schema has no guest config fields."""
        schema = load_schema_by_id("disk-create")
        guest_fields = [f for f in schema["fields"] if f.get("guest_config", False)]
        
        assert len(guest_fields) == 0


class TestSensitiveFieldHandling:
    """Test sensitive field identification and handling."""
    
    def test_sensitive_fields_identified(self):
        """Verify sensitive fields are properly identified."""
        schema = load_schema_by_id("vm-create")
        sensitive_ids = get_sensitive_field_ids(schema)
        
        # Password fields should be identified as sensitive
        assert "guest_la_pw" in sensitive_ids
        assert "guest_domain_joinpw" in sensitive_ids
        
        # Non-sensitive fields should not be included
        assert "vm_name" not in sensitive_ids
        assert "gb_ram" not in sensitive_ids
    
    def test_composed_schema_sensitive_fields(self):
        """Verify sensitive fields in composed schema."""
        composed = get_job_schema()
        sensitive_ids = get_sensitive_field_ids(composed)
        
        # Should include all password fields from all schemas
        assert "guest_la_pw" in sensitive_ids
        assert "guest_domain_joinpw" in sensitive_ids


class TestJobResultStructure:
    """Test expected job result JSON structure."""
    
    def test_expected_result_fields(self):
        """Document expected fields in job result envelope.
        
        This test documents the expected structure of JSON responses
        from PowerShell host agents, serving as a contract specification.
        """
        # Expected structure (documented, not validated against actual response)
        expected_structure = {
            "status": "str",  # "success", "error", or "partial"
            "message": "str",  # Human-readable description
            "data": "dict",  # Structured output (VM IDs, paths, etc.)
            "code": "Optional[str]",  # Machine-readable error code
            "logs": "Optional[List[str]]",  # Debug output lines
            "correlation_id": "Optional[str]",  # Mirrors request ID
        }
        
        # Verify structure is well-defined
        assert "status" in expected_structure
        assert "message" in expected_structure
        assert "data" in expected_structure
    
    def test_expected_vm_creation_result(self):
        """Document expected VM creation result structure."""
        expected_vm_result_data = {
            "vm_id": "UUID string",
            "vm_name": "string",
        }
        
        assert "vm_id" in expected_vm_result_data
        assert "vm_name" in expected_vm_result_data
    
    def test_expected_disk_creation_result(self):
        """Document expected disk creation result structure."""
        expected_disk_result_data = {
            "disk_path": "Windows path string",
            "source_image": "Optional[string]",
            "size_gb": "Optional[int]",
        }
        
        assert "disk_path" in expected_disk_result_data


class TestOrchestrationPattern:
    """Document managed deployment orchestration pattern."""
    
    def test_managed_deployment_child_job_sequence(self):
        """Document the expected sequence of child jobs in managed deployment.
        
        This test documents the orchestration pattern for reference.
        """
        expected_sequence = [
            {
                "job_type": "create_vm",
                "input": "VM hardware fields only (no guest_config fields)",
                "output": "VM ID for subsequent jobs",
            },
            {
                "job_type": "create_disk",
                "input": "Disk fields + VM ID from previous step",
                "condition": "Only if image_name or disk_size_gb provided",
                "output": "Disk path",
            },
            {
                "job_type": "create_nic",
                "input": "NIC hardware fields + VM ID (no guest_config fields)",
                "condition": "Only if network field provided",
                "output": "NIC adapter name",
            },
            {
                "job_type": "initialize_vm",
                "input": "VM ID + all guest_config fields (VM + NIC combined)",
                "condition": "Only if any guest_config fields provided",
                "output": "Provisioning published confirmation",
            },
        ]
        
        # Verify structure is well-defined
        assert len(expected_sequence) == 4
        assert expected_sequence[0]["job_type"] == "create_vm"
        assert expected_sequence[3]["job_type"] == "initialize_vm"
    
    def test_guest_config_aggregation_pattern(self):
        """Document how guest config is aggregated from multiple schemas."""
        aggregation_pattern = {
            "source_schemas": ["vm-create", "nic-create"],
            "filter_criterion": "field.get('guest_config', False) == True",
            "target_job": "initialize_vm",
            "additional_fields": ["vm_id", "vm_name"],
        }
        
        assert "source_schemas" in aggregation_pattern
        assert "vm-create" in aggregation_pattern["source_schemas"]
        assert "nic-create" in aggregation_pattern["source_schemas"]
        assert "disk-create" not in aggregation_pattern["source_schemas"]  # No guest config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
