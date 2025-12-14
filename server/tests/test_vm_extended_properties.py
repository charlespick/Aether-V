"""Tests for VM extended properties.

This test suite validates the expanded VM and VMNetworkAdapter models
with additional properties for security, boot settings, host actions,
integration services, and network adapter settings.
"""
import pytest
from pydantic import ValidationError

from app.core.models import (
    VM,
    VMState,
    VMNetworkAdapter,
    HostRecoveryAction,
    HostStopAction,
)


class TestVMExtendedProperties:
    """Test VM model with extended properties."""
    
    def test_vm_with_cluster(self):
        """Test VM with cluster field."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            cluster="production-cluster",
            state=VMState.RUNNING
        )
        
        assert vm.cluster == "production-cluster"
    
    def test_vm_with_dynamic_memory_buffer(self):
        """Test VM with dynamic memory buffer percentage."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            dynamic_memory_enabled=True,
            memory_startup_gb=4.0,
            memory_min_gb=2.0,
            memory_max_gb=8.0,
            dynamic_memory_buffer=20
        )
        
        assert vm.dynamic_memory_buffer == 20
        assert vm.dynamic_memory_enabled is True
    
    def test_vm_with_secure_boot_enabled(self):
        """Test VM with secure boot enabled."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            secure_boot_enabled=True,
            secure_boot_template="Microsoft Windows"
        )
        
        assert vm.secure_boot_enabled is True
        assert vm.secure_boot_template == "Microsoft Windows"
    
    def test_vm_with_tpm_enabled(self):
        """Test VM with TPM enabled."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            trusted_platform_module_enabled=True,
            tpm_key_protector="sample-key-protector"
        )
        
        assert vm.trusted_platform_module_enabled is True
        assert vm.tpm_key_protector == "sample-key-protector"
    
    def test_vm_with_primary_boot_device(self):
        """Test VM with primary boot device."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            primary_boot_device="IDE"
        )
        
        assert vm.primary_boot_device == "IDE"
    
    def test_vm_with_host_recovery_action(self):
        """Test VM with host recovery action."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            host_recovery_action=HostRecoveryAction.ALWAYS_START
        )
        
        assert vm.host_recovery_action == HostRecoveryAction.ALWAYS_START
        assert vm.host_recovery_action.value == "always-start"
    
    def test_vm_with_host_stop_action(self):
        """Test VM with host stop action."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            host_stop_action=HostStopAction.SHUT_DOWN
        )
        
        assert vm.host_stop_action == HostStopAction.SHUT_DOWN
        assert vm.host_stop_action.value == "shut-down"
    
    def test_vm_with_integration_services(self):
        """Test VM with all integration services."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            integration_services_shutdown=True,
            integration_services_time=True,
            integration_services_data_exchange=True,
            integration_services_heartbeat=True,
            integration_services_vss_backup=True,
            integration_services_guest_services=False
        )
        
        assert vm.integration_services_shutdown is True
        assert vm.integration_services_time is True
        assert vm.integration_services_data_exchange is True
        assert vm.integration_services_heartbeat is True
        assert vm.integration_services_vss_backup is True
        assert vm.integration_services_guest_services is False
    
    def test_vm_with_all_extended_properties(self):
        """Test VM with all extended properties set."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            cluster="production-cluster",
            state=VMState.RUNNING,
            cpu_cores=4,
            memory_startup_gb=8.0,
            memory_min_gb=4.0,
            memory_max_gb=16.0,
            dynamic_memory_enabled=True,
            dynamic_memory_buffer=20,
            secure_boot_enabled=True,
            secure_boot_template="Microsoft Windows",
            trusted_platform_module_enabled=True,
            tpm_key_protector="key-protector-guid",
            primary_boot_device="SCSI",
            host_recovery_action=HostRecoveryAction.ALWAYS_START,
            host_stop_action=HostStopAction.SHUT_DOWN,
            integration_services_shutdown=True,
            integration_services_time=True,
            integration_services_data_exchange=True,
            integration_services_heartbeat=True,
            integration_services_vss_backup=True,
            integration_services_guest_services=True
        )
        
        # Verify all properties
        assert vm.cluster == "production-cluster"
        assert vm.dynamic_memory_buffer == 20
        assert vm.secure_boot_enabled is True
        assert vm.trusted_platform_module_enabled is True
        assert vm.primary_boot_device == "SCSI"
        assert vm.host_recovery_action == HostRecoveryAction.ALWAYS_START
        assert vm.host_stop_action == HostStopAction.SHUT_DOWN
        assert vm.integration_services_shutdown is True
    
    def test_vm_serialization_with_extended_properties(self):
        """Test VM serialization with extended properties."""
        vm = VM(
            name="test-vm",
            host="hyperv-01.example.com",
            state=VMState.RUNNING,
            cluster="production-cluster",
            secure_boot_enabled=True,
            host_recovery_action=HostRecoveryAction.RESUME
        )
        
        data = vm.model_dump()
        assert data["cluster"] == "production-cluster"
        assert data["secure_boot_enabled"] is True
        assert data["host_recovery_action"] == "resume"
    
    def test_vm_deserialization_with_extended_properties(self):
        """Test VM deserialization with extended properties."""
        data = {
            "name": "test-vm",
            "host": "hyperv-01.example.com",
            "state": "Running",
            "cluster": "production-cluster",
            "secure_boot_enabled": True,
            "host_recovery_action": "always-start",
            "host_stop_action": "shut-down"
        }
        
        vm = VM(**data)
        assert vm.cluster == "production-cluster"
        assert vm.secure_boot_enabled is True
        assert vm.host_recovery_action == HostRecoveryAction.ALWAYS_START
        assert vm.host_stop_action == HostStopAction.SHUT_DOWN


class TestVMNetworkAdapterExtendedProperties:
    """Test VMNetworkAdapter model with extended properties."""
    
    def test_network_adapter_with_mac_address_config(self):
        """Test network adapter with MAC address configuration."""
        adapter = VMNetworkAdapter(
            network="Production",
            mac_address="00:15:5D:00:00:01",
            mac_address_config="Static"
        )
        
        assert adapter.mac_address_config == "Static"
    
    def test_network_adapter_with_security_settings(self):
        """Test network adapter with security settings."""
        adapter = VMNetworkAdapter(
            network="Production",
            dhcp_guard=True,
            router_guard=True,
            mac_spoof_guard=False
        )
        
        assert adapter.dhcp_guard is True
        assert adapter.router_guard is True
        assert adapter.mac_spoof_guard is False
    
    def test_network_adapter_with_bandwidth_settings(self):
        """Test network adapter with bandwidth settings."""
        adapter = VMNetworkAdapter(
            network="Production",
            min_bandwidth_mbps=100,
            max_bandwidth_mbps=1000
        )
        
        assert adapter.min_bandwidth_mbps == 100
        assert adapter.max_bandwidth_mbps == 1000
    
    def test_network_adapter_with_all_extended_properties(self):
        """Test network adapter with all extended properties."""
        adapter = VMNetworkAdapter(
            id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            vlan_id=100,
            virtual_switch="External-Switch",
            mac_address="00:15:5D:00:00:01",
            mac_address_config="Static",
            dhcp_guard=True,
            router_guard=True,
            mac_spoof_guard=False,
            min_bandwidth_mbps=100,
            max_bandwidth_mbps=1000
        )
        
        # Verify all properties
        assert adapter.network == "Production"
        assert adapter.vlan_id == 100
        assert adapter.mac_address_config == "Static"
        assert adapter.dhcp_guard is True
        assert adapter.router_guard is True
        assert adapter.mac_spoof_guard is False
        assert adapter.min_bandwidth_mbps == 100
        assert adapter.max_bandwidth_mbps == 1000
    
    def test_network_adapter_serialization_with_extended_properties(self):
        """Test network adapter serialization with extended properties."""
        adapter = VMNetworkAdapter(
            network="Production",
            mac_address_config="Dynamic",
            dhcp_guard=True,
            min_bandwidth_mbps=50
        )
        
        data = adapter.model_dump()
        assert data["mac_address_config"] == "Dynamic"
        assert data["dhcp_guard"] is True
        assert data["min_bandwidth_mbps"] == 50
    
    def test_network_adapter_deserialization_with_extended_properties(self):
        """Test network adapter deserialization with extended properties."""
        data = {
            "network": "Production",
            "vlan_id": 200,
            "mac_address_config": "Static",
            "dhcp_guard": False,
            "router_guard": True,
            "mac_spoof_guard": True,
            "min_bandwidth_mbps": 200,
            "max_bandwidth_mbps": 2000
        }
        
        adapter = VMNetworkAdapter(**data)
        assert adapter.network == "Production"
        assert adapter.vlan_id == 200
        assert adapter.mac_address_config == "Static"
        assert adapter.dhcp_guard is False
        assert adapter.router_guard is True
        assert adapter.mac_spoof_guard is True
        assert adapter.min_bandwidth_mbps == 200
        assert adapter.max_bandwidth_mbps == 2000


class TestHostActionEnums:
    """Test HostRecoveryAction and HostStopAction enums."""
    
    def test_host_recovery_action_enum_values(self):
        """Test all HostRecoveryAction enum values."""
        assert HostRecoveryAction.NONE.value == "none"
        assert HostRecoveryAction.RESUME.value == "resume"
        assert HostRecoveryAction.ALWAYS_START.value == "always-start"
    
    def test_host_stop_action_enum_values(self):
        """Test all HostStopAction enum values."""
        assert HostStopAction.SAVE.value == "save"
        assert HostStopAction.STOP.value == "stop"
        assert HostStopAction.SHUT_DOWN.value == "shut-down"
    
    def test_host_recovery_action_from_string(self):
        """Test creating HostRecoveryAction from string."""
        action = HostRecoveryAction("always-start")
        assert action == HostRecoveryAction.ALWAYS_START
    
    def test_host_stop_action_from_string(self):
        """Test creating HostStopAction from string."""
        action = HostStopAction("shut-down")
        assert action == HostStopAction.SHUT_DOWN


class TestBackwardCompatibility:
    """Test backward compatibility with new optional fields."""
    
    def test_vm_without_extended_properties(self):
        """Test VM creation without any extended properties."""
        vm = VM(
            name="simple-vm",
            host="hyperv-01.example.com",
            state=VMState.OFF
        )
        
        # All extended properties should be None by default
        assert vm.cluster is None
        assert vm.dynamic_memory_buffer is None
        assert vm.secure_boot_enabled is None
        assert vm.trusted_platform_module_enabled is None
        assert vm.host_recovery_action is None
        assert vm.host_stop_action is None
        assert vm.integration_services_shutdown is None
    
    def test_network_adapter_without_extended_properties(self):
        """Test network adapter creation without extended properties."""
        adapter = VMNetworkAdapter(network="Production")
        
        # All extended properties should be None by default
        assert adapter.mac_address_config is None
        assert adapter.dhcp_guard is None
        assert adapter.router_guard is None
        assert adapter.mac_spoof_guard is None
        assert adapter.min_bandwidth_mbps is None
        assert adapter.max_bandwidth_mbps is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
