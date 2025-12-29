# Host Resources Configuration

## Overview

The Host Resources Configuration system provides a declarative way to define available resources on each Hyper-V host, including storage classes, networks, and VM images. This configuration is managed externally via configuration management tools (e.g., Ansible, Chef, Puppet) and consumed by the Aether-V orchestration service for validation and UI population.

## Purpose

The hostresources.json file serves several key purposes:

1. **Validation**: Ensures that VM provisioning requests reference valid, available resources
2. **UI Enhancement**: Populates dropdowns in the web UI with available options based on target host/cluster
3. **Abstraction**: Provides human-readable names for resources (e.g., "fast-ssd" instead of raw paths)
4. **Centralization**: Single source of truth for host resource definitions

## File Location

The hostresources.json file must be placed at:

```
C:\ProgramData\Aether-V\hostresources.json
```

This location is automatically checked during inventory collection by the `Inventory.Collect.ps1` script.

## Schema Structure

### Top-Level Properties

- `version` (integer, required): Schema version number (currently 1)
- `schema_name` (string, required): Must be "hostresources"
- `storage_classes` (array, required): List of available storage classes
- `networks` (array, required): List of available networks
- `virtual_machines_path` (string, required): Default path for VM configuration files
- `images` (array, optional): List of available VM images for cloning

### Storage Classes

Storage classes define named storage locations where VM disks can be stored.

```json
{
  "name": "fast-ssd",
  "path": "C:\\ClusterStorage\\Volume1\\Storage"
}
```

**Properties:**
- `name` (string, required): Unique identifier for the storage class
- `path` (string, required): Windows filesystem path where VM disks will be stored

### Networks

Networks define named network configurations that VMs can connect to.

```json
{
  "name": "Production",
  "model": "vlan",
  "configuration": {
    "virtual_switch": "External-Switch",
    "vlan_id": 100
  },
  "ip_settings": {
    "gateway": "10.0.100.1",
    "dns": "10.0.100.10",
    "dns_secondary": "10.0.100.11",
    "subnet_mask": "255.255.255.0",
    "network_address": "10.0.100.0",
    "dhcp_available": true
  }
}
```

**Properties:**
- `name` (string, required): Unique identifier for the network
- `model` (string, required): Network model type (currently only "vlan" is supported)
- `configuration` (object, required): Model-specific configuration
  - `virtual_switch` (string, required): Name of the Hyper-V virtual switch
  - `vlan_id` (integer, required): VLAN identifier (1-4094)
- `ip_settings` (object, optional): IP configuration settings
  - `gateway` (string, optional): Default gateway IP address
  - `dns` (string, optional): Primary DNS server IP address
  - `dns_secondary` (string, optional): Secondary DNS server IP address
  - `subnet_mask` (string, optional): Subnet mask (e.g., "255.255.255.0")
  - `network_address` (string, optional): Network address (e.g., "10.0.100.0")
  - `dhcp_available` (boolean, optional): Whether DHCP is available on this network

**IP Settings Behavior:**
- IP settings are **optional** and used only for UI prefill and backend validation
- When a user selects a network with IP settings in the UI, those values are prefilled in the form
- The backend validates but does not auto-populate - it remains explicit in behavior
- If IP settings are not present, users enter values manually as before

### Images

Images define available VM templates that can be cloned during provisioning.

```json
{
  "name": "ubuntu-22.04",
  "path": "C:\\Images\\ubuntu-22.04-server.vhdx",
  "os_family": "linux",
  "description": "Ubuntu Server 22.04 LTS"
}
```

**Properties:**
- `name` (string, required): Unique identifier for the image
- `path` (string, required): Full Windows filesystem path to the image file (.vhdx or .vhd)
- `os_family` (string, optional): Operating system family ("windows" or "linux")
- `description` (string, optional): Human-readable description of the image

## Complete Example

