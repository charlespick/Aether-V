# Phase 0: Schema Usage Inventory

## Purpose

This document provides a complete inventory of the current schema-driven system in Aether-V. It identifies all schema files, their consumers, dependencies on auto-composition, and how guest configuration is derived. This serves as the baseline reference for the upcoming refactor from YAML schemas to Pydantic models.

**Created:** 2025-11-21  
**Status:** Phase 0 - Groundwork (No Behavior Changes)

---

## 1. Schema Files

### 1.1 vm-create.yaml

**Location:** `/Schemas/vm-create.yaml`

**Purpose:** Defines the schema for creating a new virtual machine, including both hardware properties and guest configuration.

**Fields (17 total):**

#### Hardware Fields (sent to host agent):
- `vm_name` - VM name (string, required, 1-64 chars)
- `gb_ram` - Memory in GB (integer, required, default: 4, range: 1-512)
- `cpu_cores` - vCPU count (integer, required, default: 2, range: 1-64)
- `storage_class` - Storage class name (string, optional)
- `vm_clustered` - Add to failover cluster (boolean, optional, default: false)

#### Guest Configuration Fields (held for initialization, marked with `guest_config: true`):
- `guest_la_uid` - Local administrator username (string, required)
- `guest_la_pw` - Local administrator password (secret, required)
- `guest_domain_jointarget` - Domain FQDN (string, optional)
- `guest_domain_joinuid` - Domain join account (string, optional)
- `guest_domain_joinpw` - Domain join password (secret, optional)
- `guest_domain_joinou` - Domain join OU (string, optional)
- `cnf_ansible_ssh_user` - Ansible SSH user (string, optional)
- `cnf_ansible_ssh_key` - Ansible SSH public key (multiline, optional)

**Parameter Sets:**
1. `domain-join` - All-or-none: requires all domain join fields together
2. `ansible-config` - All-or-none: requires ansible user and SSH key together

---

### 1.2 disk-create.yaml

**Location:** `/Schemas/disk-create.yaml`

**Purpose:** Defines the schema for creating and attaching a virtual disk to an existing VM.

**Fields (6 total):**

#### Hardware Fields (all sent to host agent):
- `vm_id` - Target VM Hyper-V ID (string, required, 36 chars - UUID format)
- `image_name` - Base image to clone (string, optional)
- `disk_size_gb` - Disk size in GB (integer, optional, default: 100, range: 1-65536)
- `storage_class` - Storage class name (string, optional)
- `disk_type` - Disk type: Dynamic or Fixed (string, optional, default: "Dynamic")
- `controller_type` - Controller type: SCSI or IDE (string, optional, default: "SCSI")

**Parameter Sets:** None

**Note:** When used in managed deployments, `vm_id` is excluded from form and added dynamically during orchestration.

---

### 1.3 nic-create.yaml

**Location:** `/Schemas/nic-create.yaml`

**Purpose:** Defines the schema for creating and attaching a network adapter to an existing VM, including both hardware and guest IP configuration.

**Fields (11 total):**

#### Hardware Fields (sent to host agent):
- `vm_id` - Target VM Hyper-V ID (string, required, 36 chars - UUID format)
- `network` - Network name to connect to (string, required)
- `adapter_name` - Network adapter name (string, optional)

#### Guest Configuration Fields (held for initialization, marked with `guest_config: true`):
- `guest_v4_ipaddr` - Static IPv4 address (ipv4, optional)
- `guest_v4_cidrprefix` - IPv4 prefix length (integer, optional)
- `guest_v4_defaultgw` - Default gateway (ipv4, optional)
- `guest_v4_dns1` - Primary DNS server (ipv4, optional)
- `guest_v4_dns2` - Secondary DNS server (ipv4, optional)
- `guest_net_dnssuffix` - DNS search suffix (string, optional)

**Parameter Sets:**
1. `static-ip-config` - All-or-none: requires ipaddr, cidr prefix, gateway, and DNS1 together

**Note:** When used in managed deployments, `vm_id` is excluded from form and added dynamically during orchestration.

---

## 2. Schema Consumers

### 2.1 Server-Side Components

#### Python Server (`server/app/`)

**Core Schema Processing:**

1. **`core/job_schema.py`**
   - `load_schema_by_id(schema_id)` - Loads and caches schema files
   - `load_job_schema(path)` - Validates schema structure and field definitions
   - `get_job_schema()` - Composes unified schema from vm-create, disk-create, nic-create
   - `validate_job_submission(values, schema)` - Validates user input against schema
   - `get_sensitive_field_ids(schema)` - Identifies secret fields for redaction
   - `redact_job_parameters(parameters, schema)` - Redacts sensitive values for logging

