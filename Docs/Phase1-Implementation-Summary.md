# Phase 1: Pydantic Models Implementation

This document describes the Phase 1 implementation of Pydantic models for the AetherV Python-PowerShell interface refactoring.

## Overview

Phase 1 introduces Pydantic models **in parallel** with the existing YAML schema system. No existing code has been modified - the new models provide an additional validation layer that can run alongside the current system.

## Goals Achieved

✅ **All Phase 1 requirements completed:**

1. **Pydantic models for all resource specs:**
   - `VmSpec` - VM hardware configuration (memory, CPU, storage class, clustering)
   - `DiskSpec` - Disk specifications (image cloning or blank disks)
   - `NicSpec` - Network adapter hardware configuration
   - `GuestConfigSpec` - Guest OS configuration (local admin, domain join, Ansible, static IP)
   - `ManagedDeploymentRequest` - Top-level orchestration model

2. **Pydantic models for job envelope:**
   - `JobRequest` - Standard job request envelope for host agent
   - `JobResultEnvelope` - Enhanced job result structure from host agent

3. **Conversion functions (schema → Pydantic):**
   - `convert_vm_schema_to_spec()` - VM schema validation
   - `convert_disk_schema_to_spec()` - Disk schema validation
   - `convert_nic_schema_to_spec()` - NIC schema validation
   - `convert_guest_config_schema_to_spec()` - Guest config extraction and validation
   - `convert_managed_deployment_schema_to_spec()` - Complete deployment validation
   - `validate_job_result()` - Job result envelope validation

4. **Clean validation error bubbling:**
   - Pydantic errors are formatted into readable strings
   - Errors are logged with appropriate context
   - Validation comparison logging helps track schema vs Pydantic agreement

## File Structure

```
server/app/core/
├── pydantic_models.py          # All Pydantic model definitions (390 lines)
├── pydantic_converters.py      # Schema-to-Pydantic conversion functions (370 lines)
└── ...

server/tests/
├── test_phase1_pydantic_models.py    # Comprehensive test suite (720 lines, 40 tests)
├── demo_phase1_validation.py          # Demonstration script showing validation
└── ...
```

## Key Design Decisions

### 1. Backward Compatibility

The converter functions return the **same dict structure** that the old schema system expects. This allows both systems to coexist:

```python
# Converter signature
def convert_vm_schema_to_spec(schema_values: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    # Returns: (validated_dict, error_message)
```

### 2. Clean Separation of Concerns

- **VM hardware** fields are separated from **guest configuration** fields
- **NIC hardware** fields are separated from **guest IP configuration** fields
- This matches the architecture described in the TechDoc

### 3. Parameter Set Validation

All "all-or-none" validation (domain join, static IP, Ansible) is enforced in Pydantic using `@model_validator`:

```python
@model_validator(mode='after')
def validate_parameter_sets(self) -> 'GuestConfigSpec':
    # Domain join: all-or-none
    domain_fields = [self.guest_domain_jointarget, ...]
    # Validate completeness
```

### 4. Modern Pydantic v2 Syntax

All models use Pydantic v2 with `ConfigDict` (no deprecation warnings):

```python
model_config = ConfigDict(
    json_schema_extra={
        "example": {...}
    }
)
```

## Usage Example

```python
from app.core.job_schema import validate_job_submission
from app.core.pydantic_converters import convert_vm_schema_to_spec

# Existing schema validation (still works)
schema = load_schema_by_id("vm-create")
validated_values = validate_job_submission(user_input, schema)

# NEW: Pydantic validation in parallel
vm_dict, pydantic_error = convert_vm_schema_to_spec(validated_values)

if pydantic_error:
    # Handle Pydantic validation failure
    logger.warning("Pydantic validation failed: %s", pydantic_error)
else:
    # Both validations passed
    logger.info("Double validation passed!")
```

## Test Coverage

**40 new tests** covering:
- ✅ All Pydantic model validation (positive and negative cases)
- ✅ All conversion functions
- ✅ Parameter set validation (all-or-none logic)
- ✅ Error formatting and bubbling
- ✅ Complete managed deployment scenarios

**All existing tests still pass** (316 total tests).

## Running the Demonstration

