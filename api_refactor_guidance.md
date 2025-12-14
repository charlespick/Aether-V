

# Aether-V API Surface Refactoring Guidance (v1)

## Purpose of This Document

This document defines the **intended shape and access patterns** of the Aether-V v1 API surface.

**Important clarifications up front:**

* This document **does not enumerate all available properties** on any resource.
* All properties shown are **examples only**, chosen to illustrate *scope and intent*.
* **No properties are being removed** as part of this refactor.
* The goal is to **separate shallow inventory APIs from deep detail APIs**, not to reduce functionality.
* Existing APIs may return *more* data than shown here; that is acceptable and expected.

This guidance exists to:

* Prevent accidental over-expansion of bulk APIs
* Keep payload sizes predictable and scalable
* Align API access patterns with frontend UI and Terraform usage
* Provide clear boundaries for future expansion

---

## Design Principles (Non-Negotiable)

### 1. Shallow + Wide vs Deep + Narrow

There are **two intentional classes of read APIs**:

| Class              | Purpose                       | Characteristics                  |
| ------------------ | ----------------------------- | -------------------------------- |
| **Shallow & Wide** | Inventory, tables, navigation | Minimal fields, many objects     |
| **Deep & Narrow**  | Detail views, Terraform       | Full object model, single object |

Bulk APIs **must remain shallow** by design.

---

### 2. Explicit Aggregation Boundaries

* **Virtual Machines are aggregation roots**
* Disks and NICs are **always scoped to a VM**
* There is **no global disk or NIC inventory**
* Nested objects are only enumerable *through their parent*

---

### 3. Documentation Is Illustrative, Not Exhaustive

Any property lists in this document:

* Are **not complete**
* Are **not authoritative**
* Exist solely to demonstrate **intended payload depth**

If a property exists today and is not shown here:

* It is **not being removed**
* It may still appear in responses
* It simply is not relevant to the *shape* discussion

---

## Base API Prefix

All endpoints are rooted at:

```
/api/v1
```

Plural nouns represent collections.
Singular resources are addressed by ID.

---

## Clusters

### `GET /api/v1/clusters`

**Shallow, wide inventory**

**Intent**

* Populate sidebar
* Populate cluster list views
* Support basic filtering and navigation

**Example response (illustrative only)**

```json
[
  {
    "id": "cluster-1",
    "name": "Aether-Prod",
    "state": "healthy",
    "host_count": 8,
    "vm_count": 312
  }
]
```

**Design notes**

* No hosts array
* No VMs array
* No nested objects
* Fields are limited to what is required to render current UI tables

---

### `GET /api/v1/clusters/{cluster_id}`

**Cluster detail view**

**Intent**

* Populate cluster detail UI
* Provide shallow visibility into child resources

**Example response**

```json
{
  "id": "cluster-1",
  "name": "Aether-Prod",
  "state": "healthy",

  "hosts": [
    { "id": "host-1", "name": "hv-01", "state": "up" }
  ],

  "virtual_machines": [
    {
      "id": "vm-123",
      "name": "web-01",
      "power_state": "running"
    }
  ]
}
```

**Design notes**

* Child objects are intentionally shallow
* VM internals are **not expanded**
* This endpoint is *not* intended to replace VM detail calls

---

## Hosts

### `GET /api/v1/hosts`

**Shallow, wide inventory**

**Intent**

* Host inventory views
* Sidebar navigation

```json
[
  {
    "id": "host-1",
    "name": "hv-01",
    "state": "up",
    "cluster_id": "cluster-1",
    "vm_count": 42
  }
]
```
Also includes disconnected hosts replacing existing disconnected_hosts array in inventory
---

### `GET /api/v1/hosts/{host_id}`

**Host detail view**

**Intent**

* Host-specific UI
* Capacity and health inspection

```json
{
  "id": "host-1",
  "name": "hv-01",
  "state": "up",
  "cluster_id": "cluster-1",

  "virtual_machines": [
    {
      "id": "vm-123",
      "name": "web-01",
      "power_state": "running"
    }
  ]
}
```

**Design notes**

* VM list remains shallow
* No VM disks, NICs, or configuration details appear here

---

## Virtual Machines

### `GET /api/v1/virtualmachines`

**Shallow, wide inventory (critical endpoint)**

**Intent**

* Sidebar VM lists
* Cluster views
* Host views
* Terraform list operations

```json
[
  {
    "id": "vm-123",
    "name": "web-01",
    "power_state": "running",
    "cluster_id": "cluster-1",
    "host_id": "host-1"
  }
]
```

**Design notes**

* This endpoint must remain fast and predictable
* Only properties required to populate tables belong here
* Additional fields may exist but should be scrutinized carefully

---

### `GET /api/v1/virtualmachines/{virtualmachine_id}`

**Authoritative VM detail view**

**Intent**

* VM detail UI
* Terraform read operations
* Drift detection and reconciliation

```json
{
  "id": "vm-123",
  "name": "web-01",
  "power_state": "running",

  "cluster_id": "cluster-1",
  "host_id": "host-1",

  "cpu": 4,
  "memory_mb": 8192,

  "disks": [
    {
      "id": "disk-1",
      "name": "os.vhdx",
      "size_gb": 100
    }
  ],

  "network_adapters": [
    {
      "id": "nic-1",
      "network_id": "net-3",
      "mac_address": "00:15:5D:…"
    }
  ]
}
```

**Design notes**

* This is the *only* endpoint that returns full VM configuration
* Payload size is intentionally unconstrained
* Terraform relies on this endpoint being complete

---

## Disks (VM-Scoped Sub-Resources)

There is **no global disk inventory**.

### `GET /api/v1/virtualmachines/{virtualmachine_id}/disks/{disk_id}`

**Intent**

* Disk detail UI
* Terraform disk resources (if modeled separately)

```json
{
  "id": "disk-1",
  "virtualmachine_id": "vm-123",
  "name": "os.vhdx",
  "size_gb": 100,
  "type": "vhdx"
}
```

**Design notes**

* Disks are always accessed in the context of a VM
* Listing disks happens via the VM detail endpoint
* This avoids unbounded global fan-out

---

## Network Adapters (NICs, VM-Scoped)

There is **no global NIC inventory**.

### `GET /api/v1/virtualmachines/{virtualmachine_id}/networkadapters/{adapter_id}`

**Intent**

* Network adapter detail UI
* Terraform NIC resources (if modeled separately)

```json
{
  "id": "nic-1",
  "virtualmachine_id": "vm-123",
  "network_id": "net-3",
  "mac_address": "00:15:5D:…",
  "connected": true
}
```
### `GET /api/v1/statistics
Replaces existing sumary counts in /inventory api endpoint
---

## Explicit Non-Goals of This Refactor

This API surface refactor **does not**:

* Remove existing properties
* Change underlying data models
* Introduce breaking behavior by omission
* Prevent future expansion of responses
* Enforce response schemas at this stage

The sole objective is to:

> **Clearly define which endpoints are allowed to grow deep and which must remain intentionally shallow.**

---

## Summary (Design Contract)

* Bulk inventory endpoints are **shallow by design**
* Detail endpoints are **authoritative and complete**
* Virtual Machines are the **aggregation boundary**
* Disks and NICs are **VM-scoped sub-resources**
* Documentation examples are **illustrative only**

This structure gives Aether-V:

* Predictable performance at scale
* Clean UI data flows
* A Terraform-friendly read model
* Long-term extensibility without API sprawl
