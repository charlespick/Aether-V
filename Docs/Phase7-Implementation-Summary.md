# Phase 7 Implementation Summary - UI Migration (Remove Schema Dependency)

## Objective
Remove the frontend's dependency on YAML schemas by building forms directly from Pydantic model metadata or implementing them manually in code.

## What Was Completed

### 1. Core Infrastructure
- **File**: `/server/app/static/pydantic-form-builder.js`
- **Purpose**: Utility class for extracting field metadata from Pydantic models via OpenAPI/JSON Schema
- **Features**:
  - Fetches OpenAPI spec from FastAPI's `/openapi.json` endpoint
  - Extracts field definitions, labels, types, and validation constraints
  - Provides helper methods for building HTML form controls
  - Can flatten nested Pydantic models for form display

### 2. Provision Form (Complete Replacement)
- **File**: `/server/app/static/provision-form-pydantic.js`
- **Purpose**: Manually coded VM provisioning form replacing schema-driven approach
- **Features**:
  - Hardcoded form fields based on Pydantic models (VmSpec, DiskSpec, NicSpec, GuestConfigSpec)
  - Implements all conditional UI logic in JavaScript:
    - DHCP vs Static IP toggle with dynamic field visibility
    - Domain Join toggle with conditional required fields
    - Ansible configuration (not yet implemented in UI, but supported by backend)
  - Submits to `/api/v2/managed-deployments` endpoint with proper Pydantic structure
  - Proper error handling and validation feedback

### 3. Overlay System Updates
- **File**: `/server/app/static/overlay.js`
- **Changes**:
  - Replaced `ProvisionJobOverlay` to delegate to `ProvisionFormPydantic`
  - Kept legacy schema-based implementation as `ProvisionJobOverlayLegacy` for reference
  - New overlay is much simpler - just delegates to the Pydantic form component

### 4. Template and Configuration Updates
- **File**: `/server/app/templates/index.html`
- **Changes**:
  - Added script tags for new Pydantic form files
  - Removed `job_schema` from config data (no longer needed)
  
- **File**: `/server/app/static/main.js`
- **Changes**:
  - Set `window.jobSchema` to `null` with deprecation comment
  - Removed schema initialization code

## Conditional UI Logic Implemented

### 1. DHCP vs Static IP
- Checkbox toggles between DHCP and static IP configuration
- When static IP is selected:
  - Shows fields: IPv4 Address, CIDR Prefix, Default Gateway, Primary DNS, Secondary DNS
  - Makes first 4 fields required (Secondary DNS remains optional)
- When DHCP is selected:
  - Hides all static IP fields
  - Removes required attributes

### 2. Domain Join
- Checkbox toggles domain join configuration
- When enabled:
  - Shows fields: Domain FQDN, Domain Join Username, Domain Join Password, Organizational Unit
  - All domain join fields become required
- When disabled:
  - Hides all domain join fields
  - Removes required attributes

### 3. Other Features
- Host selection with automatic filtering of connected hosts only
- VM clustered checkbox for Failover Clustering support
- Image selection for disk cloning vs blank disk
- Storage class configuration (optional)

## What Remains To Be Done

### 1. Edit Form Overlays (Not Yet Migrated)
The following overlays still use schema-driven forms and need to be updated:

#### DiskCreateOverlay & DiskEditOverlay
- **Current**: Fetches `/api/v1/schema/disk-create` schema
- **Needed**: Create manually coded form using DiskSpec Pydantic model
- **Complexity**: Low - simple form with ~6 fields
- **Conditional Logic**: None

#### NicCreateOverlay & NicEditOverlay
- **Current**: Fetches `/api/v1/schema/nic-create` schema
- **Needed**: Create manually coded form using NicSpec Pydantic model
- **Complexity**: Low - simple form with network selection and optional guest IP config
- **Conditional Logic**: Could add DHCP vs Static IP toggle (same as provision form)

