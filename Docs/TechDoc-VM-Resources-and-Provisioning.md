
## 1. Context & Legacy Model

Historically, AetherV’s provisioning pipeline was **monolithic**:

* A single **“master” PowerShell script** lived on the Hyper-V host.
* The AetherV server:

  * Opened a **single WinRM connection** to that script.
  * Sent a **single JSON payload** representing the entire “New VM” request.
* That JSON payload was shaped by a **single schema file** in the repository, which drove:

  * Front-end form rendering (fields, hints, validation).
  * Input validation.
  * The shape and semantics of the PowerShell agent’s internal data handling.

Key characteristics of the legacy design:

* The schema was the **single source of truth**: changing the schema (and the PowerShell agent) was sufficient to change both UI and behavior, without touching Python.
* Provisioning was effectively **one logical operation**: create VM, attach disk, attach NIC, inject guest configuration, power on, etc., all within one job.

This worked well for a tightly integrated “New VM” flow, but it maps poorly to Terraform’s resource-oriented model and to scenarios where VM, NIC, disk, and guest provisioning need to be treated as **independent managed resources**.

---

## 2. Design Goals of the Refactor

The current refactor is driven by Terraform and maintainability goals:

1. **Decompose** the monolithic provisioning flow into **four distinct components**:

   * Virtual Machine (VM) resource.
   * Disk resource.
   * Network Adapter (NIC) resource.
   * Guest initialization / specialization action (step 4).

2. Expose each component as an **independent API surface**:

   * VM, Disk, NIC: full **CRUD** (Create, Read, Update, Delete) APIs.
   * Initialization: a dedicated “trigger guest specialization” action (not CRUD; it’s an operation).

3. Maintain a **simple, opinionated “managed deployment” flow** for common UI-driven provisioning:

   * Fixed shape: **1 VM + 1 disk + 1 NIC**, orchestrated through a single “New VM” form.
   * Internally uses the same component APIs to perform the four steps.

4. Keep AetherV **stateless** in terms of persistent storage:

   * No database / schema migrations.
   * All durable reality is in **Hyper-V itself**.
   * AetherV continuously re-discovers state from Hyper-V inventory.

5. Ensure the design naturally maps to future **Terraform resources**:

   * Terraform should call the **individual component APIs**, not the managed deployment endpoint.
   * Dependencies (VM → Disk → NIC → Init) are expressed in Terraform’s graph instead of AetherV’s hidden state.

---

## 3. Hyper-V Constraints & Resource Dependencies

Hyper-V imposes specific constraints that shape this design:

* A **Network Adapter cannot exist without a VM** to attach it to.
* A **disk technically can exist independently**, but:

  * AetherV does not maintain persistent state about unattached disks.
  * Without a DB, AetherV cannot reliably manage a “loose disk” and later attach it.

As a result:

* **NIC and Disk creation APIs require a VM identifier**:

  * The API shape enforces:

    1. Create VM ⇒ get VM ID.
    2. Use VM ID when creating NIC and Disk.
* This mirrors Hyper-V’s dependency model while ensuring AetherV doesn’t need its own long-lived object store.

---

## 4. API Model & Guest Configuration

### 4.1. Hardware-Only Models for Independent APIs

The hardware resource models (VmSpec, DiskSpec, NicSpec) are **hardware-only**:

* **VmSpec**: vm_name, gb_ram, cpu_cores, target_host, cluster_preference
* **DiskSpec**: size_gb, storage_type, storage_class  
* **NicSpec**: network, adapter_name

These models contain **no guest configuration fields**. They are used by:

1. Independent resource APIs (create VM, create disk, create NIC separately)
2. Internal construction within the managed deployment orchestrator

### 4.2. Flat ManagedDeploymentRequest for UI Form Submission

The ManagedDeploymentRequest model is a **flat structure** that mirrors the UI form:

* All form fields are top-level properties (not nested under vm_spec/guest_config)
* Hardware fields: vm_name, gb_ram, cpu_cores, target_host, network, ip_behavior, etc.
* Guest config fields: guest_la_uid, guest_la_pw, domain, domain_ou, dns_server, etc.
* Optional join credentials: join_account, join_password