2. **`api/routes.py`**
   - `/api/v1/vms/create` - Loads vm-create schema, validates submission
   - `/api/v1/vms/update` - Loads vm-create schema, validates submission
   - `/api/v1/disks/create` - Loads disk-create schema, validates submission
   - `/api/v1/disks/update` - Loads disk-create schema, validates submission
   - `/api/v1/nics/create` - Loads nic-create schema, validates submission
   - `/api/v1/nics/update` - Loads nic-create schema, validates submission
   - `/api/v1/jobs/deploy` - Composes schema from all three component schemas
   - `/api/v1/schema/{schema_id}` - Serves schema JSON to frontend

3. **`services/job_service.py`**
   - `_execute_managed_deployment_job()` - Loads all three schemas to separate:
     - VM hardware fields vs. VM guest config fields (via `guest_config: true` flag)
     - NIC hardware fields vs. NIC guest config fields (via `guest_config: true` flag)
     - Disk fields (no guest config)
   - Creates separate child jobs for VM, disk, and NIC hardware
   - Creates initialization job with all guest config fields combined

**Schema Usage Pattern:**
```python
# Load schema
schema = load_schema_by_id("vm-create")

# Validate user input
validated_values = validate_job_submission(request.values, schema)

# Separate hardware from guest config (in managed deployment)
vm_hardware_fields = {}
vm_guest_config_fields = {}
for field in vm_schema.get("fields", []):
    if field.get("guest_config", False):
        vm_guest_config_fields[field_id] = fields[field_id]
    else:
        vm_hardware_fields[field_id] = fields[field_id]
```

---

### 2.2 Frontend Components

#### JavaScript UI (`server/app/static/overlay.js`)

**Schema Composition:**

The `ProvisionJobOverlay` class in `overlay.js` implements client-side schema composition for the managed deployment form:

```javascript
// Fetch all three component schemas
const [vmSchema, diskSchema, nicSchema] = await Promise.all([
    fetch('/api/v1/schema/vm-create').then(r => r.json()),
    fetch('/api/v1/schema/disk-create').then(r => r.json()),
    fetch('/api/v1/schema/nic-create').then(r => r.json()),
]);

// Compose a single schema from the three component schemas
const composedSchema = {
    version: vmSchema.version,
    fields: [
        ...vmSchema.fields,
        ...diskSchema.fields.filter(f => f.id !== 'vm_id'),
        ...nicSchema.fields.filter(f => f.id !== 'vm_id')
    ],
    parameter_sets: [
        ...(vmSchema.parameter_sets || []),
        ...(diskSchema.parameter_sets || []),
        ...(nicSchema.parameter_sets || [])
    ]
};
```

**Form Rendering:**

The UI dynamically generates form fields based on schema metadata:
- Field labels from `field.label`
- Field descriptions from `field.description`
- Field hints from `field.hint`
- Input types from `field.type` (string, integer, boolean, secret, multiline, ipv4, hostname)
- Validation from `field.validations` (min_length, max_length, minimum, maximum, pattern)
- Required vs. optional from `field.required`
- Default values from `field.default`

**No Conditional Rendering:**

The current UI does NOT implement:
- Conditional field visibility based on other field values
- Dynamic tabs or sections
- Show/hide logic for parameter sets

All fields are rendered statically. The backend validates parameter set constraints after submission.

---

### 2.3 PowerShell Host Agents

**Location:** `/Powershell/Invoke-*Job.ps1`

The PowerShell host agents do NOT directly read or parse the YAML schemas. Instead:

1. They receive a **job request envelope** via STDIN as JSON
2. The envelope contains:
   - `operation` field (e.g., "vm.create", "disk.create")
   - `fields` object with validated values from the schema
   - Metadata (correlation_id, timestamps, etc.)

3. They execute Hyper-V operations based on the fields provided
4. They return a **job result envelope** as JSON with:
   - `status` ("success", "error", "partial")
   - `code` (machine-readable error code)
   - `message` (human-readable description)
   - `data` (created object IDs, resolved paths, etc.)
   - `logs` (debug output lines)

**Example PowerShell Scripts:**
- `Invoke-CreateVmJob.ps1` - Creates VM from validated hardware fields
- `Invoke-CreateDiskJob.ps1` - Creates and attaches disk
- `Invoke-CreateNicJob.ps1` - Creates and attaches NIC
- `Invoke-InitializeVmJob.ps1` - Publishes guest config via KVP

The host agents operate on the **output** of schema validation, not the schemas themselves.

---

## 3. Auto-Composition Dependencies

### 3.1 Managed Deployment Composition

**Location:** `services/job_service.py::_execute_managed_deployment_job()`

The managed deployment workflow uses **runtime schema composition** to:

