# VM Extended Properties

This document describes the extended properties added to the VM and VMNetworkAdapter models to support comprehensive virtual machine configuration.

## Overview

The VM and VMNetworkAdapter models have been expanded with additional optional properties to support:

1. Cluster membership and failover configuration
2. Dynamic memory buffer configuration
3. Security settings (secure boot, TPM)
4. Boot device configuration
5. Host actions (recovery and stop actions)
6. Integration services settings
7. Network adapter security and bandwidth settings

All new properties are optional and maintain full backward compatibility.

## VM Model Extended Properties

### Cluster and Host Configuration

**New Fields:**
- `cluster` (Optional[str]): Cluster name this VM belongs to

**Example:**
```python
VM(
    name="web-01",
    host="hyperv-01.example.com",
    cluster="production-cluster",
    state=VMState.RUNNING
)
```

### Dynamic Memory

**New Fields:**
- `dynamic_memory_buffer` (Optional[int]): Memory buffer percentage for dynamic memory

**Example:**
```python
VM(
    name="web-01",
    host="hyperv-01.example.com",
    state=VMState.RUNNING,
    dynamic_memory_enabled=True,
    memory_startup_gb=4.0,
    memory_min_gb=2.0,
    memory_max_gb=8.0,
    dynamic_memory_buffer=20  # 20% buffer
)
```

### Security Settings

**New Fields:**
- `secure_boot_enabled` (Optional[bool]): Whether secure boot is enabled
- `secure_boot_template` (Optional[str]): Secure boot template name (e.g., "Microsoft Windows")
- `trusted_platform_module_enabled` (Optional[bool]): Whether TPM is enabled
- `tpm_key_protector` (Optional[str]): TPM key protector identifier

**Example:**
```python
VM(
    name="secure-vm",
    host="hyperv-01.example.com",
    state=VMState.RUNNING,
    secure_boot_enabled=True,
    secure_boot_template="Microsoft Windows",
    trusted_platform_module_enabled=True,
    tpm_key_protector="key-protector-guid"
)
```

### Boot Configuration

**New Fields:**
- `primary_boot_device` (Optional[str]): Primary boot device (e.g., "SCSI", "IDE")

**Example:**
```python
VM(
    name="web-01",
    host="hyperv-01.example.com",
    state=VMState.RUNNING,
    primary_boot_device="SCSI"
)
```

### Host Actions

**New Fields:**
- `host_recovery_action` (Optional[HostRecoveryAction]): Action to take when host recovers
- `host_stop_action` (Optional[HostStopAction]): Action to take when host stops

**Enums:**
- `HostRecoveryAction`: `NONE`, `RESUME`, `ALWAYS_START`
- `HostStopAction`: `SAVE`, `STOP`, `SHUT_DOWN`

**Example:**
```python
VM(
    name="web-01",
    host="hyperv-01.example.com",
    state=VMState.RUNNING,
    host_recovery_action=HostRecoveryAction.ALWAYS_START,
    host_stop_action=HostStopAction.SHUT_DOWN
)
```

### Integration Services

**New Fields:**
- `integration_services_shutdown` (Optional[bool]): Guest shutdown integration service
- `integration_services_time` (Optional[bool]): Time synchronization integration service
- `integration_services_data_exchange` (Optional[bool]): Data exchange integration service
- `integration_services_heartbeat` (Optional[bool]): Heartbeat integration service
- `integration_services_vss_backup` (Optional[bool]): VSS backup integration service
- `integration_services_guest_services` (Optional[bool]): Guest services integration service

**Example:**
```python
VM(
    name="web-01",
    host="hyperv-01.example.com",
    state=VMState.RUNNING,
    integration_services_shutdown=True,
    integration_services_time=True,
    integration_services_data_exchange=True,
    integration_services_heartbeat=True,
    integration_services_vss_backup=True,
    integration_services_guest_services=False
)
```

### Complete Example

```python
from app.core.models import VM, VMState, HostRecoveryAction, HostStopAction

vm = VM(
    id="12345678-1234-1234-1234-123456789abc",
    name="production-vm-01",
    host="hyperv-01.example.com",
    cluster="production-cluster",
    state=VMState.RUNNING,
    cpu_cores=8,
    memory_startup_gb=16.0,
    memory_min_gb=8.0,
    memory_max_gb=32.0,
    dynamic_memory_enabled=True,
    dynamic_memory_buffer=20,
    secure_boot_enabled=True,
    secure_boot_template="Microsoft Windows",
    trusted_platform_module_enabled=True,
    tpm_key_protector="sample-key-protector-guid",
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
```

## VMNetworkAdapter Extended Properties

### MAC Address Configuration

**New Fields:**
- `mac_address_config` (Optional[str]): MAC address configuration mode ("Dynamic" or "Static")

**Example:**
```python
VMNetworkAdapter(
    network="Production",
    mac_address="00:15:5D:00:00:01",
    mac_address_config="Static"
)
```

### Security Settings

**New Fields:**
- `dhcp_guard` (Optional[bool]): Enable DHCP guard
- `router_guard` (Optional[bool]): Enable router guard
- `mac_spoof_guard` (Optional[bool]): Enable MAC spoofing guard

**Example:**
```python
VMNetworkAdapter(
    network="Production",
    dhcp_guard=True,
    router_guard=True,
    mac_spoof_guard=False
)
```

### Bandwidth Settings

**New Fields:**
- `min_bandwidth_mbps` (Optional[int]): Minimum bandwidth in Mbps
- `max_bandwidth_mbps` (Optional[int]): Maximum bandwidth in Mbps

**Example:**
```python
VMNetworkAdapter(
    network="Production",
    min_bandwidth_mbps=100,
    max_bandwidth_mbps=10000
)
```

### Complete Example

```python
from app.core.models import VMNetworkAdapter

adapter = VMNetworkAdapter(
    id="87654321-4321-4321-4321-123456789abc",
    network="Production",
    vlan_id=100,
    virtual_switch="External-Switch",
    mac_address="00:15:5D:00:00:01",
    mac_address_config="Static",
    dhcp_guard=True,
    router_guard=True,
    mac_spoof_guard=False,
    min_bandwidth_mbps=100,
    max_bandwidth_mbps=10000
)
```

## API Compatibility

All extended properties support automatic serialization and deserialization:

```python
# Serialize to dict (for API response)
vm_dict = vm.model_dump()

# Serialize to JSON
import json
vm_json = json.dumps(vm_dict)

# Deserialize from dict (for API request)
vm = VM(**data_dict)

# Deserialize from JSON
vm = VM(**json.loads(vm_json))
```

## Backward Compatibility

All extended properties are optional with `None` as the default value. Existing code that creates VMs and network adapters without these properties continues to work without changes:

```python
# This still works - all extended properties default to None
vm = VM(
    name="simple-vm",
    host="hyperv-01.example.com",
    state=VMState.OFF
)

adapter = VMNetworkAdapter(network="Production")
```

## Usage with Inventory Service

These extended properties are designed to be populated by the inventory collection system. When collecting VM information from Hyper-V hosts, the inventory service should populate these fields based on the actual VM configuration.

Example inventory collection flow:
1. Query Hyper-V for VM details
2. Map Hyper-V properties to model fields
3. Store VM with all available properties
4. Return VM objects via API with complete configuration

## Testing

Comprehensive tests are available in:
- `tests/test_vm_extended_properties.py` - Tests for all extended properties

Run tests with:
```bash
pytest tests/test_vm_extended_properties.py -v
```

## Related Documentation

- [Host Resources Models](host_resources_models.md) - Documentation for host resource configuration models
