"""Tests for host resources models.

This test suite validates the new host resources models including:
1. StorageClass model
2. Network and VlanConfiguration models
3. HostResources model
4. Host model with resources
5. VMDisk with storage_class
6. VMNetworkAdapter with vlan_id
"""
import pytest
from pydantic import ValidationError

from app.core.models import (
    StorageClass,
    Network,
    VlanConfiguration,
    NetworkModel,
    HostResources,
    Host,
    VMDisk,
    VMNetworkAdapter,
)


class TestStorageClassModel:
    """Test StorageClass model."""
    
    def test_valid_storage_class(self):
        """Test valid storage class creation."""
        storage_class = StorageClass(
            name="fast-ssd",
            path="C:\\ClusterStorage\\Volume1\\Storage"
        )
        
        assert storage_class.name == "fast-ssd"
        assert storage_class.path == "C:\\ClusterStorage\\Volume1\\Storage"
    
    def test_storage_class_serialization(self):
        """Test storage class serialization to dict."""
        storage_class = StorageClass(
            name="bulk-storage",
            path="C:\\ClusterStorage\\Volume2\\Storage"
        )
        
        data = storage_class.model_dump()
        assert data["name"] == "bulk-storage"
        assert data["path"] == "C:\\ClusterStorage\\Volume2\\Storage"
    
    def test_storage_class_missing_fields(self):
        """Test storage class validation with missing fields."""
        with pytest.raises(ValidationError) as exc_info:
            StorageClass(name="test-storage")
        
        errors = exc_info.value.errors()
        assert any("path" in str(e["loc"]) for e in errors)


class TestNetworkModels:
    """Test Network and VlanConfiguration models."""
    
    def test_valid_vlan_configuration(self):
        """Test valid VLAN configuration."""
        vlan_config = VlanConfiguration(
            virtual_switch="External-Switch",
            vlan_id=100
        )
        
        assert vlan_config.virtual_switch == "External-Switch"
        assert vlan_config.vlan_id == 100
    
    def test_vlan_id_validation_min(self):
        """Test VLAN ID minimum validation."""
        with pytest.raises(ValidationError) as exc_info:
            VlanConfiguration(
                virtual_switch="External-Switch",
                vlan_id=0  # Min is 1
            )
        
        errors = exc_info.value.errors()
        assert any("vlan_id" in str(e["loc"]) for e in errors)
    
    def test_vlan_id_validation_max(self):
        """Test VLAN ID maximum validation."""
        with pytest.raises(ValidationError) as exc_info:
            VlanConfiguration(
                virtual_switch="External-Switch",
                vlan_id=5000  # Max is 4094
            )
        
        errors = exc_info.value.errors()
        assert any("vlan_id" in str(e["loc"]) for e in errors)
    
    def test_valid_network(self):
        """Test valid network creation."""
        network = Network(
            name="Production",
            model=NetworkModel.VLAN,
            configuration=VlanConfiguration(
                virtual_switch="External-Switch",
                vlan_id=100
            )
        )
        
        assert network.name == "Production"
        assert network.model == NetworkModel.VLAN
        assert network.configuration.vlan_id == 100
    
    def test_network_serialization(self):
        """Test network serialization to dict."""
        network = Network(
            name="Development",
            model=NetworkModel.VLAN,
            configuration=VlanConfiguration(
                virtual_switch="External-Switch",
                vlan_id=200
            )
        )
        
        data = network.model_dump()
        assert data["name"] == "Development"
        assert data["model"] == "vlan"
        assert data["configuration"]["vlan_id"] == 200


class TestHostResourcesModel:
    """Test HostResources model."""
    
    def test_valid_host_resources(self):
        """Test valid host resources configuration."""
        resources = HostResources(
            version=1,
            schema_name="hostresources",
            storage_classes=[
                StorageClass(name="fast-ssd", path="C:\\ClusterStorage\\Volume1"),
                StorageClass(name="bulk-storage", path="C:\\ClusterStorage\\Volume2")
            ],
            networks=[
                Network(
                    name="Production",
                    model=NetworkModel.VLAN,
                    configuration=VlanConfiguration(
                        virtual_switch="External-Switch",
                        vlan_id=100
                    )
                )
            ],
            virtual_machines_path="C:\\ClusterStorage\\Volume1\\VirtualMachines"
        )
        
        assert resources.version == 1
        assert resources.schema_name == "hostresources"
        assert len(resources.storage_classes) == 2
        assert len(resources.networks) == 1
        assert resources.virtual_machines_path == "C:\\ClusterStorage\\Volume1\\VirtualMachines"
    
    def test_host_resources_empty_lists(self):
        """Test host resources with empty storage and network lists."""
        resources = HostResources(
            version=1,
            schema_name="hostresources",
            storage_classes=[],
            networks=[],
            virtual_machines_path="C:\\VirtualMachines"
        )
        
        assert len(resources.storage_classes) == 0
        assert len(resources.networks) == 0
    
    def test_host_resources_from_dict(self):
        """Test creating host resources from dictionary (like JSON)."""
        data = {
            "version": 1,
            "schema_name": "hostresources",
            "storage_classes": [
                {"name": "fast-ssd", "path": "C:\\ClusterStorage\\Volume1\\Storage"}
            ],
            "networks": [
                {
                    "name": "Production",
                    "model": "vlan",
                    "configuration": {
                        "virtual_switch": "External-Switch",
                        "vlan_id": 100
                    }
                }
            ],
            "virtual_machines_path": "C:\\ClusterStorage\\Volume1\\VirtualMachines"
        }
        
        resources = HostResources(**data)
        assert resources.version == 1
        assert resources.storage_classes[0].name == "fast-ssd"
        assert resources.networks[0].configuration.vlan_id == 100


