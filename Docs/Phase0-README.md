# Phase 0 Complete: Groundwork for Schema-to-Pydantic Refactor

## Overview

Phase 0 preparation work is **complete**. The codebase is now fully mapped, documented, and tested before beginning the schema-to-Pydantic refactor outlined in `TechDoc-Python-PowerShell-Interface.md`.

**Status:** ✅ All deliverables complete  
**Behavior:** 100% unchanged (no functionality changes)  
**Tests:** 276 passing (including 21 new baseline tests)

---

## Deliverables Summary

### 1. Schema Usage Inventory ✅

**File:** `Docs/Phase0-Schema-Inventory.md` (531 lines)

**Contents:**
- All 3 schema files documented (vm-create, disk-create, nic-create)
- 34 total fields mapped (13 guest config, 21 hardware)
- Complete consumer analysis:
  - 6 Python files use schemas
  - 1 JavaScript file implements composition
  - PowerShell agents receive validated output (not schemas)
- Auto-composition dependencies fully mapped
- Guest configuration derivation logic documented
- Dependency graph with visual diagrams

**Key Findings:**
- `guest_config: true` marker is the only mechanism separating hardware from guest configuration
- Composition logic scattered across job_service.py, overlay.js, and job_schema.py
- Frontend fetches and merges three schemas at runtime
- No conditional UI rendering (all fields always visible)

---

### 2. Baseline Integration Test Suite ✅

**File:** `server/tests/test_phase0_baseline_schemas.py` (366 lines, 21 tests)

**Coverage:**
- **Schema Loading** (4 tests)
  - Individual schema loading
  - Composed schema field aggregation
  
- **Validation Logic** (5 tests)
  - Successful validation
  - Required field enforcement
  - Parameter set constraints (all-or-none)
  - Disk validation with image cloning
  - NIC validation with static IP

- **Guest Config Separation** (5 tests)
  - VM schema guest_config field identification
  - VM schema hardware field identification
  - NIC schema guest_config field identification
  - NIC schema hardware field identification
  - Disk schema has no guest_config fields

- **Sensitive Field Handling** (2 tests)
  - Secret field identification
  - Composed schema sensitive field aggregation

- **Job Result Structure** (3 tests)
  - Expected result envelope fields
  - VM creation result data structure
  - Disk creation result data structure

- **Orchestration Patterns** (2 tests)
  - Managed deployment child job sequence documentation
  - Guest config aggregation pattern documentation

**Purpose:**
These tests serve as regression tests. Any changes that break these tests indicate a behavioral change that violates backward compatibility requirements.

---

### 3. Server↔Agent Communication Logging ✅

**File:** `server/app/services/job_service.py` (35 lines added)

**Changes:**
- Added `_log_agent_request()` helper method with Phase 0 docstring
- Logs JSON payload sent to host agent for all 10 job types:
  - VM: create, update, delete
  - Disk: create, update, delete
  - NIC: create, update, delete
  - VM: initialize
- Logs JSON responses received from agents (stdout JSON detection)
- All logging at DEBUG level (minimal production impact)

**Log Format:**
```python
# Outbound:
logger.debug("Sending JSON to host agent - job=%s host=%s script=%s payload=%s", ...)

# Inbound:
logger.debug("Received JSON from host agent for job %s: %s", job_id, line)
```

**Value:**
Provides visibility into server↔agent communication for debugging refactor issues. Logs the exact JSON payloads being exchanged, which will be invaluable when validating that Pydantic-based payloads match the original schema-based payloads.

---

### 4. Current System Flow Documentation ✅

**File:** `Docs/Phase0-Current-System-Flow.md` (653 lines)

**Contents:**

**Section 1: High-Level Architecture**
- Component diagram (Frontend → Server → PowerShell Agents)

**Section 2: Request Flow - Managed Deployment**
- Frontend schema composition (overlay.js)
- Backend validation (routes.py)
- Orchestration logic (job_service.py)
- Child job execution flow
- PowerShell agent execution
- Response processing and VM ID extraction

**Section 3: Request Flow - Standalone Operations**
- VM creation (standalone)
- Disk creation (standalone)
- NIC creation (standalone)
- Differences from managed deployment

**Section 4: Schema Structure and Metadata**
- YAML schema file format
- Field type mapping (schema → Python → JavaScript)
- Special markers (guest_config, secret, required, default)

**Section 5: Validation Strategy**
- Server-side validation algorithm
- Parameter set validation modes
- Host-level validation (network names, storage classes)

**Section 6: Guest Configuration Flow**
- Derivation from VM and NIC guest_config fields
- Delivery via encrypted KVP
- Guest agent application inside VM

**Section 7: Key Invariants and Assumptions**
- Invariants that must be preserved (5 listed)
- Assumptions documented but not enforced (4 listed)

