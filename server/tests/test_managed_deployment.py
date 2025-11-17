"""Unit tests for managed deployment endpoint and schema composition."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

# Mock heavy dependencies before imports
import sys
sys.modules['psutil'] = MagicMock()
sys.modules['pypsrp'] = MagicMock()
sys.modules['pypsrp.exceptions'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.starlette_client'] = MagicMock()
sys.modules['cryptography'] = MagicMock()
sys.modules['cryptography.fernet'] = MagicMock()
sys.modules['krb5'] = MagicMock()
sys.modules['gssapi'] = MagicMock()
sys.modules['pyspnego'] = MagicMock()
sys.modules['ldap3'] = MagicMock()


class TestManagedDeploymentSchemaComposition:
    """Test that managed deployment correctly composes schemas."""
    
    def test_component_schemas_exist(self):
        """Verify all required component schemas exist."""
        from app.core.job_schema import load_schema_by_id
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        assert vm_schema is not None
        assert disk_schema is not None
        assert nic_schema is not None
        assert vm_schema.get("id") == "vm-create"
        assert disk_schema.get("id") == "disk-create"
        assert nic_schema.get("id") == "nic-create"
    
    def test_vm_initialize_schema_does_not_exist(self):
        """Verify that vm-initialize schema does not exist."""
        from app.core.job_schema import load_schema_by_id, SchemaValidationError
        
        with pytest.raises(SchemaValidationError, match="Schema file not found for ID: vm-initialize"):
            load_schema_by_id("vm-initialize")
    
    def test_guest_config_fields_in_vm_schema(self):
        """Verify that VM schema has guest_config fields marked correctly."""
        from app.core.job_schema import load_schema_by_id
        
        vm_schema = load_schema_by_id("vm-create")
        guest_fields = [f['id'] for f in vm_schema.get('fields', []) if f.get('guest_config', False)]
        
        # These are guest configuration fields that should be marked
        expected_guest_fields = [
            'guest_la_uid',
            'guest_la_pw',
            'guest_domain_jointarget',
            'guest_domain_joinuid',
            'guest_domain_joinpw',
            'guest_domain_joinou',
            'cnf_ansible_ssh_user',
            'cnf_ansible_ssh_key',
        ]
        
        for field in expected_guest_fields:
            assert field in guest_fields, f"Expected {field} to be marked as guest_config"
    
    def test_guest_config_fields_in_nic_schema(self):
        """Verify that NIC schema has guest_config fields marked correctly."""
        from app.core.job_schema import load_schema_by_id
        
        nic_schema = load_schema_by_id("nic-create")
        guest_fields = [f['id'] for f in nic_schema.get('fields', []) if f.get('guest_config', False)]
        
        # These are guest IP configuration fields that should be marked
        expected_guest_fields = [
            'guest_v4_ipaddr',
            'guest_v4_cidrprefix',
            'guest_v4_defaultgw',
            'guest_v4_dns1',
            'guest_v4_dns2',
            'guest_net_dnssuffix',
        ]
        
        for field in expected_guest_fields:
            assert field in guest_fields, f"Expected {field} to be marked as guest_config"
    
    def test_combined_schema_excludes_vm_id(self):
        """Verify that combined schema excludes vm_id from disk/nic schemas."""
        from app.core.job_schema import load_schema_by_id
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        # Simulate what routes.py does
        all_fields = {}
        for schema in [vm_schema, disk_schema, nic_schema]:
            for field in schema.get("fields", []):
                # Skip vm_id from disk/nic schemas
                if field.get("id") == "vm_id" and schema.get("id") in ["disk-create", "nic-create"]:
                    continue
                if field.get("id") not in all_fields:
                    all_fields[field["id"]] = field
        
        field_ids = list(all_fields.keys())
        
        # vm_id should NOT be in the combined schema
        assert 'vm_id' not in field_ids, "vm_id should be excluded from combined schema"
        
        # But other fields should be present
        assert 'vm_name' in field_ids
        assert 'disk_size_gb' in field_ids
        assert 'network' in field_ids
    
    def test_combined_schema_includes_parameter_sets(self):
        """Verify that combined schema includes parameter sets from all components."""
        from app.core.job_schema import load_schema_by_id
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        all_parameter_sets = []
        for schema in [vm_schema, disk_schema, nic_schema]:
            all_parameter_sets.extend(schema.get("parameter_sets", []) or [])
        
        # Should have parameter sets from VM (domain-join, ansible-config) and NIC (static-ip-config)
        assert len(all_parameter_sets) >= 3
        
        param_set_ids = [ps.get('id') for ps in all_parameter_sets]
        assert 'domain-join' in param_set_ids
        assert 'ansible-config' in param_set_ids
        assert 'static-ip-config' in param_set_ids
    
    def test_managed_deployment_validation_success(self):
        """Test that a valid managed deployment submission validates successfully."""
        from app.core.job_schema import load_schema_by_id, validate_job_submission
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        # Build combined schema
        all_fields = {}
        for schema in [vm_schema, disk_schema, nic_schema]:
            for field in schema.get("fields", []):
                if field.get("id") == "vm_id" and schema.get("id") in ["disk-create", "nic-create"]:
                    continue
                if field.get("id") not in all_fields:
                    all_fields[field["id"]] = field
        
        all_parameter_sets = []
        for schema in [vm_schema, disk_schema, nic_schema]:
            all_parameter_sets.extend(schema.get("parameter_sets", []) or [])
        
        combined_schema = {
            "version": vm_schema.get("version"),
            "fields": list(all_fields.values()),
            "parameter_sets": all_parameter_sets,
        }
        
        # Valid submission data
        values = {
            "vm_name": "test-vm-01",
            "image_name": "Windows Server 2022",
            "gb_ram": 8,
            "cpu_cores": 4,
            "disk_size_gb": 100,
            "network": "Production",
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecureP@ssw0rd123",
        }
        
        # Should validate without errors
        validated = validate_job_submission(values, combined_schema)
        
        assert validated["vm_name"] == "test-vm-01"
        assert validated["image_name"] == "Windows Server 2022"
        assert validated["gb_ram"] == 8
        assert validated["cpu_cores"] == 4
        assert validated["disk_size_gb"] == 100
        assert validated["network"] == "Production"
        assert validated["guest_la_uid"] == "Administrator"
        assert validated["guest_la_pw"] == "SecureP@ssw0rd123"
    
    def test_managed_deployment_validation_with_domain_join(self):
        """Test validation with domain join parameter set."""
        from app.core.job_schema import load_schema_by_id, validate_job_submission
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        # Build combined schema
        all_fields = {}
        for schema in [vm_schema, disk_schema, nic_schema]:
            for field in schema.get("fields", []):
                if field.get("id") == "vm_id" and schema.get("id") in ["disk-create", "nic-create"]:
                    continue
                if field.get("id") not in all_fields:
                    all_fields[field["id"]] = field
        
        all_parameter_sets = []
        for schema in [vm_schema, disk_schema, nic_schema]:
            all_parameter_sets.extend(schema.get("parameter_sets", []) or [])
        
        combined_schema = {
            "version": vm_schema.get("version"),
            "fields": list(all_fields.values()),
            "parameter_sets": all_parameter_sets,
        }
        
        # Valid submission with domain join (all fields required for domain-join parameter set)
        values = {
            "vm_name": "test-vm-01",
            "image_name": "Windows Server 2022",
            "gb_ram": 8,
            "cpu_cores": 4,
            "disk_size_gb": 100,
            "network": "Production",
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecureP@ssw0rd123",
            "guest_domain_jointarget": "corp.example.com",
            "guest_domain_joinuid": "EXAMPLE\\svc_join",
            "guest_domain_joinpw": "JoinP@ss123",
            "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
        }
        
        # Should validate without errors
        validated = validate_job_submission(values, combined_schema)
        
        assert validated["guest_domain_jointarget"] == "corp.example.com"
        assert validated["guest_domain_joinuid"] == "EXAMPLE\\svc_join"
    
    def test_managed_deployment_validation_with_static_ip(self):
        """Test validation with static IP parameter set."""
        from app.core.job_schema import load_schema_by_id, validate_job_submission
        
        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")
        
        # Build combined schema
        all_fields = {}
        for schema in [vm_schema, disk_schema, nic_schema]:
            for field in schema.get("fields", []):
                if field.get("id") == "vm_id" and schema.get("id") in ["disk-create", "nic-create"]:
                    continue
                if field.get("id") not in all_fields:
                    all_fields[field["id"]] = field
        
        all_parameter_sets = []
        for schema in [vm_schema, disk_schema, nic_schema]:
            all_parameter_sets.extend(schema.get("parameter_sets", []) or [])
        
        combined_schema = {
            "version": vm_schema.get("version"),
            "fields": list(all_fields.values()),
            "parameter_sets": all_parameter_sets,
        }
        
        # Valid submission with static IP configuration
        values = {
            "vm_name": "test-vm-01",
            "image_name": "Windows Server 2022",
            "gb_ram": 8,
            "cpu_cores": 4,
            "disk_size_gb": 100,
            "network": "Production",
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecureP@ssw0rd123",
            "guest_v4_ipaddr": "192.0.2.50",
            "guest_v4_cidrprefix": 24,
            "guest_v4_defaultgw": "192.0.2.1",
            "guest_v4_dns1": "192.0.2.53",
        }
        
        # Should validate without errors
        validated = validate_job_submission(values, combined_schema)
        
        assert validated["guest_v4_ipaddr"] == "192.0.2.50"
        assert validated["guest_v4_cidrprefix"] == 24


class TestJobServiceImport:
    """Test that job_service imports are correct."""
    
    def test_import_path_is_correct(self):
        """Verify that load_schema_by_id can be imported with correct path."""
        # The import should work from within a service module context
        from app.core.job_schema import load_schema_by_id
        
        # Verify it works
        schema = load_schema_by_id("vm-create")
        assert schema is not None
        assert schema.get("id") == "vm-create"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
