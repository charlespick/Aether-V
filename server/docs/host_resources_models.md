# Host Resources Models

This document describes the host resources models added to support authoritative API representation of host configuration state.

## Overview

The host resources models provide a structured way to represent host-specific configuration including storage classes and networks. This allows the API to:

1. Map storage class names to filesystem paths
2. Map network names to VLAN IDs and virtual switches
3. Provide an authoritative source of truth for host resource configuration
4. Enable validation of VM resource requests against available host resources

## Models

### NetworkModel (Enum)

Network model type enum. Currently supports:
- `VLAN = "vlan"` - VLAN-based network model

### StorageClass

Represents a named storage location where VM disks can be stored.

**Fields:**
- `name` (str, required): Unique identifier for the storage class
- `path` (str, required): Filesystem path where VM disks will be stored

**Example:**
```python
StorageClass(
    name="fast-ssd",
    path="C:\\ClusterStorage\\Volume1\\Storage"
)
```

### VlanConfiguration

VLAN-specific network configuration.

**Fields:**
- `virtual_switch` (str, required): Name of the Hyper-V virtual switch
- `vlan_id` (int, required): VLAN identifier (1-4094)

**Example:**
```python
VlanConfiguration(
    virtual_switch="External-Switch",
    vlan_id=100
)
```

### Network

Represents a named network that VMs can connect to.

**Fields:**
- `name` (str, required): Unique identifier for the network
- `model` (NetworkModel, required): Network model type
- `configuration` (VlanConfiguration, required): Network configuration data

**Example:**
```python
Network(
    name="Production",
    model=NetworkModel.VLAN,
    configuration=VlanConfiguration(
        virtual_switch="External-Switch",
        vlan_id=100
    )
)
```

### HostResources

Complete resource configuration for a host. This model matches the `hostresources.json` schema that can be deployed to hosts.

**Fields:**
- `version` (int, required): Schema version number
- `schema_name` (str, required): Name of the schema (should be "hostresources")
- `storage_classes` (List[StorageClass], default=[]): Available storage classes
- `networks` (List[Network], default=[]): Available networks
- `virtual_machines_path` (str, required): Default path for VM configuration files

**Example:**
```python
HostResources(
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
```

### Host (Enhanced)

The existing `Host` model has been enhanced with an optional `resources` field:

**New Field:**
- `resources` (Optional[HostResources], default=None): Host resource configuration

**Example:**
```python
Host(
    hostname="hyperv-01.example.com",
    connected=True,
    resources=HostResources(...)
)
```

### VMDisk (Enhanced)

The existing `VMDisk` model has been enhanced with a storage class reference:

**New Field:**
- `storage_class` (Optional[str], default=None): Storage class name from host resources

**Example:**
```python
VMDisk(
    id="12345678-1234-1234-1234-123456789abc",
    path="C:\\ClusterStorage\\Volume1\\disk1.vhdx",
    size_gb=100.0,
    storage_class="fast-ssd"
)
```

### VMNetworkAdapter (Enhanced)

The existing `VMNetworkAdapter` model has been enhanced with a VLAN ID field:

**New Field:**
- `vlan_id` (Optional[int], default=None): VLAN ID from network configuration

**Note:** The legacy `vlan` field (string) is maintained for backward compatibility.

**Example:**
```python
VMNetworkAdapter(
    id="12345678-1234-1234-1234-123456789abc",
    network="Production",
    vlan_id=100,
    virtual_switch="External-Switch"
)
```

## Usage

### Loading Host Resources from Configuration

The `HostResourcesService` can load host resources from a host's configuration file:

```python
from app.services.host_resources_service import host_resources_service

# Load configuration from host
config = await host_resources_service.get_host_configuration("hyperv-01.example.com")

# Parse into HostResources model
if config:
    resources = HostResources(**config)
```

### Looking Up Resources

```python
# Find storage class by name
storage_class = next(
    (sc for sc in host.resources.storage_classes if sc.name == "fast-ssd"),
    None
)

# Find network by name
network = next(
    (net for net in host.resources.networks if net.name == "Production"),
    None
)

# Get VLAN ID for a network
if network:
    vlan_id = network.configuration.vlan_id
```

### Validation

```python
from app.services.host_resources_service import host_resources_service

# Validate network name exists
config = await host_resources_service.get_host_configuration(host)
is_valid = host_resources_service.validate_network_name("Production", config)

# Validate storage class exists
is_valid = host_resources_service.validate_storage_class("fast-ssd", config)

# Get available networks
networks = host_resources_service.get_available_networks(config)

# Get available storage classes
storage_classes = host_resources_service.get_available_storage_classes(config)
```

## API Compatibility

All models support automatic serialization and deserialization for API use:

```python
# Serialize to dict (for API response)
host_dict = host.model_dump()

# Serialize to JSON
import json
host_json = json.dumps(host_dict)

# Deserialize from dict (for API request)
host = Host(**data_dict)

# Deserialize from JSON
host = Host(**json.loads(host_json))
```

## Backward Compatibility

All changes maintain backward compatibility:

1. **Host.resources** is optional - hosts without resources work as before
2. **VMDisk.storage_class** is optional - disks without storage class work as before
3. **VMNetworkAdapter.vlan_id** is optional and the legacy `vlan` field is maintained
4. Existing code using these models continues to work without changes

## Configuration File Format

Host resources are configured using a `hostresources.json` or `hostresources.yaml` file on the host at:
- `C:\ProgramData\Aether-V\hostresources.json`
- `C:\ProgramData\Aether-V\hostresources.yaml`

See `/Schemas/hostresources.example.json` for an example configuration.

## Testing

Comprehensive tests are available in:
- `tests/test_host_resources_models.py` - Tests for all new models
- `tests/test_pydantic_models.py` - Tests for existing models (validates no regressions)

Run tests with:
```bash
pytest tests/test_host_resources_models.py -v
```