1. **Load** all three schemas (vm-create, disk-create, nic-create)
2. **Separate** fields by type:
   - VM hardware vs. VM guest config (using `guest_config: true` marker)
   - NIC hardware vs. NIC guest config (using `guest_config: true` marker)
   - Disk fields (no guest config)

3. **Create child jobs** for each component:
   - VM creation job (hardware fields only)
   - Disk creation job (if image_name or disk_size_gb provided)
   - NIC creation job (hardware fields only, if network provided)
   - VM initialization job (all guest config fields combined)

4. **Orchestrate** sequential execution:
   - Create VM → get VM ID
   - Create disk (if needed) → attach to VM ID
   - Create NIC (if needed) → attach to VM ID
   - Initialize VM with guest config (if needed)

**Auto-composition logic:**
```python
# Automatically extract VM hardware fields
vm_hardware_fields = {}
for field in vm_schema.get("fields", []):
    if field_id in fields and not field.get("guest_config", False):
        vm_hardware_fields[field_id] = fields[field_id]

# Automatically extract VM guest config fields
vm_guest_config_fields = {}
for field in vm_schema.get("fields", []):
    if field_id in fields and field.get("guest_config", False):
        vm_guest_config_fields[field_id] = fields[field_id]
```

This composition is **implicit** - there's no explicit configuration stating which fields belong to which operation. The `guest_config: true` marker is the only hint.

---

### 3.2 Frontend Schema Composition

**Location:** `server/app/static/overlay.js::fetchSchema()`

The frontend auto-composes a unified schema for the deployment form:

1. **Fetches** all three component schemas via API
2. **Merges** field arrays (excluding duplicate vm_id fields)
3. **Merges** parameter_sets arrays
4. **Caches** the composed schema globally as `window.jobSchema`

This composed schema is used to:
- Render the unified deployment form
- Display all VM, disk, and NIC fields in a single interface
- Provide field metadata for client-side validation hints

**Frontend does NOT:**
- Know about `guest_config: true` markers
- Separate hardware vs. guest config fields
- Implement conditional visibility based on field values

---

## 4. Guest Configuration Derivation

### 4.1 Current Derivation Logic

**Location:** `services/job_service.py::_execute_managed_deployment_job()`

Guest configuration is derived **at orchestration time** by:

1. **Loading** vm-create and nic-create schemas
2. **Filtering** fields marked with `guest_config: true`
3. **Extracting** values for those fields from the user submission
4. **Combining** VM and NIC guest config fields into a single dictionary
5. **Passing** to the initialization job

**Code:**
```python
vm_guest_config_fields = {}
for field in vm_schema.get("fields", []):
    field_id = field.get("id")
    if field_id in fields:
        if field.get("guest_config", False):
            vm_guest_config_fields[field_id] = fields[field_id]

nic_guest_config_fields = {}
for field in nic_schema.get("fields", []):
    field_id = field.get("id")
    if field_id in fields:
        if field.get("guest_config", False):
            nic_guest_config_fields[field_id] = fields[field_id]

all_guest_config_fields = {**vm_guest_config_fields, **nic_guest_config_fields}

if all_guest_config_fields:
    init_fields = {
        "vm_id": vm_id,
        "vm_name": vm_name,
        **all_guest_config_fields,
    }
```

---

### 4.2 Guest Config Fields by Schema

**vm-create schema:**
- `guest_la_uid`
- `guest_la_pw`
- `guest_domain_jointarget`
- `guest_domain_joinuid`
- `guest_domain_joinpw`
- `guest_domain_joinou`
- `cnf_ansible_ssh_user`
- `cnf_ansible_ssh_key`

**nic-create schema:**
- `guest_v4_ipaddr`
- `guest_v4_cidrprefix`
- `guest_v4_defaultgw`
- `guest_v4_dns1`
- `guest_v4_dns2`
- `guest_net_dnssuffix`

**disk-create schema:**
- (No guest config fields)

---

### 4.3 Guest Config Delivery

**Location:** `Powershell/Provisioning.PublishProvisioningData.ps1`

Once the initialization job receives the guest config:

1. The Python server constructs a JSON payload with all guest config fields
2. The payload is **encrypted** using a VM-specific key
3. The encrypted payload is sent to `Invoke-InitializeVmJob.ps1`
4. The PowerShell script publishes the encrypted data via **Hyper-V KVP** (Key-Value Pair exchange)
5. The guest agent running inside the VM:
   - Retrieves the encrypted data from KVP
   - Decrypts it using the VM-specific key
   - Applies the configuration (networking, domain join, SSH keys, etc.)

**Key Points:**
- Guest config is **not** sent to the host agent's VM creation script
- Guest config is **isolated** to the initialization step
- The separation is driven entirely by the `guest_config: true` marker in the schema

---

## 5. Schema Dependency Graph