```bash
cd /home/runner/work/Aether-V/Aether-V
PYTHONPATH=/home/runner/work/Aether-V/Aether-V/server python server/tests/demo_phase1_validation.py
```

The demo shows:
1. Valid VM validation (both systems pass)
2. Invalid VM validation (both systems catch error)
3. Parameter set enforcement (partial domain join fails)
4. Complete managed deployment (all components)
5. Disk specification validation
6. NIC specification validation

## What's NOT Changed

**No existing code has been modified:**
- ❌ Routes still use schema validation
- ❌ Job service still uses schema-based flow
- ❌ No API changes
- ❌ No PowerShell agent changes
- ❌ Frontend unchanged

This is intentional - Phase 1 is about **adding** validation capability, not **replacing** the existing system.

## Next Steps (Future Phases)

Phase 2 and beyond will:
- Wire Pydantic validation into actual API routes
- Replace schema validation calls with Pydantic validation
- Remove schema dependencies gradually
- Update tests to use Pydantic models directly

## Model Reference

### VmSpec
```python
vm_name: str          # 1-64 chars
gb_ram: int           # 1-512 GB
cpu_cores: int        # 1-64 cores
storage_class: Optional[str]
vm_clustered: bool = False
```

### DiskSpec
```python
vm_id: Optional[str]           # 36 char GUID
image_name: Optional[str]      # For cloning
disk_size_gb: int = 100        # 1-65536 GB
storage_class: Optional[str]
disk_type: str = "Dynamic"
controller_type: str = "SCSI"
```

### NicSpec
```python
vm_id: Optional[str]    # 36 char GUID
network: str            # Required
adapter_name: Optional[str]
```

### GuestConfigSpec
```python
# Required
guest_la_uid: str
guest_la_pw: str

# Domain join (all-or-none)
guest_domain_jointarget: Optional[str]
guest_domain_joinuid: Optional[str]
guest_domain_joinpw: Optional[str]
guest_domain_joinou: Optional[str]

# Ansible (all-or-none)
cnf_ansible_ssh_user: Optional[str]
cnf_ansible_ssh_key: Optional[str]

# Static IP (all-or-none for required fields)
guest_v4_ipaddr: Optional[str]
guest_v4_cidrprefix: Optional[int]
guest_v4_defaultgw: Optional[str]
guest_v4_dns1: Optional[str]
guest_v4_dns2: Optional[str]
guest_net_dnssuffix: Optional[str]
```

### ManagedDeploymentRequest
```python
vm_spec: VmSpec
disk_spec: Optional[DiskSpec]
nic_spec: Optional[NicSpec]
guest_config: Optional[GuestConfigSpec]
target_host: str
```

### JobRequest
```python
operation: str                    # e.g., "vm.create"
resource_spec: Dict[str, Any]
correlation_id: str
metadata: Dict[str, Any] = {}
```

### JobResultEnvelope
```python
status: JobResultStatus          # success | error | partial
message: str
data: Dict[str, Any] = {}
code: Optional[str]
logs: List[str] = []
correlation_id: Optional[str]
```

## Validation Logic

### Parameter Sets (All-or-None)

Three parameter sets enforce all-or-none logic:

1. **Domain Join** - All required:
   - `guest_domain_jointarget`
   - `guest_domain_joinuid`
   - `guest_domain_joinpw`
   - `guest_domain_joinou`

2. **Ansible Configuration** - All required:
   - `cnf_ansible_ssh_user`
   - `cnf_ansible_ssh_key`

3. **Static IP** - All required:
   - `guest_v4_ipaddr`
   - `guest_v4_cidrprefix`
   - `guest_v4_defaultgw`
   - `guest_v4_dns1`
   - Optional: `guest_v4_dns2`, `guest_net_dnssuffix`

### Field Validation

- **VM name**: 1-64 characters
- **RAM**: 1-512 GB
- **CPU cores**: 1-64
- **Disk size**: 1-65536 GB
- **VM ID**: Exactly 36 characters (GUID format)

## Summary

Phase 1 successfully introduces Pydantic models as a **parallel validation layer** without breaking any existing functionality. The models are:

- ✅ Well-tested (40 new tests)
- ✅ Fully documented
- ✅ Backward compatible
- ✅ Ready for Phase 2 integration

The system is now ready for Phase 2, where these models will be integrated into the actual request processing flow.
