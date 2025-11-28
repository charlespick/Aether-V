
# AetherV Server ↔ Host Agent Architecture and Protocol Overview

## 1. Purpose and Scope

This document defines the architecture, responsibilities, and data exchange contract between the AetherV Python server and the Hyper-V host agent. It describes how job requests are structured, how they are processed on the host, how results are returned, and how each layer of the system participates in validation and orchestration.

This document deliberately does not cover:

* UI implementation details, CSS/JS structure, or frontend authentication
* Guest agent implementation details or specific PowerShell/Python code
* Exact service deployment mechanics (Dockerfile steps, CI/CD configuration)

This document *does* cover:

* The canonical API contract between the server and the Hyper-V host agent
* Where validation, orchestration, and domain logic live
* The conceptual data models used for VM, Disk, NIC, and Guest Configuration
* How job requests and job results are constructed and interpreted
* Development workflows: where new behavior should be implemented

The goal is to move away from historical schema-driven form generation and toward a simpler, clearer, and more maintainable architecture in which each layer owns the logic that is appropriate to its domain.

---

## 2. Architecture Overview

AetherV’s orchestration workflow consists of four major components:

1. **Frontend Application (JS/CSS)**
2. **Python Server (FastAPI + Pydantic models)**
3. **Hyper-V Host Agent (PowerShell)**
4. **Guest Agents (Windows and Linux)**

Front-end requests are validated by Pydantic models in the Python server, orchestrated into job requests, and then transmitted to the host agent as structured JSON via STDIN. The host agent executes Hyper-V operations and returns a structured JSON response. For operations that require guest OS configuration, the server derives an appropriate guest configuration payload and sends it through the Hyper-V key-value pair (KVP) mechanism.

All layers are version-locked because the host agents are bundled in the same Docker image as the server and automatically deployed to hosts. No backwards compatibility guarantees are required.

---

## 3. Layer Responsibilities

### 3.1 Frontend Application (JavaScript/CSS)

The frontend is responsible for implementing all interactive UI behavior and input gathering. Because AetherV’s UI needs are relatively modest but do require increasingly richer conditional rendering (e.g., DHCP vs static IP, dynamic memory options, tabbed or conditional layout), the frontend owns all layout and behavioral logic.

Responsibilities:

* Implement UX logic such as toggles, tabs, conditional visibility, and multi-section interfaces.
* Construct JSON payloads that conform to the backend’s Pydantic models.
* Display validation errors returned by the server.
* Treat backend OpenAPI/Pydantic metadata as guidance (labels, descriptions, constraints).

Non-responsibilities:

* Does not perform authoritative input validation beyond basic form checks.
* Does not derive orchestration steps or compute guest configuration.

The frontend’s job is simply to collect user intent and forward it in a clean structure to the server.

---

### 3.2 Python Server (FastAPI)

The Python server is the authoritative control plane and the single source of truth for the API contract. It defines all request/response structures, performs validation, handles orchestration, and interacts with both host agents and guest agents.

Responsibilities:

* **Define canonical Pydantic models** for:

  * VM specification
  * Disk specification
  * NIC specification
  * Guest configuration specification
  * Managed deployment requests
  * Job request envelopes and job result envelopes
* **Perform all user-facing validation**, including:

  * Data type checking
  * Range checks
  * Conditional requirements (e.g., dynamic memory constraints)
  * Cross-field validation
* **Implement orchestration logic**, including:

  * Managed deployments (VM + NIC + Disk + provisioning)
  * Independent CRUD operations for VM, Disk, and NIC (for Terraform use)
* **Construct guest configuration payloads** directly from Pydantic models.
* **Transmit job requests to host agents** as JSON via STDIN.
* **Stream and capture job output**, transform host-agent responses into API responses, and persist job status.

Non-responsibilities:

* Does not implement UI rendering rules.
* Does not rely on runtime YAML schemas for behavior.
* Does not attempt to automatically infer orchestration steps from a schema.

The server owns the protocol. It is where the domain logic and correctness guarantees live.

---

### 3.3 Hyper-V Host Agent (PowerShell)

The host agent is responsible for executing Hyper-V–level operations and computing any values that must be derived from the host environment (e.g., choosing directories, resolving image paths, checking host resource constraints).

Responsibilities:

* Accept a **single JSON job request** via STDIN.
* Parse operation type and payload based on the server’s data model.
* Execute requested actions such as:

  * Creating or modifying virtual machines
  * Creating, locating, or attaching storage
  * Creating, modifying, or attaching network adapters
  * Performing host-level validation of requested configurations
* Compute and return values derived from the host environment:

  * Image path resolution
  * Disk location selection
  * Validation of memory, CPU availability, or other hypervisor constraints
* Return a **JSON job result** containing:

  * status (success, error, partial)
  * machine-readable error code (if applicable)
  * message with human-readable detail
  * structured data (e.g., new VM IDs, file paths)
  * optional logs or debug output

Non-responsibilities:

* Does not interpret UI semantics.
* Does not interpret a general-purpose schema or DSL.
* Does not enforce front-end specific validation rules.

