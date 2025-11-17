# Guest Configuration Architecture

## Overview

This document explains how guest configuration (hostname, domain join, IP settings, etc.) is handled in the component-based VM provisioning system.

## Problem Statement

Guest configuration must be injected before the VM starts, but if VM creation completes and returns (so we can get the VM ID for disk/NIC attachment), we've lost the opportunity to inject that configuration.

Additionally, guest configuration fields must remain in the component schemas to drive form rendering on the frontend.

## Solution: Metadata-Based Filtering

Guest configuration fields remain in the component schemas but are marked with a `guest_config: true` metadata flag. The managed deployment orchestration filters fields based on this metadata, sending only hardware fields to the creation scripts and holding guest config fields for the initialization step.

## Schema Architecture

### vm-create.yaml (14 fields)

**Hardware Fields** (6):
- vm_name - VM name
- image_name - Golden image to clone
- gb_ram - Memory allocation
- cpu_cores - CPU count
- storage_class - Storage location
- vm_clustered - Failover cluster registration

**Guest Config Fields** (8) - marked with `guest_config: true`:
- guest_la_uid - Local administrator username
- guest_la_pw - Local administrator password
- guest_domain_jointarget - Domain FQDN to join
- guest_domain_joinuid - Domain join account
- guest_domain_joinpw - Domain join password
- guest_domain_joinou - OU path for computer account
- cnf_ansible_ssh_user - Ansible SSH username
- cnf_ansible_ssh_key - Ansible SSH public key

**Parameter Sets**:
- domain-join: Requires all domain join fields together
- ansible-config: Requires both ansible fields together

### nic-create.yaml (9 fields)

**Hardware Fields** (3):
- vm_id - VM to attach to (internal)
- network - Network name
- adapter_name - Optional adapter name

**Guest IP Config Fields** (6) - marked with `guest_config: true`:
- guest_v4_ipaddr - Static IPv4 address
- guest_v4_cidrprefix - CIDR prefix length
- guest_v4_defaultgw - Default gateway
- guest_v4_dns1 - Primary DNS server
- guest_v4_dns2 - Secondary DNS server
- guest_net_dnssuffix - DNS search suffix

**Parameter Sets**:
- static-ip-config: Requires IP address, prefix, gateway, and primary DNS together

### disk-create.yaml (5 fields)

**Hardware Fields** (all 5):
- vm_id - VM to attach to (internal)
- disk_size_gb - Disk size
- storage_class - Optional storage location
- disk_type - Dynamic or fixed VHD
- controller_type - SCSI or IDE

**No guest config fields** - disks don't have guest-level configuration

## Managed Deployment Orchestration

The managed deployment endpoint (`POST /api/v1/managed-deployments`) orchestrates the 4-step process:

### Step 1: Create VM (Hardware Only)

**Fields sent to Invoke-CreateVmJob.ps1**:
- vm_name
- image_name
- gb_ram
- cpu_cores
- storage_class
- vm_clustered

**Guest config fields held**:
- guest_la_uid, guest_la_pw
- guest_domain_* fields
- cnf_ansible_* fields

**Returns**: VM ID (to be parsed from PowerShell JSON output)

### Step 2: Create Disk

**Fields sent to Invoke-CreateDiskJob.ps1**:
- vm_id (from step 1)
- disk_size_gb
- storage_class (if provided)
- disk_type (if provided)
- controller_type (if provided)

**Returns**: Disk ID

### Step 3: Create NIC (Hardware Only)

**Fields sent to Invoke-CreateNicJob.ps1**:
- vm_id (from step 1)
- network
- adapter_name (if provided)

**Guest IP config fields held**:
- guest_v4_ipaddr, guest_v4_cidrprefix, guest_v4_defaultgw
- guest_v4_dns1, guest_v4_dns2, guest_net_dnssuffix

**Returns**: NIC ID

### Step 4: Initialize VM (Guest Configuration)

**Fields sent to Invoke-InitializeVmJob.ps1**:
- vm_id (from step 1)
- vm_name (from step 1)
- All VM guest config fields (from step 1)
- All NIC guest IP config fields (from step 3)

**Note**: This script receives raw fields, NOT wrapped in a schema structure

**Returns**: Provisioning key

## Implementation Details

### Backend Filtering (job_service.py)

```python
# Load schemas to get field metadata
vm_schema = load_schema_by_id("vm-create")
nic_schema = load_schema_by_id("nic-create")

# Build set of guest config field IDs
guest_config_field_ids = set()
for field in vm_schema.get("fields", []):
    if field.get("guest_config", False):
        guest_config_field_ids.add(field.get("id"))

# Separate hardware from guest config
vm_hardware_fields = {}
vm_guest_config_fields = {}
for field in vm_schema.get("fields", []):
    field_id = field.get("id")
    if field_id in user_input:
        if field.get("guest_config", False):
            vm_guest_config_fields[field_id] = user_input[field_id]
        else:
            vm_hardware_fields[field_id] = user_input[field_id]

# Send only hardware fields to VM creation script
send_to_agent(vm_hardware_fields)

# Hold guest config for initialization
hold_for_later(vm_guest_config_fields)
```

### Frontend Composition (overlay.js)

