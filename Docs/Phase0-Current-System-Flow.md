# Phase 0: Current Schema-Driven System Flow

## Purpose

This document describes the current schema-driven system's workflow and architecture in Aether-V. It serves as the reference point during the transition from YAML schemas to Pydantic models, capturing the exact behavior that must be preserved.

**Created:** 2025-11-21  
**Status:** Phase 0 - Baseline Documentation  
**Related:** See `Phase0-Schema-Inventory.md` for detailed schema usage inventory

---

## 1. High-Level Architecture

```
┌─────────────────────┐
│   Frontend (JS)     │  Fetches schemas via API
│   - overlay.js      │  Composes VM+Disk+NIC schemas
│   - views.js        │  Renders dynamic forms
└──────────┬──────────┘
           │ POST /api/v1/jobs/deploy
           │ (or individual resource endpoints)
           ↓
┌─────────────────────┐
│  Python Server      │  Validates via YAML schemas
│  FastAPI + Pydantic │  Orchestrates child jobs
│  - routes.py        │  Separates hardware/guest config
│  - job_service.py   │  Sends JSON to host agents
└──────────┬──────────┘
           │ JSON via WinRM/PowerShell
           ↓
┌─────────────────────┐
│ PowerShell Agents   │  Execute Hyper-V operations
│ (Bundled in image) │  Return structured results
│ - Invoke-*Job.ps1   │
└─────────────────────┘
```

---

## 2. Request Flow: Managed Deployment

This is the most complex workflow, involving orchestration of multiple resource types.

### 2.1 Frontend Composition

**File:** `server/app/static/overlay.js::fetchSchema()`

```javascript
// 1. Fetch three component schemas
const [vmSchema, diskSchema, nicSchema] = await Promise.all([
    fetch('/api/v1/schema/vm-create'),
    fetch('/api/v1/schema/disk-create'),
    fetch('/api/v1/schema/nic-create'),
]);

// 2. Merge fields (excluding duplicate vm_id from disk/nic)
const composedSchema = {
    fields: [
        ...vmSchema.fields,
        ...diskSchema.fields.filter(f => f.id !== 'vm_id'),
        ...nicSchema.fields.filter(f => f.id !== 'vm_id')
    ],
    parameter_sets: [...vmSchema.parameter_sets, ...diskSchema.parameter_sets, ...nicSchema.parameter_sets]
};

// 3. Render single unified form with all fields
renderForm(composedSchema);
```

**Behavior:**
- Single form contains all VM, disk, and NIC fields
- No conditional rendering (all fields visible regardless of selection)
- User fills in whatever fields they want
- Frontend submits all filled fields as single JSON payload

---

### 2.2 Backend Validation

**File:** `server/app/api/routes.py`

**Endpoint:** `POST /api/v1/jobs/deploy`

```python
# 1. Compose schema on server side (same as frontend)
from app.core.job_schema import get_job_schema
composed_schema = get_job_schema()  # Loads and merges vm/disk/nic schemas

# 2. Validate user input against composed schema
validated = validate_job_submission(submission.values, composed_schema)

# 3. Submit as managed_deployment job
job = await job_service.submit_resource_job(
    job_type="managed_deployment",
    schema_id="managed-deployment",
    payload={
        "schema": {
            "id": "managed-deployment",
            "version": 1,
            "components": {"vm-create": 1, "disk-create": 1, "nic-create": 1}
        },
        "fields": validated
    },
    target_host=submission.target_host
)
```

**Validation Rules Applied:**
- Type checking (string, integer, boolean, ipv4, etc.)
- Range validation (min/max for integers, min_length/max_length for strings)
- Required field enforcement
- Parameter set validation (all-or-none for domain join, static IP, etc.)
- Sensitive field identification (type: secret)

---

### 2.3 Orchestration

**File:** `server/app/services/job_service.py::_execute_managed_deployment_job()`