#### VMEditOverlay
- **Current**: Fetches `/api/v1/schema/vm-create` schema
- **Needed**: Create manually coded form using VmSpec Pydantic model
- **Complexity**: Low - hardware fields only (CPU, RAM, storage class, clustering)
- **Conditional Logic**: None (guest config can't be edited after creation)

### 2. Legacy Code Removal
After all forms are migrated:
- Remove `ProvisionJobOverlayLegacy` class from overlay.js
- Remove all schema-related helper methods (renderField, renderParameterSets, etc.) from overlay.js
- Consider removing `/api/v1/schema/{schema_id}` endpoint (or mark as deprecated)
- Remove or deprecate YAML schema files in `/Schemas` directory

### 3. Testing
- Manual testing of provision form with all conditional combinations
- Test form validation (required fields, pattern matching, min/max constraints)
- Test error handling and display
- Verify submission to `/api/v2/managed-deployments` works end-to-end

### 4. Documentation Updates
- Update TechDoc to reflect Phase 7 completion
- Document the new form architecture
- Add developer guide for creating new forms based on Pydantic models

## Technical Details

### Backend API Integration

The new forms submit to the v2 endpoint which expects Pydantic model structure:

```json
{
  "vm_spec": {
    "vm_name": "web-server-01",
    "gb_ram": 4,
    "cpu_cores": 2,
    "storage_class": "fast-ssd",
    "vm_clustered": false
  },
  "disk_spec": {
    "image_name": "Windows Server 2022",
    "disk_size_gb": 100,
    "disk_type": "Dynamic",
    "controller_type": "SCSI"
  },
  "nic_spec": {
    "network": "Production"
  },
  "guest_config": {
    "guest_la_uid": "Administrator",
    "guest_la_pw": "SecurePass123!",
    "guest_v4_ipaddr": "192.168.1.100",
    "guest_v4_cidrprefix": 24,
    "guest_v4_defaultgw": "192.168.1.1",
    "guest_v4_dns1": "192.168.1.2"
  },
  "target_host": "hyperv-01.domain.local"
}
```

### Key Benefits of Pydantic-Based Forms

1. **Single Source of Truth**: Pydantic models define the API contract
2. **Type Safety**: Backend validation catches errors early
3. **Simplified Frontend**: No need to interpret complex schema structures
4. **Better Maintainability**: Form logic is explicit and easy to modify
5. **Improved Performance**: No runtime schema composition or dynamic rendering

### Migration Strategy for Remaining Forms

For each remaining overlay:

1. **Create new form component file** (e.g., `disk-form-pydantic.js`)
2. **Hardcode field definitions** based on the Pydantic model
3. **Implement any conditional logic** directly in JavaScript
4. **Update overlay class** to delegate to new form component
5. **Test thoroughly** before deploying

Example structure:
```javascript
class DiskFormPydantic {
    constructor(data = {}) {
        this.data = data;
        this.vmId = data.vm_id;
        this.vmName = data.vm_name;
        this.host = data.host;
    }
    
    async init() {
        // Render hardcoded form
    }
    
    async handleSubmit(event) {
        // Submit to /api/v1/resources/disks with Pydantic structure
    }
}
```

## Files Modified

1. `/server/app/static/pydantic-form-builder.js` (new)
2. `/server/app/static/provision-form-pydantic.js` (new)
3. `/server/app/static/overlay.js` (modified - ProvisionJobOverlay replaced)
4. `/server/app/static/main.js` (modified - removed schema initialization)
5. `/server/app/templates/index.html` (modified - removed job_schema, added new scripts)

## Next Steps

1. Complete migration of edit form overlays (Disk, NIC, VM)
2. Remove legacy schema-driven code
3. Test all forms end-to-end
4. Update documentation
5. Mark schema system as deprecated/ready for removal

## Conclusion

Phase 7 is **partially complete**:
- ✅ Core provision form migrated to Pydantic-based approach
- ✅ Schema references removed from main.js and template
- ✅ Conditional UI logic implemented directly in code
- ⚠️ Edit forms still need migration (straightforward, low complexity)
- ⚠️ Legacy code cleanup pending

The foundation is in place for completing the remaining work. The pattern established by the provision form can be easily replicated for the simpler edit forms.