**Section 8: Current Limitations**
- Known gaps (5 listed)
- Workarounds in use (3 listed)

**Section 9: Migration Path**
- Phase 1: Pydantic Models
- Phase 2: Explicit Orchestration
- Phase 3: Frontend Refactor

**Section 10: Summary**
- Current system characteristics table
- Key workflows summary
- Critical dependencies list
- Next phase focus areas

**Purpose:**
This document serves as the reference manual during the refactor. It captures the exact behavior that must be preserved, including edge cases, workarounds, and implicit assumptions.

---

## Test Results

```bash
$ pytest server/tests/ -v
========================= 276 passed, 88 warnings in 2.17s =========================
```

**Breakdown:**
- 255 existing tests (all passing)
- 21 new baseline tests (all passing)
- 88 deprecation warnings (pre-existing, unrelated to Phase 0 changes)

**No functionality changes:** All existing tests continue to pass without modification.

---

## Git Commit History

```
7ee7234 Add Phase 0 Deliverable 4: Current System Flow Documentation
25df350 Add Phase 0 Deliverable 3: Server-Agent Communication Logging
ccc48b9 Add Phase 0 Deliverable 2: Baseline Test Suite
36ca629 Add Phase 0 Deliverable 1: Schema Usage Inventory
e7369cf Initial plan
```

---

## Files Changed

### Created Files (4)
1. `Docs/Phase0-Schema-Inventory.md`
2. `Docs/Phase0-Current-System-Flow.md`
3. `Docs/Phase0-README.md` (this file)
4. `server/tests/test_phase0_baseline_schemas.py`

### Modified Files (1)
1. `server/app/services/job_service.py`
   - Added `_log_agent_request()` method
   - Added logging calls in 10 job execution methods
   - Added JSON response logging in `_handle_stream_chunk()`

### Total Changes
- **Documentation:** 1,384 lines added
- **Tests:** 366 lines added
- **Code:** 35 lines added
- **Total:** 1,785 lines added across 5 files

---

## Next Steps

Phase 0 is complete. The codebase is now ready for Phase 1 (not in scope of this PR):

**Phase 1: Pydantic Model Definition**
- Define Pydantic models for VM, Disk, NIC, GuestConfig
- Add validators matching current schema validation logic
- Generate OpenAPI/JSON Schema from Pydantic models
- Serve to frontend for backward compatibility
- Replace `validate_job_submission()` with Pydantic validation

**Phase 2: Explicit Orchestration** (future)
- Remove `guest_config: true` runtime introspection
- Explicitly define field lists in orchestration code
- Hardcode hardware vs. guest config separation

**Phase 3: Frontend Refactor** (future)
- Implement conditional rendering (show/hide fields)
- Add tabs/sections for better UX
- Remove dependency on server-side schema composition

---

## Critical Invariants to Preserve

From the documentation, these behaviors **must not change**:

1. ✅ **Schema-driven validation** - All user input validated against schema before processing
2. ✅ **Field separation via guest_config marker** - Fields marked `guest_config: true` go to init job
3. ✅ **Sequential orchestration** - VM → Disk/NIC → Init (in that order)
4. ✅ **Child job tracking** - Parent job stores child summaries, updates on status change
5. ✅ **JSON communication protocol** - Server sends JSON via base64 STDIN, agents return JSON on STDOUT

---

## Reference Documents

For future developers working on the refactor:

| Document | Purpose |
|----------|---------|
| `TechDoc-Python-PowerShell-Interface.md` | Target architecture and end state |
| `Phase0-Schema-Inventory.md` | Current schema usage and dependencies |
| `Phase0-Current-System-Flow.md` | Current behavior and workflow documentation |
| `test_phase0_baseline_schemas.py` | Regression test suite |

---

## Success Criteria Met ✅

**From Problem Statement:**

- [x] **Deliverable 1:** Inventory the current schema usage
  - [x] Each schema file documented
  - [x] Which components read each schema identified
  - [x] UI/agent auto-composition dependencies mapped
  - [x] Guest configuration derivation documented

- [x] **Deliverable 2:** Create baseline integration test suite
  - [x] Schema loading tests
  - [x] Validation tests
  - [x] Guest config separation tests
  - [x] Job structure validation tests

- [x] **Deliverable 3:** Add logging for server↔agent communication
  - [x] Log raw JSON sent to host agent
  - [x] Log raw JSON received from host agent

- [x] **Deliverable 4:** Write internal docs describing current flow
  - [x] Current schema-driven system documented
  - [x] Reference created for transition

**App state at end of Phase 0:**
✅ 100% unchanged behavior  
✅ Complete map of dependencies  
✅ Comprehensive test suite  
✅ Debug logging in place  
✅ Reference documentation ready

---

**Phase 0 Status: COMPLETE** ✅