```python
# 1. Load all three schemas
vm_schema = load_schema_by_id("vm-create")
disk_schema = load_schema_by_id("disk-create")
nic_schema = load_schema_by_id("nic-create")

# 2. Separate VM fields by guest_config marker
vm_hardware_fields = {}
vm_guest_config_fields = {}
for field in vm_schema.get("fields", []):
    field_id = field.get("id")
    if field_id in fields:
        if field.get("guest_config", False):
            vm_guest_config_fields[field_id] = fields[field_id]
        else:
            vm_hardware_fields[field_id] = fields[field_id]

# 3. Separate NIC fields by guest_config marker
nic_hardware_fields = {}
nic_guest_config_fields = {}
for field in nic_schema.get("fields", []):
    field_id = field.get("id")
    if field_id in fields:
        if field.get("guest_config", False):
            nic_guest_config_fields[field_id] = fields[field_id]
        elif field_id != "vm_id":
            nic_hardware_fields[field_id] = fields[field_id]

# 4. Extract disk fields (no guest_config in disk schema)
disk_fields = {}
for field in disk_schema.get("fields", []):
    field_id = field.get("id")
    if field_id == "vm_id":
        continue
    if field_id in fields:
        disk_fields[field_id] = fields[field_id]

# 5. Create child jobs in sequence
# a. Create VM (hardware only)
vm_job = await self._queue_child_job(
    parent_job, "create_vm", "vm-create",
    {"schema": {"id": "vm-create", "version": 1}, "fields": vm_hardware_fields}
)
vm_result = await self._wait_for_child_job_completion(parent_job.job_id, vm_job.job_id)
vm_id = self._extract_vm_id_from_output(vm_result.output)

# b. Create disk (if image or size provided)
if disk_fields.get("image_name") or disk_fields.get("disk_size_gb"):
    disk_fields["vm_id"] = vm_id
    disk_job = await self._queue_child_job(
        parent_job, "create_disk", "disk-create",
        {"schema": {"id": "disk-create", "version": 1}, "fields": disk_fields}
    )
    await self._wait_for_child_job_completion(parent_job.job_id, disk_job.job_id)

# c. Create NIC (if network provided)
if nic_hardware_fields.get("network"):
    nic_hardware_fields["vm_id"] = vm_id
    nic_job = await self._queue_child_job(
        parent_job, "create_nic", "nic-create",
        {"schema": {"id": "nic-create", "version": 1}, "fields": nic_hardware_fields}
    )
    await self._wait_for_child_job_completion(parent_job.job_id, nic_job.job_id)

# d. Initialize VM with guest config (if any guest_config fields provided)
all_guest_config = {**vm_guest_config_fields, **nic_guest_config_fields}
if all_guest_config:
    init_fields = {"vm_id": vm_id, "vm_name": vm_name, **all_guest_config}
    init_job = await self._queue_child_job(
        parent_job, "initialize_vm", "initialize-vm",
        {"schema": {"id": "initialize-vm", "version": 1}, "fields": init_fields}
    )
    await self._wait_for_child_job_completion(parent_job.job_id, init_job.job_id)
```

**Key Orchestration Patterns:**

1. **Sequential Execution:**
   - VM created first (to get VM ID)
   - Disk and NIC created in parallel (both need VM ID)
   - Initialization last (needs VM to exist)

2. **Conditional Jobs:**
   - Disk job only if `image_name` OR `disk_size_gb` provided
   - NIC job only if `network` provided
   - Init job only if any `guest_config` fields provided

3. **Field Separation Logic:**
   - Runtime inspection of schema `guest_config: true` marker
   - Hardware fields → host agent
   - Guest config fields → initialization job

4. **Parent-Child Tracking:**
   - Parent job stores array of child job summaries
   - Each child updates parent on status change
   - Parent aggregates child statuses for overall progress

---

### 2.4 Child Job Execution

**File:** `server/app/services/job_service.py::_execute_create_vm_job()`

```python
# 1. Extract job definition
definition = job.parameters.get("definition", {})
fields = definition.get("fields", {})

# 2. Validate against host configuration
await self._validate_job_against_host_config(definition, target_host)

# 3. Build JSON payload
json_payload = await asyncio.to_thread(
    json.dumps, definition, ensure_ascii=False, separators=(",", ":")
)

# 4. Log outgoing JSON (Phase 0 addition)
self._log_agent_request(job.job_id, target_host, json_payload, "Invoke-CreateVmJob.ps1")

# 5. Build PowerShell command
command = self._build_agent_invocation_command("Invoke-CreateVmJob.ps1", json_payload)
# This encodes JSON as base64 and constructs: 
# $payload = [base64_decode]; $payload | & Invoke-CreateVmJob.ps1

# 6. Execute via WinRM with streaming output
exit_code = await self._execute_agent_command(job, target_host, command)

# 7. Stream processing captures:
# - Standard output lines (including JSON results)
# - Standard error lines
# - Exit code
```

