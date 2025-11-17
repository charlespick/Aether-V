# 4-Step Architecture: Infrastructure + Guest Configuration

## Overview

The VM provisioning system has been restructured from a monolithic approach into a 4-step orchestration that properly separates infrastructure provisioning from guest OS configuration.

## The Problem

The original architecture had a critical flaw:

```
❌ Original (Broken):
VM Creation → Returns
  ├─ Hardware: CPU, RAM, Disk, NIC ✓
  ├─ Guest Config: Hostname, IP, Domain Join ✓
  └─ Problem: If this step returns, how do we add more disks/NICs?
      └─ We can't! Guest config was already injected.
```

**The Issue**: Guest configuration (hostname, IP settings, domain join credentials) must be injected via provisioning ISO BEFORE the VM starts. But if the VM creation step completes and returns (so we can get the VM ID for subsequent disk/NIC operations), we've already lost the opportunity to inject that configuration.

## The Solution

Separate infrastructure from configuration with a 4-step orchestration:

```
✅ New (Fixed):

Step 1: Create VM (Hardware Only)
  └─ CPU, RAM, Generation, Image → vm_id

Step 2: Create Disk
  └─ Attach to vm_id → disk_id

Step 3: Create NIC
  └─ Attach to vm_id → nic_id

Step 4: Initialize VM (Guest Configuration)
  └─ Inject hostname, IP, domain join → provisioning_key
```

## Architecture Details

### Step 1: Create VM (Hardware Only)

**Schema**: `vm-create.yaml`
**Script**: `Invoke-CreateVmJob.ps1`
**Fields**:
- vm_name
- image_name
- gb_ram
- cpu_cores
- storage_class
- vm_clustered

**NOT Included**:
- ❌ Local administrator credentials
- ❌ Domain join settings
- ❌ Ansible configuration
- ❌ IP address settings

**Output**: VM ID from Hyper-V

### Step 2: Create Disk

**Schema**: `disk-create.yaml`
**Script**: `Invoke-CreateDiskJob.ps1`
**Fields**:
- vm_id (from step 1)
- disk_size_gb
- storage_class
- disk_type
- controller_type

**Output**: Disk ID

### Step 3: Create NIC

**Schema**: `nic-create.yaml`
**Script**: `Invoke-CreateNicJob.ps1`
**Fields**:
- vm_id (from step 1)
- network
- adapter_name

**NOT Included**:
- ❌ IP address
- ❌ Subnet mask
- ❌ Gateway
- ❌ DNS servers

**Output**: NIC ID

### Step 4: Initialize VM (Guest Configuration)

**Schema**: `vm-initialize.yaml` (INTERNAL - not exposed as resource)
**Script**: `Invoke-InitializeVmJob.ps1`
**Fields**:
- vm_id (from step 1)
- vm_name (for hostname)
- guest_la_uid (local admin username)
- guest_la_pw (local admin password)
- guest_domain_jointarget (domain FQDN)
- guest_domain_joinuid (domain join account)
- guest_domain_joinpw (domain join password)
- guest_domain_joinou (OU path)
- cnf_ansible_ssh_user (ansible username)
- cnf_ansible_ssh_key (ansible SSH key)
- guest_v4_ipaddr (IP address)
- guest_v4_cidrprefix (subnet mask)
- guest_v4_defaultgw (gateway)
- guest_v4_dns1 (primary DNS)
- guest_v4_dns2 (secondary DNS)
- guest_net_dnssuffix (DNS suffix)

**Process**:
1. Creates provisioning ISO with all guest configuration
2. Attaches ISO to VM
3. Starts VM
4. Waits for guest OS to pick up provisioning data
5. Guest OS applies configuration (hostname, IP, domain join, etc.)
6. Returns provisioning key when complete
7. Removes provisioning ISO

**Output**: Provisioning key

## Managed Deployment Orchestration

