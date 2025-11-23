"""Tests: Guest Configuration Generator

This test suite validates the new guest config generation logic that
replaces the schema-based auto-composition approach.

Tests cover:
1. Minimal guest config (local admin only)
2. Guest config with domain join
3. Guest config with static IP configuration
4. Guest config with Ansible configuration
5. Combined scenarios (domain join + static IP, etc.)
6. Edge cases and validation

Note: These tests validate the new generator in isolation.
The generator is NOT yet used in production flows - that happens in Phase 6.
"""
import pytest
from pydantic import ValidationError

from app.core.pydantic_models import (
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
)
from app.core.guest_config_generator import (
    generate_guest_config,
    generate_guest_config_from_dicts,
)


class TestMinimalGuestConfig:
    """Test minimal guest configuration (local admin only)."""
    
    def test_no_guest_config_returns_empty_dict(self):
        """Test that no guest config spec returns empty dict."""
        vm = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        
        config = generate_guest_config(vm)
        
        assert config == {}
    
    def test_minimal_guest_config(self):
        """Test minimal guest config with only local admin credentials."""
        vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should contain exactly the local admin fields
        assert "guest_la_uid" in config
        assert "guest_la_pw" in config
        assert config["guest_la_uid"] == "Administrator"
        assert config["guest_la_pw"] == "SecurePass123!"
        
        # Should not contain any optional fields
        assert "guest_domain_jointarget" not in config
        assert "guest_v4_ipaddr" not in config
        assert "cnf_ansible_ssh_user" not in config
    
    def test_minimal_guest_config_with_different_credentials(self):
        """Test that different credentials are correctly included."""
        vm = VmSpec(vm_name="db-01", gb_ram=8, cpu_cores=4)
        guest = GuestConfigSpec(
            guest_la_uid="LocalAdmin",
            guest_la_pw="MyP@ssw0rd!",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        assert config["guest_la_uid"] == "LocalAdmin"
        assert config["guest_la_pw"] == "MyP@ssw0rd!"


class TestDomainJoinConfiguration:
    """Test guest configuration with domain join."""
    
    def test_guest_config_with_domain_join(self):
        """Test guest config with complete domain join configuration."""
        vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="corp.example.com",
            guest_domain_joinuid="EXAMPLE\\svc_join",
            guest_domain_joinpw="DomainPass456!",
            guest_domain_joinou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        assert config["guest_la_pw"] == "SecurePass123!"
        
        # Should contain all domain join fields
        assert config["guest_domain_jointarget"] == "corp.example.com"
        assert config["guest_domain_joinuid"] == "EXAMPLE\\svc_join"
        assert config["guest_domain_joinpw"] == "DomainPass456!"
        assert config["guest_domain_joinou"] == "OU=Servers,DC=corp,DC=example,DC=com"
    
    def test_domain_join_with_different_domain(self):
        """Test domain join with different domain values."""
        vm = VmSpec(vm_name="sql-01", gb_ram=16, cpu_cores=8)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="internal.company.net",
            guest_domain_joinuid="COMPANY\\domain_admin",
            guest_domain_joinpw="AnotherPass789!",
            guest_domain_joinou="OU=Database,OU=Production,DC=internal,DC=company,DC=net",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        assert config["guest_domain_jointarget"] == "internal.company.net"
        assert config["guest_domain_joinuid"] == "COMPANY\\domain_admin"
        assert config["guest_domain_joinou"] == "OU=Database,OU=Production,DC=internal,DC=company,DC=net"


class TestStaticIPConfiguration:
    """Test guest configuration with static IP."""
    
    def test_guest_config_with_static_ip(self):
        """Test guest config with static IP configuration."""
        vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        nic = NicSpec(network="Production")
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="192.168.1.100",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        config = generate_guest_config(vm, nic, guest_config_spec=guest)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        
        # Should contain all required static IP fields
        assert config["guest_v4_ipaddr"] == "192.168.1.100"
        assert config["guest_v4_cidrprefix"] == 24
        assert config["guest_v4_defaultgw"] == "192.168.1.1"
        assert config["guest_v4_dns1"] == "192.168.1.10"
        
        # Optional fields should not be present if not provided
        assert "guest_v4_dns2" not in config
        assert "guest_net_dnssuffix" not in config
    
    def test_guest_config_with_static_ip_and_optional_fields(self):
        """Test static IP config with optional DNS2 and suffix."""
        vm = VmSpec(vm_name="app-01", gb_ram=8, cpu_cores=4)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="10.0.0.50",
            guest_v4_cidrprefix=16,
            guest_v4_defaultgw="10.0.0.1",
            guest_v4_dns1="10.0.0.10",
            guest_v4_dns2="10.0.0.11",
            guest_net_dnssuffix="corp.example.com",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should contain required IP fields
        assert config["guest_v4_ipaddr"] == "10.0.0.50"
        assert config["guest_v4_cidrprefix"] == 16
        
        # Should contain optional fields
        assert config["guest_v4_dns2"] == "10.0.0.11"
        assert config["guest_net_dnssuffix"] == "corp.example.com"
    
    def test_static_ip_with_different_network_ranges(self):
        """Test static IP with various network configurations."""
        vm = VmSpec(vm_name="test-vm", gb_ram=2, cpu_cores=1)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="172.16.50.200",
            guest_v4_cidrprefix=22,
            guest_v4_defaultgw="172.16.48.1",
            guest_v4_dns1="8.8.8.8",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        assert config["guest_v4_ipaddr"] == "172.16.50.200"
        assert config["guest_v4_cidrprefix"] == 22


class TestAnsibleConfiguration:
    """Test guest configuration with Ansible."""
    
    def test_guest_config_with_ansible(self):
        """Test guest config with Ansible SSH configuration."""
        vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should contain local admin credentials
        assert config["guest_la_uid"] == "Administrator"
        
        # Should contain Ansible fields
        assert config["cnf_ansible_ssh_user"] == "ansible"
        assert config["cnf_ansible_ssh_key"] == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample"
    
    def test_ansible_with_different_credentials(self):
        """Test Ansible config with different user and key."""
        vm = VmSpec(vm_name="app-01", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            cnf_ansible_ssh_user="automation",
            cnf_ansible_ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAAExample",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        assert config["cnf_ansible_ssh_user"] == "automation"
        assert "ssh-rsa" in config["cnf_ansible_ssh_key"]


class TestCombinedConfigurations:
    """Test combined guest configurations."""
    
    def test_domain_join_and_static_ip(self):
        """Test guest config with both domain join and static IP."""
        vm = VmSpec(vm_name="web-01", gb_ram=8, cpu_cores=4)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="corp.example.com",
            guest_domain_joinuid="EXAMPLE\\svc_join",
            guest_domain_joinpw="DomainPass456!",
            guest_domain_joinou="OU=Servers,DC=corp,DC=example,DC=com",
            guest_v4_ipaddr="192.168.1.100",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should have local admin
        assert "guest_la_uid" in config
        
        # Should have domain join
        assert "guest_domain_jointarget" in config
        assert config["guest_domain_jointarget"] == "corp.example.com"
        
        # Should have static IP
        assert "guest_v4_ipaddr" in config
        assert config["guest_v4_ipaddr"] == "192.168.1.100"
    
    def test_all_configurations_combined(self):
        """Test guest config with domain join, static IP, and Ansible."""
        vm = VmSpec(vm_name="app-01", gb_ram=16, cpu_cores=8)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="internal.company.net",
            guest_domain_joinuid="COMPANY\\svc_join",
            guest_domain_joinpw="DomainPass456!",
            guest_domain_joinou="OU=Servers,DC=internal,DC=company,DC=net",
            guest_v4_ipaddr="10.0.0.50",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="10.0.0.1",
            guest_v4_dns1="10.0.0.10",
            guest_v4_dns2="10.0.0.11",
            guest_net_dnssuffix="internal.company.net",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should have all configuration sections
        assert "guest_la_uid" in config
        assert "guest_domain_jointarget" in config
        assert "guest_v4_ipaddr" in config
        assert "cnf_ansible_ssh_user" in config
        
        # Verify all keys are present
        expected_keys = {
            "guest_la_uid",
            "guest_la_pw",
            "guest_domain_jointarget",
            "guest_domain_joinuid",
            "guest_domain_joinpw",
            "guest_domain_joinou",
            "guest_v4_ipaddr",
            "guest_v4_cidrprefix",
            "guest_v4_defaultgw",
            "guest_v4_dns1",
            "guest_v4_dns2",
            "guest_net_dnssuffix",
            "cnf_ansible_ssh_user",
            "cnf_ansible_ssh_key",
        }
        assert set(config.keys()) == expected_keys
    
    def test_ansible_and_static_ip(self):
        """Test Ansible with static IP (no domain join)."""
        vm = VmSpec(vm_name="linux-01", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="192.168.2.50",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.2.1",
            guest_v4_dns1="192.168.2.10",
            cnf_ansible_ssh_user="ansible",
            cnf_ansible_ssh_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Should have static IP
        assert config["guest_v4_ipaddr"] == "192.168.2.50"
        
        # Should have Ansible
        assert config["cnf_ansible_ssh_user"] == "ansible"
        
        # Should NOT have domain join
        assert "guest_domain_jointarget" not in config


class TestGeneratorWithAllSpecs:
    """Test generator with different combinations of spec objects."""
    
    def test_with_vm_and_nic_specs(self):
        """Test generator with VM and NIC specs provided."""
        vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        nic = NicSpec(network="Production", adapter_name="Ethernet 1")
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        config = generate_guest_config(vm, nic, guest_config_spec=guest)
        
        # NIC spec doesn't affect guest config (only guest IP fields do)
        assert "guest_la_uid" in config
        assert len(config) == 2  # Only local admin fields
    
    def test_with_vm_nic_and_disk_specs(self):
        """Test generator with all spec types provided."""
        vm = VmSpec(vm_name="db-01", gb_ram=16, cpu_cores=8)
        nic = NicSpec(network="Storage", adapter_name="iSCSI Adapter")
        disk = DiskSpec(image_name="Windows Server 2022", disk_size_gb=500)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        config = generate_guest_config(vm, nic, disk, guest)
        
        # Disk spec doesn't affect guest config
        assert "guest_la_uid" in config
        assert len(config) == 2
    
    def test_with_only_vm_spec(self):
        """Test generator with only VM spec (no NIC or disk)."""
        vm = VmSpec(vm_name="standalone-vm", gb_ram=2, cpu_cores=1)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        assert config["guest_la_uid"] == "Administrator"


class TestGeneratorFromDicts:
    """Test the dict-based generator convenience function."""
    
    def test_generate_from_dicts_minimal(self):
        """Test generating guest config from dict inputs."""
        vm_dict = {
            "vm_name": "web-01",
            "gb_ram": 4,
            "cpu_cores": 2,
        }
        guest_dict = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
        }
        
        config = generate_guest_config_from_dicts(vm_dict, guest_config_dict=guest_dict)
        
        assert config["guest_la_uid"] == "Administrator"
        assert config["guest_la_pw"] == "SecurePass123!"
    
    def test_generate_from_dicts_with_domain_join(self):
        """Test generating config from dicts with domain join."""
        vm_dict = {
            "vm_name": "app-01",
            "gb_ram": 8,
            "cpu_cores": 4,
        }
        guest_dict = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
            "guest_domain_jointarget": "corp.example.com",
            "guest_domain_joinuid": "EXAMPLE\\svc_join",
            "guest_domain_joinpw": "DomainPass456!",
            "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
        }
        
        config = generate_guest_config_from_dicts(vm_dict, guest_config_dict=guest_dict)
        
        assert config["guest_domain_jointarget"] == "corp.example.com"
    
    def test_generate_from_dicts_with_nic(self):
        """Test generating config with NIC dict."""
        vm_dict = {
            "vm_name": "web-01",
            "gb_ram": 4,
            "cpu_cores": 2,
        }
        nic_dict = {
            "network": "Production",
        }
        guest_dict = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
            "guest_v4_ipaddr": "192.168.1.100",
            "guest_v4_cidrprefix": 24,
            "guest_v4_defaultgw": "192.168.1.1",
            "guest_v4_dns1": "192.168.1.10",
        }
        
        config = generate_guest_config_from_dicts(
            vm_dict,
            nic_dict=nic_dict,
            guest_config_dict=guest_dict,
        )
        
        assert config["guest_v4_ipaddr"] == "192.168.1.100"
    
    def test_generate_from_dicts_validation_error(self):
        """Test that invalid dict raises ValidationError."""
        vm_dict = {
            "vm_name": "a" * 100,  # Too long
            "gb_ram": 4,
            "cpu_cores": 2,
        }
        guest_dict = {
            "guest_la_uid": "Administrator",
            "guest_la_pw": "SecurePass123!",
        }
        
        with pytest.raises(ValidationError) as exc_info:
            generate_guest_config_from_dicts(vm_dict, guest_config_dict=guest_dict)
        
        # Should fail on VM name length
        errors = exc_info.value.errors()
        assert any("vm_name" in str(e["loc"]) for e in errors)
    
    def test_generate_from_dicts_no_guest_config(self):
        """Test generating from dicts with no guest config."""
        vm_dict = {
            "vm_name": "test-vm",
            "gb_ram": 2,
            "cpu_cores": 1,
        }
        
        config = generate_guest_config_from_dicts(vm_dict)
        
        assert config == {}


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_empty_optional_strings_not_included(self):
        """Test that empty optional strings are not included."""
        vm = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="192.168.1.100",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
            # guest_v4_dns2 is None
            # guest_net_dnssuffix is None
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Optional fields should not be included if None
        assert "guest_v4_dns2" not in config
        assert "guest_net_dnssuffix" not in config
    
    def test_config_dict_is_flat(self):
        """Test that generated config is a flat dictionary."""
        vm = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # All values should be simple types, not nested dicts
        for value in config.values():
            assert not isinstance(value, dict)
            assert not isinstance(value, list)
    
    def test_multiple_vms_with_same_generator(self):
        """Test generating config for multiple VMs."""
        vms = [
            VmSpec(vm_name=f"web-{i:02d}", gb_ram=4, cpu_cores=2)
            for i in range(1, 4)
        ]
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        configs = [generate_guest_config(vm, guest_config_spec=guest) for vm in vms]
        
        # All should have the same guest config (since guest spec is the same)
        for config in configs:
            assert config["guest_la_uid"] == "Administrator"
            assert config["guest_la_pw"] == "SecurePass123!"
    
    def test_generator_is_pure_function(self):
        """Test that generator doesn't mutate inputs."""
        vm = VmSpec(vm_name="test-vm", gb_ram=4, cpu_cores=2)
        guest = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
        )
        
        # Store original values
        original_vm_name = vm.vm_name
        original_uid = guest.guest_la_uid
        
        # Generate config
        config = generate_guest_config(vm, guest_config_spec=guest)
        
        # Inputs should be unchanged
        assert vm.vm_name == original_vm_name
        assert guest.guest_la_uid == original_uid
        
        # Modifying config should not affect inputs
        config["guest_la_uid"] = "ModifiedUser"
        assert guest.guest_la_uid == original_uid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