```json
{
  "version": 1,
  "schema_name": "hostresources",
  "storage_classes": [
    {
      "name": "fast-ssd",
      "path": "C:\\ClusterStorage\\Volume1\\Storage"
    },
    {
      "name": "bulk-storage",
      "path": "C:\\ClusterStorage\\Volume2\\Storage"
    }
  ],
  "networks": [
    {
      "name": "Production",
      "model": "vlan",
      "configuration": {
        "virtual_switch": "External-Switch",
        "vlan_id": 100
      },
      "ip_settings": {
        "gateway": "10.0.100.1",
        "dns": "10.0.100.10",
        "dns_secondary": "10.0.100.11",
        "subnet_mask": "255.255.255.0",
        "network_address": "10.0.100.0",
        "dhcp_available": true
      }
    },
    {
      "name": "Development",
      "model": "vlan",
      "configuration": {
        "virtual_switch": "External-Switch",
        "vlan_id": 200
      }
    }
  ],
  "virtual_machines_path": "C:\\ClusterStorage\\Volume1\\VirtualMachines",
  "images": [
    {
      "name": "ubuntu-22.04",
      "path": "C:\\Images\\ubuntu-22.04-server.vhdx",
      "os_family": "linux",
      "description": "Ubuntu Server 22.04 LTS"
    },
    {
      "name": "windows-server-2022",
      "path": "C:\\Images\\windows-server-2022-standard.vhdx",
      "os_family": "windows",
      "description": "Windows Server 2022 Standard"
    }
  ]
}
```

## Management Approach

### Configuration Management

The hostresources.json file should be managed using your organization's configuration management tool:

- **Ansible**: Use the `copy` or `template` module to deploy the file
- **Chef**: Use a `cookbook_file` or `template` resource
- **Puppet**: Use the `file` resource
- **DSC**: Use the `File` resource in Desired State Configuration

### Example: Ansible Playbook

```yaml
- name: Deploy host resources configuration
  hosts: hyperv_hosts
  tasks:
    - name: Ensure Aether-V directory exists
      win_file:
        path: C:\ProgramData\Aether-V
        state: directory

    - name: Deploy hostresources.json
      win_copy:
        src: files/hostresources.json
        dest: C:\ProgramData\Aether-V\hostresources.json
```

### Validation

After deployment, the configuration is automatically validated during inventory collection:

1. The `Inventory.Collect.ps1` script reads the file
2. The orchestration service parses and validates the JSON structure
3. Invalid configurations generate warnings in the inventory collection logs
4. Resources become available in the UI and API responses

## API Integration

### Host Detail Endpoint

Resources are exposed in the host detail response:

**GET /api/v1/hosts/{hostname}**

```json
{
  "hostname": "hyperv01.lab.local",
  "cluster": "Production",
  "connected": true,
  "resources": {
    "storage_classes": [...],
    "networks": [...],
    "images": [...]
  }
}
```

### Cluster Detail Endpoint

Resources are aggregated from all connected hosts in a cluster:

**GET /api/v1/clusters/{cluster_name}**

```json
{
  "id": "Production",
  "name": "Production",
  "storage_classes": [...],
  "networks": [...],
  "images": [...]
}
```

### Validation

The orchestration service validates resource references in provisioning requests:

- **VM Creation**: Validates `storage_class` against target host
- **Disk Creation**: Validates `storage_class` against VM's host
- **NIC Creation**: Validates `network` against VM's host
- **Managed Deployment**: Validates `storage_class`, `network`, and `image_name` against target host

Invalid references result in HTTP 400 errors before job submission.

## Best Practices

1. **Consistency**: Use consistent naming conventions across all hosts in a cluster
2. **Documentation**: Include descriptive names and descriptions for all resources
3. **Testing**: Validate JSON syntax before deployment
4. **Version Control**: Store hostresources.json in version control
5. **Automation**: Deploy changes automatically through CI/CD pipelines
6. **Monitoring**: Monitor inventory collection warnings for configuration issues

## Troubleshooting

### File Not Found

If the file is not present, inventory collection will generate a warning but continue to function. Resources will not be available for validation or UI population.

**Solution**: Deploy the hostresources.json file to the correct location.

### Invalid JSON

If the JSON is malformed, inventory collection will generate an error.

**Solution**: Validate JSON syntax using a linter or online validator.

### Missing Required Fields

If required fields are missing, the configuration will be rejected.

**Solution**: Ensure all required fields are present according to the schema.

### Resources Not Appearing in UI

If resources are configured but not appearing:

1. Check inventory collection logs for warnings
2. Verify the file is at the correct path
3. Trigger a manual inventory refresh
4. Check that the host is connected

## Future Enhancements

Planned enhancements to the host resources system:

- Support for additional network models (bridge, NAT)
- Dynamic resource discovery (automatic detection of storage and images)
- Resource utilization tracking
- Per-resource access control
- Resource tagging and filtering