The managed deployment endpoint (`POST /api/v1/managed-deployments`) orchestrates all 4 steps server-side:

### User Input

User provides a single unified form with fields from all schemas:
- VM hardware fields (from vm-create)
- Disk fields (from disk-create)
- Network fields (from nic-create)
- Guest config fields (from vm-initialize)

### Server Processing

```python
# Separate fields by purpose
vm_hardware = {vm_name, image_name, gb_ram, cpu_cores, ...}
guest_config = {guest_la_uid, guest_la_pw, guest_domain_*, cnf_ansible_*, guest_v4_*, ...}

# Step 1: Create VM (hardware only)
vm_id = Invoke-CreateVmJob(vm_hardware)

# Step 2: Create disk (if disk_size_gb provided)
if disk_size_gb:
    disk_id = Invoke-CreateDiskJob({vm_id, disk_size_gb, ...})

# Step 3: Create NIC (if network provided)
if network:
    nic_id = Invoke-CreateNicJob({vm_id, network, ...})

# Step 4: Initialize VM (with held guest config)
if guest_config:
    provisioning_key = Invoke-InitializeVmJob({vm_id, vm_name, ...guest_config})
```

### Key Insight

Guest configuration fields are **held** during steps 1-3, then passed to step 4. This allows:
- Infrastructure to be built first (VM, disk, NIC)
- Guest configuration to be injected afterward
- Proper dependency order respected

## Schema Composition

### Frontend

The frontend fetches 4 schemas and composes them into a single form:

```javascript
const [vmSchema, diskSchema, nicSchema, initSchema] = await Promise.all([
    fetch('/api/v1/schema/vm-create'),
    fetch('/api/v1/schema/disk-create'),
    fetch('/api/v1/schema/nic-create'),
    fetch('/api/v1/schema/vm-initialize'),
]);

const composedSchema = {
    fields: [
        ...vmSchema.fields,
        ...diskSchema.fields (exclude vm_id),
        ...nicSchema.fields (exclude vm_id, adapter_name),
        ...initSchema.fields (exclude vm_id, vm_name)
    ]
};
```

### Server

The server validates against the composed schema:

```python
def get_job_schema():
    vm = load_schema_by_id("vm-create")
    disk = load_schema_by_id("disk-create")
    nic = load_schema_by_id("nic-create")
    init = load_schema_by_id("vm-initialize")
    
    # Compose fields, excluding internal IDs
    return {
        "fields": [
            ...vm.fields,
            ...disk.fields (exclude vm_id),
            ...nic.fields (exclude vm_id),
            ...init.fields (exclude vm_id, vm_name)
        ]
    }
```

## Component APIs vs. Managed Deployment

### Component APIs (For Terraform)

Users can call each API independently:

```bash
# Step 1: Create VM
POST /api/v1/resources/vms
{
  "vm_name": "app-01",
  "gb_ram": 8,
  "cpu_cores": 4
}
→ Returns: {job_id, vm_id}

# Step 2: Create disk
POST /api/v1/resources/disks
{
  "vm_id": "<from-step-1>",
  "disk_size_gb": 500
}
→ Returns: {job_id, disk_id}

# Step 3: Create NIC
POST /api/v1/resources/nics
{
  "vm_id": "<from-step-1>",
  "network": "Production"
}
→ Returns: {job_id, nic_id}

# Step 4: Initialize (NOT EXPOSED - use managed deployment for this)
```

**Note**: VM initialization is NOT exposed as a standalone resource API. It's only available through managed deployment orchestration.

### Managed Deployment (For Simple Workflows)

Single API call that orchestrates all 4 steps:

```bash
POST /api/v1/managed-deployments
{
  "vm_name": "app-01",
  "gb_ram": 8,
  "cpu_cores": 4,
  "disk_size_gb": 500,
  "network": "Production",
  "guest_la_uid": "Administrator",
  "guest_la_pw": "SecurePass123!",
  "guest_v4_ipaddr": "192.168.1.100",
  ...
}
→ Returns: {job_id}
```