---

### 2.5 PowerShell Agent Execution

**File:** `Powershell/Invoke-CreateVmJob.ps1`

```powershell
# 1. Receive JSON via STDIN
$InputObject = $Input | ConvertFrom-Json

# 2. Extract fields from JSON
$schema = $InputObject.schema
$fields = $InputObject.fields
$vmName = $fields.vm_name
$ramGB = $fields.gb_ram
$cpuCores = $fields.cpu_cores
# etc.

# 3. Execute Hyper-V operations
$vm = New-VM -Name $vmName -MemoryStartupBytes ($ramGB * 1GB) `
    -Generation 2 -BootDevice VHD

Set-VM -VM $vm -ProcessorCount $cpuCores

# 4. Construct result JSON
$result = @{
    status = "success"
    message = "VM '$vmName' created successfully"
    data = @{
        vm_id = $vm.Id.Guid
        vm_name = $vm.Name
    }
} | ConvertTo-Json -Compress

# 5. Write result to STDOUT
Write-Output $result
```

**Result Structure:**
```json
{
  "status": "success",
  "message": "VM 'my-vm' created successfully",
  "data": {
    "vm_id": "12345678-1234-1234-1234-123456789abc",
    "vm_name": "my-vm"
  }
}
```

---

### 2.6 Response Processing

**File:** `server/app/services/job_service.py::_handle_stream_chunk()`

```python
# 1. Stream decoder processes PowerShell output
decoder = _PowerShellStreamDecoder(...)
lines = decoder.push(payload)

# 2. For each output line:
for line in lines:
    # a. Log JSON responses (Phase 0 addition)
    if stream == "stdout" and line.strip().startswith('{'):
        logger.debug("Received JSON from host agent for job %s: %s", job_id, line)
    
    # b. Append to job output
    await self._append_job_output(job_id, line)
    
    # c. Call line callback (for VM ID extraction, etc.)
    if line_callback:
        line_callback(line)

# 3. VM ID extraction example
def _extract_vm_id_from_output(self, lines: List[str]) -> Optional[str]:
    for line in lines:
        if line.strip().startswith('{'):
            try:
                result = json.loads(line)
                return result.get("data", {}).get("vm_id")
            except json.JSONDecodeError:
                continue
    return None
```

---

## 3. Request Flow: Standalone Resource Operations

Simpler workflows for individual resource CRUD operations.

### 3.1 VM Creation (Standalone)

**Endpoint:** `POST /api/v1/vms/create`

```python
# 1. Load VM schema
schema = load_schema_by_id("vm-create")

# 2. Validate request
validated = validate_job_submission(request.values, schema)

# 3. Submit job directly (no orchestration)
job = await job_service.submit_resource_job(
    job_type="create_vm",
    schema_id="vm-create",
    payload={"schema": {"id": "vm-create", "version": 1}, "fields": validated},
    target_host=request.target_host
)
```

**Difference from Managed Deployment:**
- Single job (not orchestrated child jobs)
- All validated fields sent to agent (including guest_config fields)
- No automatic disk/NIC creation
- No automatic initialization

**Note:** In standalone mode, guest_config fields are still validated but NOT separated. The agent receives them and ignores them (because agent scripts only process hardware fields).

---

### 3.2 Disk Creation (Standalone)

**Endpoint:** `POST /api/v1/disks/create`

```python
# 1. Load disk schema
schema = load_schema_by_id("disk-create")

# 2. Validate (vm_id is required in standalone mode)
validated = validate_job_submission(request.values, schema)

# 3. Submit job
job = await job_service.submit_resource_job(
    job_type="create_disk",
    schema_id="disk-create",
    payload={"schema": {"id": "disk-create", "version": 1}, "fields": validated},
    target_host=request.target_host
)
```

**Key Point:** `vm_id` is required because there's no VM creation step to generate it.

---

### 3.3 NIC Creation (Standalone)

**Endpoint:** `POST /api/v1/nics/create`

Similar pattern to disk creation:
- `vm_id` required
- Hardware fields sent to agent
- Guest config fields validated but NOT separated or sent to init job

---

## 4. Schema Structure and Metadata

### 4.1 Schema File Format

```yaml
version: 1
id: vm-create
name: "Virtual machine creation"
description: "Schema for creating a new virtual machine..."