```
User Input (via UI or API)
        ↓
validate_job_submission(values, schema)
        ↓
Validated Fields Dictionary
        ↓
    ┌───────────────────────┴──────────────────────┐
    │                                              │
Managed Deployment                          Standalone Operations
    │                                              │
    ├─ Load vm-create schema                       ├─ VM Create: load vm-create
    ├─ Load disk-create schema                     ├─ VM Update: load vm-create
    ├─ Load nic-create schema                      ├─ Disk Create: load disk-create
    │                                              ├─ Disk Update: load disk-create
    ├─ Separate fields by guest_config flag        ├─ NIC Create: load nic-create
    │   ├─ VM hardware                             └─ NIC Update: load nic-create
    │   ├─ VM guest config                              │
    │   ├─ NIC hardware                                 ↓
    │   ├─ NIC guest config                    Send to host agent
    │   └─ Disk fields (all hardware)                   │
    │                                                    ↓
    ├─ Create child jobs:                       PowerShell script
    │   ├─ VM creation (hardware only)                  │
    │   ├─ Disk creation (if needed)                    ↓
    │   └─ NIC creation (hardware only)          Execute Hyper-V cmdlet
    │                                                    │
    └─ Create init job (all guest config)               ↓
            ↓                                    Job Result JSON
    Publish to VM via KVP                                │
            ↓                                            ↓
    Guest agent receives config              Return to Python server
            ↓                                            │
    Apply inside VM                                      ↓
                                            Update job status
                                                         │
                                                         ↓
                                            Return to API client
```

---

## 6. Key Findings and Implications

### 6.1 Schema-Driven Auto-Composition

**Current State:**
- The `guest_config: true` marker is the **only** mechanism separating hardware from guest configuration
- No explicit data model defines this separation
- Composition logic is **scattered** across:
  - `job_service.py` (orchestration)
  - `overlay.js` (frontend composition)
  - `job_schema.py` (unified schema generation)

**Implication for Refactor:**
- Must preserve the hardware/guest-config split in Pydantic models
- Should make this split **explicit** in the data model
- Should eliminate the need for runtime schema introspection

---

### 6.2 Frontend Schema Dependency

**Current State:**
- Frontend **fetches** schemas at runtime to render forms
- Frontend **merges** three schemas client-side for managed deployment
- All field metadata (labels, hints, types) comes from schema

**Implication for Refactor:**
- Frontend still needs field metadata
- Options:
  1. Generate JSON metadata from Pydantic models (via OpenAPI/FastAPI auto-docs)
  2. Continue serving schema-like JSON for backward compatibility
  3. Replace with explicit frontend forms (no auto-generation)

---

### 6.3 Validation Duplication

**Current State:**
- Schema defines field types, ranges, required/optional
- Pydantic models exist in `core/models.py` but are **not used** for job validation
- Schema validation in `job_schema.py` is **separate** from model validation

**Implication for Refactor:**
- Can eliminate duplicate validation logic
- Pydantic models should become the single source of truth
- FastAPI can auto-generate OpenAPI docs from Pydantic models

---

### 6.4 No Conditional UI Logic

**Current State:**
- Frontend renders all fields statically
- No show/hide logic for parameter sets
- No tabs or conditional sections

**Implication for Refactor:**
- TechDoc specifies that frontend should own conditional rendering
- This is a **future enhancement**, not Phase 0
- Phase 0 only needs to **document** this gap

---

## 7. Summary

### Schema Files
- **3 total:** vm-create.yaml, disk-create.yaml, nic-create.yaml
- **34 total fields** (17 VM + 6 disk + 11 NIC)
- **13 guest config fields** (8 VM + 5 NIC + 0 disk)

### Consumers
- **Python server:** 6 files reference schemas
  - `core/job_schema.py` - schema loading and validation
  - `api/routes.py` - API endpoints
  - `services/job_service.py` - orchestration logic
- **Frontend:** 1 file implements schema composition
  - `static/overlay.js` - ProvisionJobOverlay class
- **PowerShell agents:** 0 files read schemas directly
  - Agents consume validated field dictionaries, not schemas

### Auto-Composition
- **Backend:** Managed deployment orchestrates VM + disk + NIC creation via child jobs
- **Backend:** Guest config separation uses `guest_config: true` marker
- **Frontend:** Unified deployment form merges three schemas client-side

### Guest Configuration
- **Derived** at orchestration time by filtering fields marked `guest_config: true`
- **Delivered** via encrypted KVP to guest agent after VM creation
- **Applied** by guest agent inside VM (no host agent involvement)

---

**Next Steps (Phase 0):**
- ✅ Complete schema inventory (this document)
- ⬜ Create baseline integration test suite
- ⬜ Add logging for server↔agent communication
- ⬜ Write internal docs describing current flow

