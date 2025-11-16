# VM Component Separation - Implementation Guide

## Overview
This document outlines the implementation plan for separating VM, Disk, and Network Adapter into independent resources with their own CRUD APIs.

## Completed Work

### Phase 1: Schemas and Models ✅
- Created 4 new schema files:
  - `Schemas/vm-create.yaml` - VM creation without disk/NIC
  - `Schemas/disk-create.yaml` - Disk creation (requires vm_id)
  - `Schemas/nic-create.yaml` - NIC creation (requires vm_id)
  - `Schemas/managed-deployment.yaml` - Full VM deployment (backward compatible)
  
- Updated `server/app/core/models.py`:
  - Added `id` field to `VMDisk` and `VMNetworkAdapter`
  - Added new models: `ResourceCreateRequest`, `DiskCreateRequest`, `NicCreateRequest`, `ResourceDeleteRequest`, `JobResult`

- Updated `server/app/core/job_schema.py`:
  - Modified to support loading multiple schemas by ID
  - Added `load_schema_by_id()` function
  - Updated `get_job_schema()` to return managed-deployment schema

### Phase 2: PowerShell Scripts (In Progress)
- Created `Powershell/Invoke-CreateVmJob.ps1` (initial version)
- Still needed:
  - `Powershell/Invoke-CreateDiskJob.ps1`
  - `Powershell/Invoke-CreateNicJob.ps1`
  - `Powershell/Invoke-UpdateVmJob.ps1`
  - `Powershell/Invoke-UpdateDiskJob.ps1`
  - `Powershell/Invoke-UpdateNicJob.ps1`
  - `Powershell/Invoke-DeleteDiskJob.ps1`
  - `Powershell/Invoke-DeleteNicJob.ps1`
  - Update `Powershell/Inventory.Collect.ps1` to collect IDs

## Remaining Work

### Phase 3: Backend Services
Location: `server/app/services/job_service.py`

#### New Job Types to Add:
- `create_vm` - Create VM only
- `create_disk` - Create and attach disk to existing VM
- `create_nic` - Create and attach NIC to existing VM
- `update_vm` - Update VM settings
- `update_disk` - Update disk settings
- `update_nic` - Update NIC settings
- `delete_disk` - Delete disk from VM
- `delete_nic` - Delete NIC from VM
- `managed_deployment` - Orchestrate creation of VM + disk + NIC

#### Changes Needed:
1. Add new execution methods in `JobService`:
   ```python
   async def _execute_create_vm_job(self, job: Job) -> None
   async def _execute_create_disk_job(self, job: Job) -> None
   async def _execute_create_nic_job(self, job: Job) -> None
   async def _execute_update_vm_job(self, job: Job) -> None
   async def _execute_managed_deployment_job(self, job: Job) -> None
   ```

2. Update `_process_job()` to handle new job types

3. Add validation logic to check:
   - VM exists before creating disk/NIC
   - Resource exists before updating/deleting
   - No circular dependencies

### Phase 4: API Endpoints
Location: `server/app/api/routes.py`

#### New Endpoints:
```python
# VM Resources
POST /api/v1/resources/vms - Create VM (returns JobResult)
GET /api/v1/resources/vms/{vm_id} - Get VM by ID
PUT /api/v1/resources/vms/{vm_id} - Update VM (returns JobResult)
DELETE /api/v1/resources/vms/{vm_id} - Delete VM (returns JobResult)

# Disk Resources
POST /api/v1/resources/disks - Create disk (returns JobResult)
GET /api/v1/resources/disks/{disk_id} - Get disk by ID
PUT /api/v1/resources/disks/{disk_id} - Update disk (returns JobResult)
DELETE /api/v1/resources/disks/{disk_id} - Delete disk (returns JobResult)

# NIC Resources
POST /api/v1/resources/nics - Create NIC (returns JobResult)
GET /api/v1/resources/nics/{nic_id} - Get NIC by ID
PUT /api/v1/resources/nics/{nic_id} - Update NIC (returns JobResult)
DELETE /api/v1/resources/nics/{nic_id} - Delete NIC (returns JobResult)

# Managed Deployments (backward compatible)
POST /api/v1/managed-deployments - Create VM + disk + NIC (returns JobResult)
DELETE /api/v1/managed-deployments/{vm_id} - Delete VM + disk + NIC (returns JobResult)

# Schema Endpoints
GET /api/v1/schema/vm-create - Get VM creation schema
GET /api/v1/schema/disk-create - Get disk creation schema
GET /api/v1/schema/nic-create - Get NIC creation schema
GET /api/v1/schema/managed-deployment - Get managed deployment schema
```