The host agent is a driver, not an orchestrator. It encapsulates Hyper-V’s operational domain knowledge and exposes results in a predictable JSON structure.

---

### 3.4 Guest Agents (Windows and Linux)

Guest agents run inside the virtual machine after the host agent has provisioned disks and booted the VM. Guest configuration is always derived by the Python server and transmitted to the guest via KVP in an encrypted form.

Responsibilities:

* Receive a structured guest configuration dictionary generated by the server.
* Apply OS-specific provisioning tasks:

  * Configure networking
  * Apply domain or authentication settings
  * Initialize services
  * Execute requested provisioning scripts

Non-responsibilities:

* Do not know anything about the front-end or server-side orchestration.
* Do not interact with the host agent directly except through KVP.

Guest agents are simple executors of configuration specified by the server.

---

## 4. Job Request and Job Result Envelope

### 4.1 Job Request Structure

The server sends a single JSON object for each job. While implementation details may vary, the conceptual structure is:

* operation: A string identifying what the agent should perform (“vm.create”, “disk.clone”, “nic.update”, etc.)
* resource_spec: A structured object matching the corresponding Pydantic model
* correlation_id: A unique identifier used for log tracking
* metadata: Optional values such as timestamps, host identifier, or debug flags

The envelope ensures that the agent receives both the intent (operation) and the payload (specification) in a single structured unit.

### 4.2 Job Result Structure

The host agent returns a JSON document with predictable fields:

* status: “success”, “error”, or “partial”
* code: An optional machine-readable error code
* message: Human-readable description of the outcome
* data: Structured output (e.g., created object identifiers, resolved file paths)
* logs: Optional array of log or debug lines generated during execution
* correlation_id: Mirrors the ID sent by the server

The Python server consumes this result, stores job status, and returns a summarized form to API clients.

---

## 5. Guest Configuration Generation

The guest configuration specification is derived directly from the VM, Disk, and NIC specifications using explicit logic in the Python server. Instead of dynamically composing a schema at runtime, the server determines exactly which configuration keys apply and constructs a compact guest configuration dictionary.

This dictionary is:

* Encrypted and transmitted to the guest agent via Hyper-V KVP
* Applied by the in-guest initialization process
* Independent of the UI or host agent behavior

This eliminates the need for a fourth dynamic “schema” and prevents the layering issues encountered previously.

---

## 6. Versioning and Deployment Model

AetherV embeds all PowerShell and guest agent code inside the server’s Docker image. When the server starts, it deploys these agents to managed hosts. Therefore:

* Server and agents are always version-locked.
* No backwards compatibility is required.
* The API contract may evolve freely as long as server and agents update together.

This simplifies development significantly compared to a multi-version plugin ecosystem.

---

## 7. Input Validation and Error Handling

### 7.1 Validation Strategy

Validation is distributed intentionally:

* The **frontend** performs light client-side validation only (basic checks).
* The **Python server** does all user-facing validation using Pydantic models.
* The **host agent** performs environment-level validation:

  * Existence of image paths
  * Hyper-V resource availability
  * Host-specific constraints such as dynamic memory rules

This division keeps validation logic close to where it actually matters.

### 7.2 Error Handling

Host agents return machine-readable error codes when appropriate, enabling the server to categorize failures. The frontend surfaces these to the user.

Partial failures can be represented using the “partial” status value, though the server generally treats orchestration operations as atomic from a user-facing perspective.

---

## 8. Development Workflow for New Features

Adding new VM-level or resource-level functionality requires coordinated updates to three layers. The workflow is explicit and predictable:

1. **Update Pydantic Models in the Python Server**

   * Add new fields to VM, Disk, NIC, or GuestConfig models.
   * Add any necessary validation rules.
   * Update orchestration logic or guest configuration generation.

2. **Update the Frontend Form**

   * Add UI controls corresponding to the new fields.
   * Implement new conditional rendering or behavior as needed.
   * Submit new fields in the JSON payload directly.

3. **Update the Hyper-V Host Agent**

   * Modify PowerShell code to apply the new configuration.
   * Add host-level validation and compute any derived fields.
   * Return updated structured results.

4. **Update Guest Agents (if needed)**

   * Extend provisioning logic to apply new guest configuration keys.

This workflow replaces the older schema-driven approach and focuses development effort where it naturally belongs.

---

## 9. Summary

This architecture replaces a complex, increasingly brittle schema-driven system with a clear division of responsibility:

* The **frontend** manages presentation and user interaction.
* The **Python server** owns the contract, the validation, and the orchestration.
* The **Hyper-V host agent** owns Hyper-V operational logic and host-specific validation.
* The **guest agents** apply final OS-level configuration.

The JSON job request and result envelopes provide a stable, predictable communication protocol. Pydantic models become the authoritative definition of the wire format and serve as the source of truth for validation. Removing the dynamic schema layer simplifies development, improves maintainability, and accelerates delivery of new features while retaining the power and flexibility required for complex VM operations.