fields:
  - id: vm_name
    label: "VM name"
    description: "Unique name for the new virtual machine."
    hint: "Example: web-01"
    type: string
    required: true
    validations:
      min_length: 1
      max_length: 64
  
  - id: guest_la_pw
    label: "Local administrator password"
    description: "Password for the guest operating system's local administrator."
    type: secret
    required: true
    guest_config: true

parameter_sets:
  - id: domain-join
    name: "Domain join"
    description: "Configuration required to join the guest to an Active Directory domain."
    mode: all-or-none
    members:
      - guest_domain_jointarget
      - guest_domain_joinuid
      - guest_domain_joinpw
      - guest_domain_joinou
```

### 4.2 Field Type Mapping

| Schema Type | Python Validation | JavaScript Rendering |
|-------------|-------------------|----------------------|
| `string` | `str.strip()` | `<input type="text">` |
| `integer` | `int()` + range check | `<input type="number">` |
| `boolean` | `bool()` | `<input type="checkbox">` |
| `secret` | `str` + marked sensitive | `<input type="password">` |
| `multiline` | `str` (no strip) | `<textarea>` |
| `ipv4` | `ipaddress.IPv4Address()` | `<input type="text" pattern="...">` |
| `hostname` | Regex validation | `<input type="text">` |

### 4.3 Special Markers

**`guest_config: true`**
- Marks fields that configure the guest OS (not hypervisor)
- Used ONLY during managed deployment orchestration
- Filtered out from VM/NIC creation jobs
- Aggregated into initialization job

**`type: secret`**
- Marks fields as sensitive
- Logged as `••••••` in redacted outputs
- Still transmitted in full to agents (over encrypted WinRM)

**`required: true`**
- Field must be provided (non-empty)
- Enforced by `validate_job_submission()`
- Does NOT apply to fields with `default` value

**`default: <value>`**
- Applied if field missing or empty
- Happens during validation, before submission

---

## 5. Validation Strategy

### 5.1 Server-Side Validation

**File:** `server/app/core/job_schema.py::validate_job_submission()`

**Order of Operations:**

```python
def validate_job_submission(values, schema):
    # 1. Identify unknown fields
    field_ids = {f["id"] for f in schema["fields"]}
    unknown = set(values.keys()) - field_ids
    if unknown:
        raise SchemaValidationError(f"Unknown field(s): {', '.join(unknown)}")
    
    # 2. For each field in schema:
    for field_id, field in field_map.items():
        raw_value = values.get(field_id)
        
        # a. Check if missing
        if _is_missing(raw_value):
            if "default" in field:
                sanitized[field_id] = field["default"]
            elif field.get("required"):
                errors.append(f"Field '{field_id}' is required")
            continue
        
        # b. Coerce type and validate
        sanitized[field_id] = _coerce_and_validate(field, raw_value)
    
    # 3. Validate parameter sets
    for param_set in schema.get("parameter_sets", []):
        mode = param_set.get("mode")
        members = param_set.get("members")
        
        if mode == "all-or-none":
            provided = [m for m in members if not _is_missing(sanitized.get(m))]
            if provided and len(provided) != len(members):
                errors.append(f"Parameter set '{param_set['name']}' requires all members")
    
    # 4. Return only non-empty fields
    return {k: v for k, v in sanitized.items() if not _is_missing(v)}
```

**Parameter Set Validation:**

**Mode: `all-or-none`**
- All members must be provided together, or none
- Example: Domain join (target, uid, pw, ou)

**Mode: `variants`** (not currently used)
- One of several valid combinations must be provided
- Example: Could be used for "DHCP" vs "Static IP" (exclusive choice)

---

### 5.2 Host-Level Validation

**File:** `server/app/services/job_service.py::_validate_job_against_host_config()`

```python
async def _validate_job_against_host_config(self, definition, target_host):
    # 1. Load host configuration
    host_config = await host_resources_service.get_host_configuration(target_host)
    
    # 2. Validate network name
    network_name = fields.get("network")
    if network_name and not host_resources_service.validate_network_name(network_name, host_config):
        raise ValueError(f"Network '{network_name}' not found on host {target_host}")
    
    # 3. Validate storage class
    storage_class = fields.get("storage_class")
    if storage_class and not host_resources_service.validate_storage_class(storage_class, host_config):
        raise ValueError(f"Storage class '{storage_class}' not found on host {target_host}")