class TestHostModelWithResources:
    """Test Host model with resources field."""
    
    def test_host_without_resources(self):
        """Test host without resources (backward compatibility)."""
        host = Host(
            hostname="hyperv-01.example.com",
            connected=True,
            total_cpu_cores=32,
            total_memory_gb=128.0
        )
        
        assert host.hostname == "hyperv-01.example.com"
        assert host.resources is None
    
    def test_host_with_resources(self):
        """Test host with full resources configuration."""
        host = Host(
            hostname="hyperv-01.example.com",
            connected=True,
            resources=HostResources(
                version=1,
                schema_name="hostresources",
                storage_classes=[
                    StorageClass(name="fast-ssd", path="C:\\ClusterStorage\\Volume1")
                ],
                networks=[
                    Network(
                        name="Production",
                        model=NetworkModel.VLAN,
                        configuration=VlanConfiguration(
                            virtual_switch="External-Switch",
                            vlan_id=100
                        )
                    )
                ],
                virtual_machines_path="C:\\ClusterStorage\\Volume1\\VirtualMachines"
            )
        )
        
        assert host.hostname == "hyperv-01.example.com"
        assert host.resources is not None
        assert len(host.resources.storage_classes) == 1
        assert len(host.resources.networks) == 1
        assert host.resources.networks[0].name == "Production"
    
    def test_host_resources_lookup(self):
        """Test looking up resources from host configuration."""
        host = Host(
            hostname="hyperv-01.example.com",
            resources=HostResources(
                version=1,
                schema_name="hostresources",
                storage_classes=[
                    StorageClass(name="fast-ssd", path="C:\\ClusterStorage\\Volume1"),
                    StorageClass(name="bulk-storage", path="C:\\ClusterStorage\\Volume2")
                ],
                networks=[
                    Network(
                        name="Production",
                        model=NetworkModel.VLAN,
                        configuration=VlanConfiguration(
                            virtual_switch="External-Switch",
                            vlan_id=100
                        )
                    ),
                    Network(
                        name="Development",
                        model=NetworkModel.VLAN,
                        configuration=VlanConfiguration(
                            virtual_switch="External-Switch",
                            vlan_id=200
                        )
                    )
                ],
                virtual_machines_path="C:\\VirtualMachines"
            )
        )
        
        # Verify we can access storage classes
        storage_names = [sc.name for sc in host.resources.storage_classes]
        assert "fast-ssd" in storage_names
        assert "bulk-storage" in storage_names
        
        # Verify we can access networks
        network_names = [net.name for net in host.resources.networks]
        assert "Production" in network_names
        assert "Development" in network_names
        
        # Verify we can look up specific network by name
        prod_network = next((n for n in host.resources.networks if n.name == "Production"), None)
        assert prod_network is not None
        assert prod_network.configuration.vlan_id == 100


class TestVMDiskWithStorageClass:
    """Test VMDisk model with storage_class field."""
    
    def test_vm_disk_without_storage_class(self):
        """Test VM disk without storage class (backward compatibility)."""
        disk = VMDisk(
            id="12345678-1234-1234-1234-123456789abc",
            path="C:\\VMs\\disk1.vhdx",
            size_gb=100.0
        )
        
        assert disk.id == "12345678-1234-1234-1234-123456789abc"
        assert disk.storage_class is None
    
    def test_vm_disk_with_storage_class(self):
        """Test VM disk with storage class reference."""
        disk = VMDisk(
            id="12345678-1234-1234-1234-123456789abc",
            path="C:\\ClusterStorage\\Volume1\\disk1.vhdx",
            size_gb=100.0,
            storage_class="fast-ssd"
        )
        
        assert disk.storage_class == "fast-ssd"
        assert disk.path == "C:\\ClusterStorage\\Volume1\\disk1.vhdx"


class TestVMNetworkAdapterWithVlanId:
    """Test VMNetworkAdapter model with vlan_id field."""
    
    def test_network_adapter_without_vlan_id(self):
        """Test network adapter without VLAN ID (backward compatibility)."""
        adapter = VMNetworkAdapter(
            id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            mac_address="00:15:5D:00:00:01"
        )
        
        assert adapter.network == "Production"
        assert adapter.vlan_id is None
    
    def test_network_adapter_with_vlan_id(self):
        """Test network adapter with VLAN ID."""
        adapter = VMNetworkAdapter(
            id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            vlan_id=100,
            virtual_switch="External-Switch",
            mac_address="00:15:5D:00:00:01"
        )
        
        assert adapter.network == "Production"
        assert adapter.vlan_id == 100
        assert adapter.virtual_switch == "External-Switch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