Server internally orchestrates all 4 steps.

## Why Not Expose Initialization as a Resource?

The vm-initialize schema is **internal only** and not exposed as a standalone resource API for several reasons:

1. **Not a Hardware Resource**: It's not a persistent resource like VM/disk/NIC. It's a one-time configuration operation.

2. **Complex Dependencies**: Requires VM to be fully built (with disk and NIC) before initialization can run.

3. **Terraform Use Case**: Terraform users would use the component APIs to build infrastructure, then use a different tool (like cloud-init, Ansible, etc.) for guest configuration. They wouldn't call an initialization API.

4. **Managed Deployment Simplicity**: For simple workflows (managed deployment), the initialization is automatic. Users don't need to think about it as a separate step.

5. **Avoid Confusion**: Having an "initialize VM" resource would confuse users. It's better to keep it as an internal orchestration detail.

## Benefits of This Architecture

✅ **Clean Separation**: Infrastructure (VM/disk/NIC) vs. Configuration (guest OS)

✅ **Proper Timing**: Guest config injected at the right moment (after infrastructure, before VM starts)

✅ **Terraform Support**: Components can be created independently

✅ **Managed Deployment**: Simple workflows still get everything in one API call

✅ **Extensibility**: Can add more disks/NICs after initial creation without losing guest config

✅ **No Schema Confusion**: vm-initialize is internal, not a user-facing resource

## Migration from Old System

### Old System (Removed)

```
POST /api/v1/jobs/provision
→ Uses Invoke-ProvisioningJob.ps1 (monolithic script)
→ Creates VM + disk + NIC + guest config in one PowerShell script
→ Schema: job-inputs.yaml (all fields mixed together)
```

### New System

```
POST /api/v1/managed-deployments
→ Orchestrates 4 PowerShell scripts server-side
→ Step 1: Invoke-CreateVmJob.ps1 (hardware)
→ Step 2: Invoke-CreateDiskJob.ps1 (disk)
→ Step 3: Invoke-CreateNicJob.ps1 (NIC)
→ Step 4: Invoke-InitializeVmJob.ps1 (guest config)
→ Schema: Composed from 4 schemas (vm-create + disk-create + nic-create + vm-initialize)
```

### Key Differences

| Aspect | Old | New |
|--------|-----|-----|
| PowerShell | 1 monolithic script | 4 focused scripts |
| Schema | 1 mixed schema | 4 component schemas |
| Orchestration | Agent-side (PowerShell) | Server-side (Python) |
| Extensibility | Cannot add resources | Can add disk/NIC later |
| Separation | Mixed hardware + config | Clean separation |

## Implementation Status

### ✅ Complete

- vm-create schema (hardware only)
- disk-create schema (hardware only)
- nic-create schema (hardware only)
- vm-initialize schema (guest config)
- Invoke-CreateVmJob.ps1 (VM creation)
- Invoke-CreateDiskJob.ps1 (disk creation)
- Invoke-CreateNicJob.ps1 (NIC creation)
- Invoke-InitializeVmJob.ps1 (guest initialization)
- Managed deployment orchestration
- Frontend schema composition
- Server validation

### ⏳ TODO

- VM ID parsing from PowerShell JSON output
- Complete end-to-end testing
- Update documentation
- Add integration tests

## Summary

The 4-step architecture solves a critical flaw in the original design by separating infrastructure provisioning from guest configuration. This allows for:

1. **Proper dependency order**: VM → disk → NIC → initialize
2. **Clean separation**: Hardware vs. software configuration
3. **Terraform support**: Components can be created independently
4. **Simple workflows**: Managed deployment handles everything
5. **Extensibility**: Can add resources without breaking guest config

The vm-initialize step is internal to managed deployment orchestration and not exposed as a standalone resource, keeping the API surface simple and focused on persistent infrastructure resources.