When a managed deployment job executes:

1. The flat request is parsed
2. Hardware specs (VmSpec, DiskSpec, NicSpec) are constructed internally
3. Guest configuration is extracted using generate_guest_config()
4. Hardware APIs create resources, then Initialize API injects guest config via KVP

### 4.3. Guest Configuration Composition

The guest_config_generator extracts guest configuration from the flat request:

* Takes ManagedDeploymentRequest directly (not nested dicts)
* Extracts fields like hostname, domain, credentials, network settings
* Returns a flat dictionary for KVP transmission to the guest agent

This composed guest configuration dictionary is what is ultimately passed to the **initialization (step 4) agent** for encryption and injection into the guest via Hyper-V KVP.

---

## 5. Stateless Job & Orchestration Model

### 5.1. No Persistent State, Only Jobs + Hyper-V

AetherV deliberately **does not have a database**:

* No persistent tracking of “deployments,” “resources,” or “job state” beyond:

  * The live state in Hyper-V (VMs, disks, NICs).
  * Short-lived in-memory data inside the job that is executing.

The system relies on:

* A **job service** where each operation is a job.
* Periodic **inventory refreshes** from Hyper-V to reconstruct the current world state at any time.

### 5.2. Job IDs & Correlation

Every job (whether it’s VM creation, Disk creation, NIC creation, Initialization, or a Managed Deployment) is:

* Created via an API call that:

  * Accepts the request.
  * Returns a **job ID** immediately.
* Polled by the client (UI / API consumer) for status and results.

Job results include:

* Success/failure state.
* For resource creation:

  * Identifying properties (e.g., VM ID) as job output.
* Human-readable job log (populated from PowerShell output).

Within the implementation:

* The **Managed Deployment service** also has its own **deployment/job ID**, used to tie together:

  * Step 1: VM creation.
  * Step 2: Disk creation.
  * Step 3: NIC creation.
  * Step 4: Initialization.

But none of this is persisted beyond the job lifetime; it all lives in memory during execution.

### 5.3. Failure & Rollback

Current behavior and expectations:

* If any step fails (VM, Disk, NIC, or Initialization), the **job stops**.
* There is **no automatic rollback** of previously created resources at this stage.
* “Create” operations are **not idempotent** in the sense of “create or succeed if existing”:

  * If you attempt to create a VM with an already existing name, it should **fail explicitly**, not silently succeed.
* Robust rollback logic and job resumption are explicitly out of scope for this refactor and are deferred to a much later phase.

---

## 6. Component Agents & Entry Scripts

Although deep details of the PowerShell agents aren’t the focus here, key constraints are:

* Each component (VM, Disk, NIC, Init) has its **own entry PowerShell script**.
* The payload for each entry script is:

  * A **subset of the original form data**, filtered to that component’s schema.
  * Serialized as a dictionary of key/value pairs for that component.

PowerShell execution model:

* Each entry script:

  * Executes under a job.
  * Writes verbose/log output captured for display in the UI.
  * Returns a basic success/failure indication (exit code) plus any structured job output needed by the server (e.g. VM ID).

Versioning:

* Versioning is currently minimal:

  * Some schema metadata (schema name/version), but no sophisticated backward compatibility or multi-version management.
  * Assumed deployment model: hosts and server code are kept in sync.

---

## 7. Managed Deployment Service (UI-Facing Orchestration)

The **Managed Deployment Service** is a server-side orchestrator that provides a **simple, rigid “New VM” experience** for most users while still being compatible with the decomposed model.

Characteristics:

* Shape is **fixed**:

  * Exactly **1 VM**, **1 Disk**, **1 NIC**.
* It is **generic enough** for most common “create a normal VM” scenarios but intentionally does not cover every advanced use case.
* For more complex configurations:

  * Users can:

    * Start with a managed deployment to get the initial VM.
    * Then use **independent Disk/NIC APIs** (or UI wrappers around them) to add extra disks/NICs.
    * Or use Terraform for full declarative control later.

