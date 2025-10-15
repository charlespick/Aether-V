
# 🧩 Project Planning Document — Hyper-V Orchestration Service

### **Project Summary**

This project is a lightweight orchestration service for provisioning and managing virtual machines on Hyper-V hosts using existing PowerShell automation logic. It replaces the Ansible-AWX frontend with a self-contained, containerized Python web service that exposes a REST API and simple web UI. The system is entirely stateless and relies on Kubernetes primitives for configuration, high availability, and secret management.

The service is intended to act as a foundation for future integrations — including Terraform provider support — while remaining as simple as possible in its initial implementation.

---

## **Core Design Philosophy**

1. **Stateless by design**

   * No local or external databases, queues, or durable stores.
   * All operational state (inventory, job queue, logs) lives in memory.
   * On restart, the service reconstructs state by querying connected Hyper-V hosts.
   * If a job is interrupted mid-run, the next reconciliation or external IaC tool (e.g., Terraform) will converge state automatically.

2. **Delegate infrastructure responsibilities outward**

   | Concern                        | Delegated To                                  | Notes                                             |
   | ------------------------------ | --------------------------------------------- | ------------------------------------------------- |
   | Configuration                  | Kubernetes ConfigMaps & environment variables | Cluster names, host list, update intervals        |
   | Secrets                        | Kubernetes Secrets                            | WinRM credentials, OIDC client secret, API tokens |
   | TLS termination                | Kubernetes Ingress Controller                 | TLS certs handled externally                      |
   | Authentication & Authorization | External OIDC provider (e.g., Entra ID)       | Role claim checked in token                       |
   | High Availability              | Kubernetes scheduler                          | Restart on crash; single replica only             |
   | Logging                        | Standard output + Kubernetes log aggregation  | Persistent storage optional                       |
   | Job scheduling                 | In-process threads or asyncio coroutines      | Kubernetes Jobs optional for future scale-out     |

3. **Reuse existing logic**

   * The orchestration layer wraps existing PowerShell scripts and ISO deployment logic.
   * All provisioning work is executed remotely on the Hyper-V host via WinRM.
   * No direct guest connections are required; all guest customization is handled via ISOs and KVP.

---

## **High-Level Architecture**

```
+--------------------------------------------------------------+
|                Kubernetes Cluster                            |
|                                                              |
|  +--------------------------------------------------------+  |
|  |    hyperv-orchestrator (single container process)      |  |
|  |--------------------------------------------------------|  |
|  |  FastAPI Web Server:                                   |  |
|  |    - REST API (/api/v1/...)                            |  |
|  |    - Static Web UI (/ui)                               |  |
|  |                                                        |  |
|  |  Inventory Manager:                                    |  |
|  |    - On startup, query all Hyper-V hosts               |  |
|  |    - Maintain in-memory list of VMs, templates, hosts  |  |
|  |                                                        |  |
|  |  Job Runner:                                           |  |
|  |    - Execute provisioning/deletion tasks               |  |
|  |    - Uses WinRM to transfer ISOs & scripts             |  |
|  |    - Invokes PowerShell remotely with params           |  |
|  |                                                        |  |
|  |  Auth Middleware:                                      |  |
|  |    - Validates OIDC token                              |  |
|  |    - Enforces role-based access                        |  |
|  +--------------------------------------------------------+  |
|                                                              |
+--------------------------------------------------------------+
```

---

## **Startup and Runtime Behavior**

1. **Startup Sequence**

   1. Read configuration from environment variables and ConfigMaps.
   2. Load WinRM credentials from Kubernetes Secrets.
   3. Deploy artifacts to Hyper-V hosts:
      * Check version on each host
      * Deploy scripts and ISOs if version mismatch detected
      * Scripts and ISOs are bundled in container (built at container build time)
   4. Establish WinRM connections to all listed Hyper-V hosts.
   5. Query each host for available virtual machines.
   6. Store inventory in memory.
   7. Expose REST API and web UI.

2. **Runtime Behavior**

   * Periodic background task re-queries inventory (interval configurable).
   * Users or automation (Terraform, API clients, or web UI) submit job requests:

     * Example: *Create new VM → choose host, template, name, vCPUs, VLAN, etc.*
   * Job runner executes:

     1. Run PowerShell creation scripts via WinRM with injected variables.
     2. Monitor script output and stream logs back to client.
     
   Note: Scripts and ISOs are deployed at startup, not at job time.
   * Job result and logs are held in memory until service restart.

3. **Failure and Restart Behavior**

   * If the process or pod crashes:

     * Any running jobs are lost.
     * On restart, inventory is rebuilt.
     * Terraform or external IaC tool can reapply configuration to converge.

---

## **Authentication and Authorization**

