"""Tests: Guest Configuration Generator

This test suite validates guest configuration generation from flat 
ManagedDeploymentRequest models for VM provisioning operations.

Tests cover:
1. Minimal guest config (local admin only)
2. Guest config with domain join
3. Guest config with static IP configuration
4. Guest config with Ansible configuration
5. Combined scenarios (domain join + static IP, etc.)
6. Edge cases and validation

The generator creates guest configuration dictionaries that are encrypted and
transmitted to guest VMs via Hyper-V KVP for OS-level customization.
"""
import pytest
from pydantic import ValidationError

from app.core.pydantic_models import ManagedDeploymentRequest
from app.core.guest_config_generator import generate_guest_config


def create_request(**kwargs) -> ManagedDeploymentRequest:
    """Helper to create a ManagedDeploymentRequest with defaults."""
    defaults = {
        "target_host": "hyperv-01.example.com",
        "vm_name": "test-vm",
        "gb_ram": 4,
        "cpu_cores": 2,
        "network": "Production",
        "guest_la_uid": "Administrator",
        "guest_la_pw": "SecurePass123!",
    }
    defaults.update(kwargs)
    return ManagedDeploymentRequest(**defaults)


class TestMinimalGuestConfig:
    """Test minimal guest configuration (local admin only)."""
    
    def test_minimal_guest_config(self):
        """Test minimal guest config with only local admin credentials."""
        request = create_request()
        
        config = generate_guest_config(request)
        
        # Should contain exactly the local admin fields
        assert "guest_la_uid" in config
        assert "guest_la_pw" in config
        assert config["guest_la_uid"] == "Administrator"
        assert config["guest_la_pw"] == "SecurePass123!"
        
        # Should not contain any optional fields
        assert "guest_domain_join_target" not in config
        assert "guest_v4_ip_addr" not in config
        assert "cnf_ansible_ssh_user" not in config
    
    def test_minimal_guest_config_with_different_credentials(self):
        """Test that different credentials are correctly included."""
        request = create_request(
            vm_name="db-01",
            gb_ram=8,
            cpu_cores=4,
            guest_la_uid="LocalAdmin",
            guest_la_pw="MyP@ssw0rd!",
        )
        
        config = generate_guest_config(request)
        
        assert config["guest_la_uid"] == "LocalAdmin"
        assert config["guest_la_pw"] == "MyP@ssw0rd!"


