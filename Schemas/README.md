# Host Resources Configuration

This directory contains JSON schemas for configuring Aether-V components.

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

When submitting a VM provisioning job, users can now specify:

- **network** (optional): Name of a network defined in the host configuration (e.g., "Production")
- **storage_class** (optional): Name of a storage class (e.g., "fast-ssd")

Example job submission:
```json
{
  "schema": {
    "id": "vm-provisioning",
    "version": 1
  },
  "fields": {
    "vm_name": "web-server-01",
    "image_name": "Windows Server 2022",
    "gb_ram": 8,
    "cpu_cores": 4,
    "network": "Production",
    "storage_class": "fast-ssd",
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

## job-inputs.yaml Schema

The `job-inputs.yaml` schema defines the fields required for VM provisioning requests. This schema is used by the server to validate incoming job submissions.

See the file itself for field definitions and validation rules.
