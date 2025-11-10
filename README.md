
# Aether-V

Aether-V is a unified solution for modern workload management on Hyper-V, providing a complete platform that includes a web frontend, orchestration service, and guest agents. Designed for both homelab and enterprise environments, Aether-V streamlines VM provisioning, configuration, and lifecycle management with secure, resilient architecture.

## Overview

Aether-V enables automated, secure, and scalable management of Hyper-V virtual machines. It features a stateless orchestration service—no persistent storage required—making deployment and scaling simple. All state is reconstructed in-memory from Hyper-V hosts at runtime, ensuring reliability and minimal infrastructure footprint.

## Key Features

- **Unified Platform:** Web UI, REST API, and guest agents for end-to-end VM lifecycle management.
- **Stateless Operation:** No persistent storage; service state is always derived from live Hyper-V hosts.
- **Encrypted Provisioning Data:** VM provisioning data is injected via Hyper-V KVP, encrypted so only the VM can access secrets after provisioning.
- **OIDC Authentication:** Enterprise-ready authentication with Microsoft Entra ID (Azure AD) for users and service principals.
- **Containerized & Kubernetes-ready:** Easy deployment and scaling in cloud-native environments.
- **Auto-refresh Inventory:** Periodic updates from all hosts.
- **No SCVMM or SQL Server Required:** Minimal infrastructure footprint.

## How It Works

1. **Provisioning:** Host copies image and provisioning media, configures and starts VM.
2. **Secure Data Injection:** Guest VM receives encrypted provisioning data via KVP.
3. **Self-contained Customization:** All secrets remain inside the VM; no external exposure.
4. **Unified Management:** Use the web UI, REST API, or (future) Terraform provider for VM lifecycle operations.

## Getting Started

### Prerequisites

- Kubernetes cluster
- Hyper-V hosts with WinRM enabled
- OIDC provider (Azure AD recommended) or disable auth for development

The orchestration service relies on the [`pypsrp`](https://github.com/jborean93/pypsrp) library for PowerShell Remoting Protocol
(PSRP) communication. Aether-V now authenticates exclusively with Kerberos using a pre-generated keytab. Ensure the
container hosts have network line-of-sight to your domain controllers, the service principal exists, and resource-based
delegation is enabled on every Hyper-V host and cluster computer object that Aether-V will manage.

### Development Setup

1. Create a `.env` file with your settings (see below).
2. Run locally:
    ```bash
    cd server
    pip install -r requirements.txt
    python -m app.main
    ```
3. Access the UI at [http://localhost:8000](http://localhost:8000) or API docs at `/docs`.

### Production Deployment

1. Configure Kubernetes manifests (`server/k8s/`):
    - Namespace, secrets, configmap, deployment, service, ingress
2. Edit secrets and configmap for credentials and settings.
3. Deploy with `kubectl apply -f k8s/<manifest>.yaml`.

## Configuration

All settings are managed via environment variables (ConfigMap/Secrets):

- `DEBUG`, `APP_VERSION`
- `AUTH_ENABLED`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_API_AUDIENCE`
- `OIDC_READER_PERMISSIONS`, `OIDC_WRITER_PERMISSIONS`, `OIDC_ADMIN_PERMISSIONS`
- `HYPERV_HOSTS`, `WINRM_KERBEROS_PRINCIPAL`, `WINRM_KERBEROS_KEYTAB`, `WINRM_KERBEROS_CCACHE`, `WINRM_PORT`
- `INVENTORY_REFRESH_INTERVAL`
- `HOST_INSTALL_DIRECTORY`
- `AGENT_DOWNLOAD_BASE_URL`

See [Docs/Host-Setup.md](Docs/Host-Setup.md) for host configuration details, the
Kerberos-specific onboarding steps in [Docs/KerberosSetup.md](Docs/KerberosSetup.md), plus
[Docs/vm-provisioning-service.md](Docs/vm-provisioning-service.md) and
[Docs/vm-deletion-service.md](Docs/vm-deletion-service.md) for end-to-end job
workflows.

## API & UI

- **Inventory:** `GET /api/v1/inventory`
- **Hosts:** `GET /api/v1/hosts`
- **VMs:** `GET /api/v1/vms`, `POST /api/v1/vms/create`, `POST /api/v1/vms/delete`
- **Jobs:** `GET /api/v1/jobs/{job_id}`
- **Auth:** OIDC login/logout endpoints
- **Health:** `/healthz`, `/readyz`

Interactive API docs: `/docs` (Swagger UI), `/redoc`

## Extending & Customizing

- Extend provisioning scripts (`ProvisioningService.sh/ps1`) for custom logic.
- Add new fields or phases as needed.
- Integrate with automation tools via API or future Terraform provider.

## Security

- Always enable OIDC in production.
- Use Kubernetes Secrets for credentials.
- Enable TLS for ingress.
- Map Microsoft Entra scopes/app roles to `OIDC_READER_PERMISSIONS`, `OIDC_WRITER_PERMISSIONS`, and `OIDC_ADMIN_PERMISSIONS`; access tokens are validated for the configured audience and signing keys.
- Configure RBAC and use HTTPS for WinRM in production.

## Troubleshooting

- Check WinRM connectivity and credentials.
- Review logs via `kubectl logs`.
- Use health endpoints for readiness checks.

## Project Structure

```
server/
├── app/
│   ├── api/           # API routes
│   ├── core/          # Core models and config
│   ├── services/      # Business logic services
│   ├── templates/     # Web UI templates
│   └── main.py        # Application entry point
├── k8s/               # Kubernetes manifests
├── Dockerfile         # Container definition
└── requirements.txt   # Python dependencies
```

## Roadmap

- Enhanced job logging
- Terraform provider integration
- Multi-replica support
- Persistent job history