```javascript
// Fetch all 3 component schemas
const [vmSchema, diskSchema, nicSchema] = await Promise.all([
    fetch('/api/v1/schema/vm-create'),
    fetch('/api/v1/schema/disk-create'),
    fetch('/api/v1/schema/nic-create'),
]);

// Compose single form
const composedSchema = {
    fields: [
        ...vmSchema.fields,           // Includes hardware + guest config
        ...diskSchema.fields.filter(f => f.id !== 'vm_id'),
        ...nicSchema.fields.filter(f => f.id !== 'vm_id' && f.id !== 'adapter_name'),
    ],
    parameter_sets: [
        ...vmSchema.parameter_sets,   // domain-join, ansible-config
        ...nicSchema.parameter_sets,  // static-ip-config
    ]
};

// All fields render in form
// User sees complete unified deployment form
```

### Schema Composition (job_schema.py)

```python
def get_job_schema() -> Dict[str, Any]:
    """Compose from 3 component schemas."""
    vm_schema = load_schema_by_id("vm-create")
    disk_schema = load_schema_by_id("disk-create")
    nic_schema = load_schema_by_id("nic-create")
    
    # Combine all fields (keeping guest_config metadata)
    all_fields = {}
    for schema in [vm_schema, disk_schema, nic_schema]:
        for field in schema.get("fields", []):
            if field.get("id") != "vm_id":  # Internal field
                all_fields[field["id"]] = field
    
    return {
        "version": vm_schema.get("version"),
        "fields": list(all_fields.values()),
        "parameter_sets": [
            ...(vm_schema.get("parameter_sets") or []),
            ...(nic_schema.get("parameter_sets") or []),
        ],
    }
```

## Benefits

### 1. Form Rendering Works

Fields in schemas drive the UI. Since all fields remain in the component schemas, the frontend can render the complete form with proper validation.

### 2. IP Settings Associated with NICs

IP configuration fields are in the nic-create schema, maintaining the logical association. This is critical for future multi-NIC scenarios where each NIC may have different IP settings.

**Future multi-NIC example**:
```javascript
// User adds a second NIC
POST /api/v1/resources/nics
{
  "vm_id": "existing-vm-id",
  "network": "DMZ",
  "guest_v4_ipaddr": "10.1.1.50",  // Different IP than primary NIC
  "guest_v4_cidrprefix": 24,
  "guest_v4_defaultgw": "10.1.1.1"
}
```

### 3. Clean Separation

Hardware properties are sent to agent scripts (physical infrastructure).
Guest configuration is held for initialization (OS-level setup).

Separation is metadata-driven, not schema-driven.

### 4. Only 3 Schemas

No confusing 4th schema. Users understand the 3 resource types:
- VM hardware
- Disk storage
- Network adapter

Guest configuration is an implementation detail of the orchestration, not a separate resource type.

### 5. Flexible for Future

Can add more guest config fields to the appropriate schema:
- VM-level config → vm-create schema
- NIC-level config → nic-create schema
- Disk-level config → disk-create schema (if needed in the future)

### 6. Proper Orchestration

1. Create infrastructure (VM, disk, NIC) - pure hardware
2. Initialize guest OS with configuration - OS-level setup

This matches Hyper-V's architecture and dependencies.

## Component API Usage (Terraform)

For advanced users using Terraform, the component APIs work independently:

```hcl
# Create VM (hardware only, no guest config yet)
resource "aether_vm" "web" {
  target_host = "hyperv01"
  values = {
    vm_name      = "web-01"
    image_name   = "Ubuntu 22.04"
    cpu_cores    = 4
    gb_ram       = 8
    storage_class = "fast-ssd"
  }
}

# Add disk
resource "aether_disk" "data" {
  target_host = "hyperv01"
  values = {
    vm_id        = aether_vm.web.id
    disk_size_gb = 500
  }
}

# Add NIC (hardware only, no IP config yet)
resource "aether_nic" "primary" {
  target_host = "hyperv01"
  values = {
    vm_id   = aether_vm.web.id
    network = "Production"
  }
}

# Initialize guest OS (separate Terraform resource)
# Note: Initialization may be handled by Terraform provider differently
# This is a conceptual example
resource "aether_vm_initialization" "web" {
  target_host = "hyperv01"
  vm_id       = aether_vm.web.id
  
  local_admin = {
    username = "admin"
    password = var.admin_password
  }
  
  domain_join = {
    domain   = "corp.example.com"
    username = "CORP\\svc_join"
    password = var.domain_password
    ou       = "OU=Servers,DC=corp,DC=example,DC=com"
  }
  
  network_config = {
    ip_address    = "192.168.1.50"
    prefix_length = 24
    gateway       = "192.168.1.1"
    dns_servers   = ["192.168.1.10", "192.168.1.11"]
  }
}
```

## Summary

**Architecture**: 3 component schemas with metadata-based filtering
**Guest Config Location**: In vm-create and nic-create schemas with `guest_config: true`
**Form Rendering**: All fields in schemas drive UI
**Orchestration**: Hardware first, then guest configuration
**Future-Proof**: IP settings stay with NICs for multi-NIC support
**Simple for Users**: Managed deployment handles orchestration
**Flexible for Terraform**: Component APIs work independently

This architecture balances simplicity (3 schemas), flexibility (multi-NIC support), and proper separation (hardware vs. guest config).
