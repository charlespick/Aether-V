# Host Resources Configuration

This directory contains host resource configuration files for Aether-V.

**Note**: As of Phase 8, YAML job input schemas (vm-create.yaml, disk-create.yaml, nic-create.yaml) have been removed. 
The system now uses Pydantic models exclusively for validation. See `server/app/core/pydantic_models.py` for the current data models.

## hostresources.json Schema

The `hostresources.json` schema defines how storage and network resources are configured on each Hyper-V host. This allows the Aether-V server to remain stateless while hosts maintain their own resource configuration.

### Purpose

The host resources configuration enables:
- **Stateless Server**: The server doesn't need to know about each host's storage paths or network configuration
- **Network Abstraction**: Users select networks by name (e.g., "Production", "Development") instead of raw VLAN IDs
- **Storage Classes**: Administrators can define multiple storage tiers (e.g., "fast-ssd", "bulk-storage") with different performance characteristics
- **Flexibility**: Each host can have its own unique storage and network configuration

### Configuration Location

On each Hyper-V host, the configuration file must be placed at:
```
C:\ProgramData\Aether-V\hostresources.json
```

Alternatively, YAML format is also supported:
```
C:\ProgramData\Aether-V\hostresources.yaml
```

### Schema Structure

```json
{
  "version": 1,
  "schema_name": "hostresources",
  "storage_classes": [
    {
      "name": "fast-ssd",
      "path": "C:\\ClusterStorage\\Volume1\\Storage"
    }
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
```

### Fields

#### Required Fields

- **version** (integer): Schema version number (currently 1)
- **schema_name** (string): Must be "hostresources"
- **storage_classes** (array): List of available storage classes
  - **name** (string): Unique identifier for the storage class
  - **path** (string): Windows filesystem path where VM disks will be stored
- **networks** (array): List of available networks
  - **name** (string): Unique identifier for the network
  - **model** (string): Network model type (currently only "vlan" is supported)
  - **configuration** (object): Model-specific configuration
    - For VLAN model:
      - **virtual_switch** (string): Name of the Hyper-V virtual switch
      - **vlan_id** (integer): VLAN identifier (1-4094)
- **virtual_machines_path** (string): Default path where VM configuration files will be stored

### Example Configuration

See `hostresources.example.json` for a complete example.

### Usage in Job Submissions

When submitting a VM provisioning job via the `/api/v2/managed-deployments` endpoint, users specify:

- **network** (optional): Name of a network defined in the host configuration (e.g., "Production")
- **storage_class** (optional): Name of a storage class (e.g., "fast-ssd")

Example using Pydantic-based API (v2):
```json
{
  "target_host": "hyperv-01",
  "vm_spec": {
    "vm_name": "web-server-01",
    "gb_ram": 8,
    "cpu_cores": 4,
    "storage_class": "fast-ssd"
  },
  "disk_spec": {
    "image_name": "Windows Server 2022",
    "disk_size_gb": 100,
    "storage_class": "fast-ssd"
  },
  "nic_spec": {
    "network": "Production"
  },
  "guest_config": {
    "guest_la_uid": "Administrator",
    "guest_la_pw": "SecurePassword123!"
  }
}
```

### Migration from Legacy Configuration

Previously, VMs were provisioned with:
- Raw VLAN IDs (e.g., `vlan_id: 100`)
- Automatic storage path selection based on available cluster volumes

Now, VMs use:
- Network names (e.g., `network: "Production"`)
- Explicit storage classes (e.g., `storage_class: "fast-ssd"`)
- Separate paths for VM configurations and VM disks

### Benefits

1. **Separation of Concerns**: VM configurations are stored separately from VM disks
2. **No Path Collisions**: Unique IDs are added to VHDX filenames to prevent naming conflicts
3. **Simplified Cleanup**: No complex folder cleanup is needed during VM deletion
4. **Better Organization**: Storage and VMs are organized in predictable, configured locations
5. **Improved Inventory**: Network information is displayed as human-readable names instead of VLAN numbers