```

**Validated Against Host Config:**
- Network names (must exist in host's vSwitch configuration)
- Storage classes (must exist in host's storage pool configuration)
- Image names (validated by PowerShell agent, not server)

---

## 6. Guest Configuration Flow

### 6.1 Derivation

**Trigger:** Managed deployment with at least one `guest_config: true` field provided

**Process:**
```python
# Aggregate all guest_config fields from VM and NIC
all_guest_config = {**vm_guest_config_fields, **nic_guest_config_fields}

# Add VM metadata
init_fields = {
    "vm_id": vm_id,  # From VM creation result
    "vm_name": vm_name,  # From user input
    **all_guest_config  # All guest config fields
}
```

**Result Example:**
```json
{
  "vm_id": "12345678-1234-1234-1234-123456789abc",
  "vm_name": "my-vm",
  "guest_la_uid": "Administrator",
  "guest_la_pw": "SecurePass123!",
  "guest_domain_jointarget": "corp.example.com",
  "guest_domain_joinuid": "EXAMPLE\\svc_join",
  "guest_domain_joinpw": "JoinPass123!",
  "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
  "guest_v4_ipaddr": "192.168.1.100",
  "guest_v4_cidrprefix": 24,
  "guest_v4_defaultgw": "192.168.1.1",
  "guest_v4_dns1": "192.168.1.10"
}
```

### 6.2 Delivery

**File:** `Powershell/Provisioning.PublishProvisioningData.ps1`

```powershell
# 1. Receive guest config via STDIN
$InputObject = $Input | ConvertFrom-Json
$vmId = $InputObject.fields.vm_id
$guestConfig = $InputObject.fields

# 2. Encrypt configuration
$encrypted = Protect-ProvisioningData -Data ($guestConfig | ConvertTo-Json) -VmId $vmId

# 3. Publish via KVP
Set-VMKeyValuePairItem -VMId $vmId -Key "provisioning-data" -Value $encrypted

# 4. Set provisioning-ready flag
Set-VMKeyValuePairItem -VMId $vmId -Key "provisioning-ready" -Value "true"
```

**Key Exchange:**
- VM-specific encryption key derived from VM ID and secret
- Only the guest VM can decrypt (using same VM ID + secret)
- Host cannot read guest config after encryption
- Network cannot intercept (transmitted via local KVP, not network)

### 6.3 Guest Agent Application

**Guest Agent (runs inside VM):**
```powershell
# 1. Wait for provisioning-ready flag
while (-not (Get-VMKeyValuePairItem -Key "provisioning-ready")) {
    Start-Sleep -Seconds 5
}

# 2. Retrieve encrypted config
$encrypted = Get-VMKeyValuePairItem -Key "provisioning-data"

# 3. Decrypt
$guestConfig = Unprotect-ProvisioningData -Data $encrypted -VmId $env:VM_ID

# 4. Apply configuration
Set-LocalAdministratorPassword -Password $guestConfig.guest_la_pw
Join-Domain -Target $guestConfig.guest_domain_jointarget `
    -Credential $guestConfig.guest_domain_joinuid:$guestConfig.guest_domain_joinpw `
    -OU $guestConfig.guest_domain_joinou
Set-StaticIP -IPAddress $guestConfig.guest_v4_ipaddr `
    -PrefixLength $guestConfig.guest_v4_cidrprefix `
    -Gateway $guestConfig.guest_v4_defaultgw `
    -DNS $guestConfig.guest_v4_dns1
```

---

## 7. Key Invariants and Assumptions

### 7.1 Invariants (Must Preserve)

1. **Schema-Driven Validation:**
   - All user input validated against YAML schema before processing
   - Schema defines types, ranges, required/optional
   - Parameter sets enforce all-or-none constraints

2. **Field Separation via guest_config Marker:**
   - Fields marked `guest_config: true` go to initialization job
   - Fields without marker go to hardware jobs (VM/disk/NIC creation)
   - This separation happens ONLY during managed deployment

3. **Sequential Orchestration:**
   - VM created first (generates VM ID)
   - Disk and NIC created with VM ID
   - Initialization last (after VM exists)

4. **Child Job Tracking:**
   - Parent job stores array of child job summaries
   - Child status changes update parent
   - Parent completes only after all children complete