#### Endpoints to Remove:
- `POST /api/v1/jobs/provision` (replaced by managed-deployments)
- `POST /api/v1/vms/delete` (replaced by resource delete endpoints)

### Phase 5: Frontend Updates
Location: `server/app/static/` and `server/app/templates/`

#### Changes Needed:
1. Update form rendering to use managed-deployment schema
2. Add support for component-based creation (advanced mode)
3. Display resource IDs in VM details
4. Update job status display for new job types

### Phase 6: Inventory Service
Location: `server/app/services/inventory_service.py`

#### Changes Needed:
1. Update to track disk and NIC IDs
2. Add methods to query by resource ID:
   ```python
   def get_disk_by_id(self, disk_id: str) -> Optional[VMDisk]
   def get_nic_by_id(self, nic_id: str) -> Optional[VMNetworkAdapter]
   ```

### Phase 7: Testing
Location: `server/tests/`

#### Test Files to Update:
- `test_job_service.py` - Add tests for new job types
- `test_routes_unit.py` - Add tests for new endpoints
- `test_inventory_service.py` - Add tests for ID-based queries

#### New Test Files:
- `test_resource_apis.py` - Integration tests for resource CRUD
- `test_managed_deployment.py` - Test orchestration logic

## Migration Path

### For Existing Deployments:
1. Keep legacy endpoints active initially
2. Add new component-based endpoints
3. Update frontend to use managed-deployment endpoint
4. Deprecate legacy endpoints after validation
5. Remove legacy endpoints in future release

### For Terraform Users:
- Use new component-based APIs directly
- Example workflow:
  1. POST /api/v1/resources/vms → get job_id → poll → get vm_id
  2. POST /api/v1/resources/disks with vm_id → get job_id → poll
  3. POST /api/v1/resources/nics with vm_id → get job_id → poll

## Key Design Decisions

1. **Async Pattern**: All create/update/delete operations return `JobResult` with job_id for polling
2. **Resource IDs**: Use Hyper-V native .ID property (GUID) for all resources
3. **Dependencies**: Disks and NICs require existing VM ID; deleting VM cascades to components
4. **Backward Compatibility**: Managed deployment endpoint provides same UX as current provision endpoint
5. **Inventory Collection**: Updated to include IDs from PowerShell Get-VM, Get-VMHardDiskDrive, Get-VMNetworkAdapter

## File Checklist

### Schemas ✅
- [x] Schemas/vm-create.yaml
- [x] Schemas/disk-create.yaml
- [x] Schemas/nic-create.yaml
- [x] Schemas/managed-deployment.yaml

### Models ✅
- [x] server/app/core/models.py
- [x] server/app/core/job_schema.py

### PowerShell Scripts
- [x] Powershell/Invoke-CreateVmJob.ps1 (initial)
- [ ] Powershell/Invoke-CreateDiskJob.ps1
- [ ] Powershell/Invoke-CreateNicJob.ps1
- [ ] Powershell/Invoke-UpdateVmJob.ps1
- [ ] Powershell/Invoke-UpdateDiskJob.ps1
- [ ] Powershell/Invoke-UpdateNicJob.ps1
- [ ] Powershell/Invoke-DeleteDiskJob.ps1
- [ ] Powershell/Invoke-DeleteNicJob.ps1
- [ ] Powershell/Inventory.Collect.ps1 (update)

### Backend Services
- [ ] server/app/services/job_service.py
- [ ] server/app/services/inventory_service.py

### API Routes
- [ ] server/app/api/routes.py

### Frontend
- [ ] server/app/static/*.js
- [ ] server/app/templates/*.html

### Tests
- [ ] server/tests/test_job_service.py
- [ ] server/tests/test_routes_unit.py
- [ ] server/tests/test_inventory_service.py
- [ ] server/tests/test_resource_apis.py (new)
- [ ] server/tests/test_managed_deployment.py (new)

## Next Steps

This implementation requires significant work across multiple files. The recommended approach is to:

1. Complete PowerShell scripts first (foundation)
2. Update inventory collection to include IDs
3. Extend job service with new job types
4. Add API endpoints
5. Update frontend
6. Add comprehensive tests

The current commit provides the foundational schemas and models. The remaining work should be done incrementally, testing each component as it's added.