### 7.1. UI Integration

From the UI perspective:

* There is still **one “Create VM” form**:

  * The front-end loads all three schemas (VM, Disk, NIC).
  * It composes them into a single rendered form.
  * On submit, it:

    * Validates according to each schema.
    * Produces an aggregated JSON payload.

The Managed Deployment Service then:

1. **Parses the composite payload** into:

   * VM-relevant fields (per VM schema).
   * Disk-relevant fields (per Disk schema).
   * NIC-relevant fields (per NIC schema).
   * Guest config fields (flagged across all three).
2. **Creates a managed deployment job**:

   * Internally:

     1. Calls the **VM create** API (step 1).
     2. On success, obtains the VM ID.
     3. Calls **Disk create** with the VM ID (step 2).
     4. Calls **NIC create** with the VM ID (step 3).
     5. Composes all guest config fields into a single guest config payload.
     6. Calls **Initialization** (step 4) with that guest config.

Job behavior:

* The managed deployment API is **asynchronous**:

  * It returns a job ID immediately.
  * The UI polls for completion and shows job logs (aggregated from the underlying steps).

---

## 8. Initialization / Guest Specialization (Step 4)

The **fourth component** is the initialization / guest specialization action. Its responsibilities include:

* Receiving the **composed guest configuration payload**:

  * Flat dictionary of encrypted-to-be key/value pairs like hostname, local admin password, IP configuration, domain join settings, Ansible config, etc.
* Running the existing **“inject provisioning data”** logic:

  * Performs an asymmetric encryption key exchange.
  * Encrypts each guest configuration value.
  * Writes the encrypted payload into **Hyper-V KVP**.
* **Powering on the VM**:

  * The VM is powered on in this step, not before.
* Potentially orchestrating **cluster registration** (with a caveat):

  * If the user has requested clustering, this is intended to be part of step 4.
  * However, there is a design tension:

    * For KVP-based provisioning to work reliably, the VM must remain on a **single host** until guest specialization completes.
    * Clustering (and especially live migration) could interfere with that requirement.
  * This is an open issue that needs further design:

    * Ideally, cluster enablement should occur **after** provisioning completes, but that conflicts with the idea of doing it in step 4.

In short: step 4 is the **centralized point** where guest config is applied and the VM is booted, and (eventually) where cluster registration is considered, subject to constraints.

---

## 9. Terraform-Facing Model (Intended Direction)

The refactor is explicitly designed so Terraform can later interact with AetherV as a set of **primitive resources**:

* Planned Terraform resource types (conceptually):

  * `aetherv_vm` – create/update/delete VM.
  * `aetherv_disk` – create/update/delete disk (requires VM ID).
  * `aetherv_nic` – create/update/delete NIC (requires VM ID).
  * `aetherv_vm_init` (or similar) – triggers the guest initialization / provisioning.

Key points:

* Terraform will **not** call the Managed Deployment endpoint.

  * That endpoint is specifically for non-Terraform, UI-driven workflows.
* Terraform will use the **component APIs directly**:

  * Create VM first, then Disk and NIC (using `depends_on` and/or explicit IDs), then Init.
* The refactor’s separation into four component agents and APIs is meant to be a near-direct reflection of the Terraform resource model.

---

## 10. Current Limitations & Open Design Questions

Some constraints and known gaps in the current design:

* **No persistent state / job resumption**:

  * If the application crashes mid-job, the job is simply lost.
  * Any retry would be a fresh job, and it’s up to the calling system to handle partial resources that were already created.
* **No automatic rollback**:

  * Resources created before a failure are left in Hyper-V.
  * Operators (or future tooling) must clean these up if needed.
* **Managed deployment is intentionally rigid**:

  * Exactly one VM, disk, NIC.
  * Advanced layouts require post-deployment steps or Terraform.
* **Clustering timing issue**:

  * Ideal behavior (cluster after provisioning) is in tension with the current idea of “cluster as part of step 4.”
  * Needs a clearer model to ensure KVP-based provisioning completes on a single host.