class TestDomainJoinConfiguration:
    """Test guest configuration with domain join."""
    
    def test_guest_config_with_domain_join(self):
        """Test guest config with complete domain join configuration."""
        request = create_request(
            vm_name="web-01",
            guest_domain_join_target="corp.example.com",
            guest_domain_join_uid="EXAMPLE\\svc_join",
            guest_domain_join_pw="DomainPass456!",
            guest_domain_join_ou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        config = generate_guest_config(request)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        assert config["guest_la_pw"] == "SecurePass123!"
        
        # Should contain all domain join fields
        assert config["guest_domain_join_target"] == "corp.example.com"
        assert config["guest_domain_join_uid"] == "EXAMPLE\\svc_join"
        assert config["guest_domain_join_pw"] == "DomainPass456!"
        assert config["guest_domain_join_ou"] == "OU=Servers,DC=corp,DC=example,DC=com"
    
    def test_domain_join_with_different_domain(self):
        """Test domain join with different domain values."""
        request = create_request(
            vm_name="sql-01",
            gb_ram=16,
            cpu_cores=8,
            guest_domain_join_target="internal.company.net",
            guest_domain_join_uid="COMPANY\\domain_admin",
            guest_domain_join_pw="AnotherPass789!",
            guest_domain_join_ou="OU=Database,OU=Production,DC=internal,DC=company,DC=net",
        )
        
        config = generate_guest_config(request)
        
        assert config["guest_domain_join_target"] == "internal.company.net"
        assert config["guest_domain_join_uid"] == "COMPANY\\domain_admin"
        assert config["guest_domain_join_ou"] == "OU=Database,OU=Production,DC=internal,DC=company,DC=net"


class TestStaticIPConfiguration:
    """Test guest configuration with static IP."""
    
    def test_guest_config_with_static_ip(self):
        """Test guest config with static IP configuration."""
        request = create_request(
            vm_name="web-01",
            guest_v4_ip_addr="192.168.1.100",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        config = generate_guest_config(request)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        
        # Should contain all required static IP fields
        assert config["guest_v4_ip_addr"] == "192.168.1.100"
        assert config["guest_v4_cidr_prefix"] == 24
        assert config["guest_v4_default_gw"] == "192.168.1.1"
        assert config["guest_v4_dns1"] == "192.168.1.10"
        
        # Optional fields should not be present if not provided
        assert "guest_v4_dns2" not in config
        assert "guest_net_dns_suffix" not in config
    
    def test_guest_config_with_static_ip_and_optional_fields(self):
        """Test static IP config with optional DNS2 and suffix."""
        request = create_request(
            vm_name="app-01",
            gb_ram=8,
            cpu_cores=4,
            guest_v4_ip_addr="10.0.0.50",
            guest_v4_cidr_prefix=16,
            guest_v4_default_gw="10.0.0.1",
            guest_v4_dns1="10.0.0.10",
            guest_v4_dns2="10.0.0.11",
            guest_net_dns_suffix="corp.example.com",
        )
        
        config = generate_guest_config(request)
        
        # Should contain required IP fields
        assert config["guest_v4_ip_addr"] == "10.0.0.50"
        assert config["guest_v4_cidr_prefix"] == 16
        
        # Should contain optional fields
        assert config["guest_v4_dns2"] == "10.0.0.11"
        assert config["guest_net_dns_suffix"] == "corp.example.com"
    
    def test_static_ip_with_different_network_ranges(self):
        """Test static IP with various network configurations."""
        request = create_request(
            vm_name="test-vm",
            gb_ram=2,
            cpu_cores=1,
            guest_v4_ip_addr="172.16.50.200",
            guest_v4_cidr_prefix=22,
            guest_v4_default_gw="172.16.48.1",
            guest_v4_dns1="8.8.8.8",
        )
        
        config = generate_guest_config(request)
        
        assert config["guest_v4_ip_addr"] == "172.16.50.200"
        assert config["guest_v4_cidr_prefix"] == 22


class TestAnsibleConfiguration:
    """Test guest configuration with Ansible."""
    
    def test_guest_config_with_ansible(self):
        """Test guest config with Ansible SSH configuration."""
        request = create_request(
            vm_name="web-01",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(request)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        
        # Should contain Ansible fields
        assert config["cnf_ansible_ssh_user"] == "ansible"
        assert config["cnf_ansible_ssh_key"] == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample"
    
    def test_ansible_with_different_credentials(self):
        """Test Ansible config with different user and key."""
        request = create_request(
            vm_name="app-01",
            cnf_ansible_ssh_user="automation",
            cnf_ansible_ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAAExample",
        )
        
        config = generate_guest_config(request)
        
        assert config["cnf_ansible_ssh_user"] == "automation"
        assert "ssh-rsa" in config["cnf_ansible_ssh_key"]


class TestCombinedConfigurations:
    """Test combined guest configurations."""
    
    def test_domain_join_and_static_ip(self):
        """Test guest config with both domain join and static IP."""
        request = create_request(
            vm_name="web-01",
            gb_ram=8,
            cpu_cores=4,
            guest_domain_join_target="corp.example.com",
            guest_domain_join_uid="EXAMPLE\\svc_join",
            guest_domain_join_pw="DomainPass456!",
            guest_domain_join_ou="OU=Servers,DC=corp,DC=example,DC=com",
            guest_v4_ip_addr="192.168.1.100",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        config = generate_guest_config(request)
        
        # Should have local admin
        assert "guest_la_uid" in config
        
        # Should have domain join
        assert "guest_domain_join_target" in config
        assert config["guest_domain_join_target"] == "corp.example.com"
        
        # Should have static IP
        assert "guest_v4_ip_addr" in config
        assert config["guest_v4_ip_addr"] == "192.168.1.100"
    
    def test_all_configurations_combined(self):
        """Test guest config with domain join, static IP, and Ansible."""
        request = create_request(
            vm_name="app-01",
            gb_ram=16,
            cpu_cores=8,
            guest_domain_join_target="internal.company.net",
            guest_domain_join_uid="COMPANY\\svc_join",
            guest_domain_join_pw="DomainPass456!",
            guest_domain_join_ou="OU=Servers,DC=internal,DC=company,DC=net",
            guest_v4_ip_addr="10.0.0.50",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="10.0.0.1",
            guest_v4_dns1="10.0.0.10",
            guest_v4_dns2="10.0.0.11",
            guest_net_dns_suffix="internal.company.net",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(request)
        
        # Should have all configuration sections
        assert "guest_la_uid" in config
        assert "guest_domain_join_target" in config
        assert "guest_v4_ip_addr" in config
        assert "cnf_ansible_ssh_user" in config
        
        # Verify all keys are present
        expected_keys = {
            "guest_la_uid",
            "guest_la_pw",
            "guest_domain_join_target",
            "guest_domain_join_uid",
            "guest_domain_join_pw",
            "guest_domain_join_ou",
            "guest_v4_ip_addr",
            "guest_v4_cidr_prefix",
            "guest_v4_default_gw",
            "guest_v4_dns1",
            "guest_v4_dns2",
            "guest_net_dns_suffix",
            "cnf_ansible_ssh_user",
            "cnf_ansible_ssh_key",
        }
        assert set(config.keys()) == expected_keys
    
    def test_ansible_and_static_ip(self):
        """Test Ansible with static IP (no domain join)."""
        request = create_request(
            vm_name="linux-01",
            guest_v4_ip_addr="192.168.2.50",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="192.168.2.1",
            guest_v4_dns1="192.168.2.10",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(request)
        
        # Should have static IP
        assert config["guest_v4_ip_addr"] == "192.168.2.50"
        
        # Should have Ansible
        assert config["cnf_ansible_ssh_user"] == "ansible"
        
        # Should NOT have domain join
        assert "guest_domain_join_target" not in config


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_empty_optional_strings_not_included(self):
        """Test that empty optional strings are not included."""
        request = create_request(
            guest_v4_ip_addr="192.168.1.100",
            guest_v4_cidr_prefix=24,
            guest_v4_default_gw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
            # guest_v4_dns2 is None
            # guest_net_dns_suffix is None
        )
        
        config = generate_guest_config(request)
        
        # Optional fields should not be included if None
        assert "guest_v4_dns2" not in config
        assert "guest_net_dns_suffix" not in config
    
    def test_config_dict_is_flat(self):
        """Test that generated config is a flat dictionary."""
        request = create_request()
        
        config = generate_guest_config(request)
        
        # All values should be simple types, not nested dicts
        for value in config.values():
            assert not isinstance(value, dict)
            assert not isinstance(value, list)
    
    def test_multiple_requests_with_same_guest_config(self):
        """Test generating config for multiple requests."""
        requests = [
            create_request(vm_name=f"web-{i:02d}")
            for i in range(1, 4)
        ]
        
        configs = [generate_guest_config(req) for req in requests]
        
        # All should have the same guest config (since same creds)
        for config in configs:
            assert config["guest_la_uid"] == "Administrator"
            assert config["guest_la_pw"] == "SecurePass123!"
    
    def test_generator_is_pure_function(self):
        """Test that generator doesn't mutate inputs."""
        request = create_request()
        
        # Store original values
        original_vm_name = request.vm_name
        original_uid = request.guest_la_uid
        
        # Generate config
        config = generate_guest_config(request)
        
        # Inputs should be unchanged
        assert request.vm_name == original_vm_name
        assert request.guest_la_uid == original_uid
        
        # Modifying config should not affect inputs
        config["guest_la_uid"] = "ModifiedUser"
        assert request.guest_la_uid == original_uid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