* **OIDC Provider:** Microsoft Entra ID (Azure AD)
* **Flow:** Browser redirect or API token exchange
* **Validation:** Token verified against OIDC discovery endpoint and JWKS keys
* **Role Enforcement:** A specific claim (e.g., `"roles": ["vm-admin"]`) is required for access.
* **Configuration:**

  * Provided via environment variables:

    ```
    OIDC_ISSUER_URL=https://login.microsoftonline.com/<tenant_id>/v2.0
    OIDC_CLIENT_ID=...
    OIDC_ROLE_NAME=vm-admin
    ```
  * Client secret provided via Kubernetes Secret.

---

## **Configuration Management**

| Configuration Type              | Kubernetes Primitive | Example                            |
| ------------------------------- | -------------------- | ---------------------------------- |
| Cluster/host definitions        | ConfigMap            | `hosts.yaml` or inline JSON        |
| Update intervals, logging level | ConfigMap / env vars | `INVENTORY_REFRESH_INTERVAL=60`    |
| WinRM credentials               | Secret               | `winrm_username`, `winrm_password` |
| OIDC secrets                    | Secret               | `client_secret`                    |
| Script/ISO source paths         | ConfigMap            | `SCRIPT_PATH`, `ISO_PATH`          |

* **Mounted Secrets:**

  * Kubernetes can mount a Secret as files inside the container (e.g., `/run/secrets/winrm_password`), allowing the app to read credentials from disk rather than environment variables.
  * This avoids exposing secrets in process listings or crash logs.

---

## **Component Summary**

| Component           | Technology                         | Responsibility                              |
| ------------------- | ---------------------------------- | ------------------------------------------- |
| **Web Framework**   | FastAPI                            | REST API and UI routing                     |
| **Web Server**      | Uvicorn                            | ASGI server for FastAPI                     |
| **Task Runner**     | Python `asyncio` or threads        | Run provisioning/deletion tasks             |
| **WinRM Interface** | `pywinrm`                          | Execute PowerShell scripts on Hyper-V hosts |
| **Auth**            | `authlib` or `fastapi-oidc`        | OIDC validation                             |
| **Deployment**      | Kubernetes Deployment (replicas=1) | Self-healing single pod                     |
| **Configuration**   | ConfigMaps + Secrets               | Environment and credential injection        |
| **TLS + Routing**   | Ingress Controller                 | Termination and routing to the service      |
| **Inventory Cache** | In-memory Python dicts             | Rebuilt on restart                          |

---

## **Kubernetes Resources**

* **Deployment:**

  * 1 replica
  * RestartPolicy: Always
  * Environment variables populated from ConfigMap and SecretRefs
  * Liveness/Readiness probes on `/healthz` and `/readyz`

* **Service:**

  * ClusterIP or LoadBalancer for internal/external access

* **Ingress:**

  * TLS termination
  * OIDC callback endpoint routed to `/oidc/callback`

* **ConfigMap:**

  * Contains list of Hyper-V hosts and cluster definitions

* **Secrets:**

  * Contains WinRM credentials, OIDC client secret, optional API keys

---

## **Future Expansion Roadmap**

| Milestone   | Feature                                                                     | Notes                              |
| ----------- | --------------------------------------------------------------------------- | ---------------------------------- |
| **MVP**     | Single container, no persistence, FastAPI REST + UI, WinRM job execution    | Target for initial release         |
| **Phase 2** | Add Terraform provider integration                                          | Allow Terraform `apply` → API call |
| **Phase 3** | Add structured logs & audit via external backend (e.g., Loki or PostgreSQL) | Optional durability                |
| **Phase 4** | Add multi-replica leader election                                           | Optional HA at service level       |
| **Phase 5** | Add granular job resume & history                                           | Introduce persistence if justified |

---

## **Example Configuration Summary**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hyperv-orchestrator
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: orchestrator
          image: myrepo/hyperv-orchestrator:latest
          envFrom:
            - configMapRef:
                name: orchestrator-config
            - secretRef:
                name: orchestrator-secrets
          volumeMounts:
            - name: secrets
              mountPath: /run/secrets
              readOnly: true
      volumes:
        - name: secrets
          secret:
            secretName: orchestrator-secrets
```

---

## **Deliverables for This Phase**

1. **FastAPI skeleton app**

   * `/api/v1/hosts` — List Hyper-V hosts
   * `/api/v1/vms` — List VMs (aggregated inventory)
   * `/api/v1/vms/create` — Provision VM
   * `/api/v1/vms/delete` — Delete VM
   * `/healthz` and `/readyz` endpoints

2. **In-memory job management**

   * Async worker queue
   * Threaded job runner for WinRM calls
   * Periodic inventory refresh task

3. **OIDC integration**

   * Role validation middleware
   * Simple login redirect and token exchange (future-friendly)

4. **Kubernetes YAMLs**

   * Deployment, ConfigMap, Secret, Service, Ingress

5. **Web UI**

   * Basic HTML/JS frontend bundled with FastAPI
   * List inventory and launch new VM forms

---

## **Summary**

This next phase focuses on **simplifying the architecture to its logical minimum**:

* One process
* One container
* One replica
* Zero state
* Delegated configuration, authentication, and security

From this foundation, higher-order features like Terraform integration, durability, or job history can be layered on later without re-architecting the core system.