5. **JSON Communication Protocol:**
   - Server sends JSON to agents via base64-encoded STDIN
   - Agents return JSON to STDOUT
   - Result structure: `{status, message, data, code?, logs?}`

### 7.2 Assumptions (Documented, Not Enforced)

1. **Version Locking:**
   - Server and agents always deployed together
   - No backwards compatibility required
   - API contract can change freely

2. **Single Host Per Job:**
   - Each job targets exactly one host
   - No multi-host orchestration

3. **Stateless Server:**
   - All job state in memory
   - Inventory refreshed from hosts periodically
   - No persistent job database

4. **Synchronous Host Operations:**
   - Host agent blocks until Hyper-V operation completes
   - No async host-side workflows
   - Exit code 0 = success, non-zero = failure

---

## 8. Current Limitations

### 8.1 Known Gaps

1. **No Conditional UI:**
   - All fields visible regardless of selections
   - No show/hide logic for parameter sets
   - No tabs or sections

2. **No Field Dependencies:**
   - disk_size_gb should be hidden if image_name provided
   - Static IP fields should be hidden if DHCP selected
   - Domain fields should be hidden unless joining domain

3. **Guest Config in Standalone Mode:**
   - Standalone VM creation validates guest_config fields
   - But doesn't separate them or create init job
   - Fields are sent to agent (which ignores them)

4. **Schema Duplication:**
   - Validation logic in job_schema.py
   - Pydantic models exist in models.py but unused for validation
   - Two sources of truth for field structure

5. **Runtime Schema Inspection:**
   - Orchestration depends on reading `guest_config: true` at runtime
   - No compile-time type checking
   - Refactoring risk (field rename breaks orchestration)

### 8.2 Workarounds in Use

1. **Frontend Composition:**
   - Frontend manually merges three schemas
   - Could use server endpoint `/api/v1/schema/managed-deployment` (doesn't exist yet)

2. **VM ID Extraction:**
   - Parse JSON from agent output lines
   - Fragile if output format changes

3. **Partial Validation:**
   - Host-level validation separate from schema validation
   - Could be unified

---

## 9. Migration Path (Future Phases)

### 9.1 Phase 1: Pydantic Models

**Goal:** Replace YAML schemas with Pydantic models for validation

**Changes:**
- Define Pydantic models for VM, Disk, NIC, GuestConfig
- Use Pydantic for validation instead of job_schema.py
- Keep YAML schemas for frontend (or generate from Pydantic)

**Benefits:**
- Type safety
- IDE autocomplete
- Compile-time checking
- Single source of truth

---

### 9.2 Phase 2: Explicit Orchestration

**Goal:** Remove runtime schema introspection

**Changes:**
- Explicitly define which fields are hardware vs. guest config in code
- Remove `guest_config: true` marker from schemas
- Hardcode field lists in orchestration logic

**Benefits:**
- No runtime introspection
- Easier to refactor
- Clearer code

---

### 9.3 Phase 3: Frontend Refactor

**Goal:** Move to explicit forms instead of schema-driven rendering

**Changes:**
- Implement conditional rendering in JavaScript
- Add tabs/sections for better UX
- Show/hide fields based on selections

**Benefits:**
- Better UX
- No schema dependency
- Richer interactions

---

## 10. Summary

**Current System Characteristics:**

| Aspect | Implementation |
|--------|----------------|
| **Validation** | YAML schemas via job_schema.py |
| **Orchestration** | Runtime schema introspection |
| **Guest Config** | `guest_config: true` marker |
| **Communication** | JSON via base64-encoded STDIN |
| **Frontend** | Schema-driven form generation |
| **Deployment** | Managed (orchestrated) or standalone |

**Key Workflows:**

1. **Managed Deployment:** Frontend → Validation → Orchestration → 4 child jobs → Result
2. **Standalone Create:** Frontend → Validation → Single job → Result
3. **Update/Delete:** Frontend → Validation → Single job → Result

**Critical Dependencies:**

- YAML schema files in `/Schemas`
- `guest_config: true` marker for field separation
- JSON result format from PowerShell agents
- Sequential orchestration order (VM → Disk/NIC → Init)

**Next Phase Focus:**

- Replace YAML validation with Pydantic
- Preserve 100% current behavior
- Add comprehensive regression tests
- Document any edge cases discovered

