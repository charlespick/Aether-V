# Aether-V Orchestrator

A lightweight, stateless orchestration service for managing Hyper-V virtual machines. Built to replace AWX/Ansible with a modern, containerized solution that runs on Kubernetes.

## Features

- 🚀 **Stateless Design**: All state in-memory, reconstructed from Hyper-V hosts on startup
- 🔐 **OIDC Authentication**: Enterprise-ready auth with Microsoft Entra ID (Azure AD) support
- 🌐 **REST API**: Complete API for automation and integration
- 💻 **Web UI**: Simple, modern interface for inventory management
- 📦 **Containerized**: Docker container ready for Kubernetes deployment
- ⚡ **Fast**: Direct WinRM execution of existing PowerShell scripts
- 🔄 **Auto-refresh**: Periodic inventory updates from all hosts

## Architecture

The orchestrator is a single Python FastAPI application that:

1. Connects to Hyper-V hosts via WinRM
2. Queries inventory periodically and stores in-memory
3. Executes VM provisioning/deletion jobs using existing PowerShell scripts
4. Provides REST API and web UI for management
5. Delegates auth, config, and HA to Kubernetes

## Quick Start

### Prerequisites

- Kubernetes cluster
- Hyper-V hosts with WinRM enabled
- OIDC provider (Azure AD recommended) or disable auth for development

**Note**: PowerShell scripts and ISOs are automatically deployed to hosts by the service at startup. No manual installation required!

### Development Mode (No Auth)

Create a `.env` file:

```env
DEBUG=true
OIDC_ENABLED=false
HYPERV_HOSTS=hyperv01.local,hyperv02.local
WINRM_USERNAME=DOMAIN\\username
WINRM_PASSWORD=password
WINRM_TRANSPORT=ntlm
```

Run locally:

```bash
cd server
pip install -r requirements.txt
python -m app.main
```

Visit http://localhost:8000 for the UI or http://localhost:8000/docs for API documentation.

### Production Deployment on Kubernetes

1. **Create namespace:**
   ```bash
   kubectl apply -f k8s/namespace.yaml
   ```

2. **Configure secrets:**
   
   Edit `k8s/secret.yaml` with your credentials:
   - OIDC client secret
   - WinRM credentials
   - Optional API token for automation
   
   ```bash
   kubectl apply -f k8s/secret.yaml
   ```

3. **Configure settings:**
   
   Edit `k8s/configmap.yaml`:
   - Set your Hyper-V host list
   - Configure OIDC issuer URL and client ID
   - Adjust refresh intervals if needed
   
   ```bash
   kubectl apply -f k8s/configmap.yaml
   ```

4. **Deploy the application:**
   ```bash
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/service.yaml
   ```

5. **Configure ingress:**
   
   Edit `k8s/ingress.yaml` with your domain name, then:
   ```bash
   kubectl apply -f k8s/ingress.yaml
   ```

6. **Verify deployment:**
   ```bash
   kubectl -n aetherv get pods
   kubectl -n aetherv logs -f deployment/aetherv-orchestrator
   ```

## API Documentation

Once running, visit `/docs` for interactive API documentation (Swagger UI) or `/redoc` for alternative documentation.

### Key Endpoints

- `GET /api/v1/inventory` - Get complete inventory
- `GET /api/v1/hosts` - List Hyper-V hosts
- `GET /api/v1/vms` - List all VMs
- `POST /api/v1/vms/create` - Create a new VM
- `POST /api/v1/vms/delete` - Delete a VM
- `GET /api/v1/jobs/{job_id}` - Get job status

### Example: Create a VM

```bash
curl -X POST "https://aetherv.example.com/api/v1/vms/create" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-vm-01",
    "image_name": "Windows Server 2022",
    "hyperv_host": "hyperv01.local",
    "gb_ram": 4,
    "cpu_cores": 2,
    "guest_la_uid": "Administrator",
    "guest_la_pw": "YourSecurePassword123!",
    "guest_v4_ipaddr": "192.168.1.100",
    "guest_v4_cidrprefix": 24,
    "guest_v4_defaultgw": "192.168.1.1",
    "guest_v4_dns1": "192.168.1.10"
  }'
```

## Configuration

All configuration is via environment variables (from ConfigMap and Secrets in Kubernetes):

### Application Settings
- `DEBUG` - Enable debug mode (default: false)
- `APP_VERSION` - Application version

### OIDC Authentication
- `OIDC_ENABLED` - Enable OIDC auth (default: true)
- `OIDC_ISSUER_URL` - OIDC provider URL
- `OIDC_CLIENT_ID` - OIDC client ID
- `OIDC_CLIENT_SECRET` - OIDC client secret (from Secret)
- `OIDC_ROLE_NAME` - Required role claim (default: "vm-admin")
- `API_TOKEN` - Optional static token for automation (from Secret)

### Hyper-V Settings
- `HYPERV_HOSTS` - Comma-separated list of Hyper-V hosts
- `WINRM_USERNAME` - WinRM username (from Secret)
- `WINRM_PASSWORD` - WinRM password (from Secret)
- `WINRM_TRANSPORT` - Transport protocol: ntlm, basic, credssp (default: ntlm)
- `WINRM_PORT` - WinRM port (default: 5985)

### Inventory Settings
- `INVENTORY_REFRESH_INTERVAL` - Seconds between inventory refreshes (default: 60)

### Host Deployment Settings
- `DEVELOPMENT_INSTALL` - Use development directory on hosts (default: false)

## Orchestration Logic

The orchestrator mirrors the existing Ansible playbooks:

### VM Creation (mirrors `Provisioning.yaml`)
1. Copy image to target host
2. Copy provisioning ISO
3. Register VM with Hyper-V
4. Wait for VM to signal readiness
5. Publish provisioning data via KVP
6. Optionally add to cluster

### VM Deletion
1. Stop VM (if force=true)
2. Remove VM from Hyper-V
3. Delete VM files

## Monitoring

### Health Checks

- `/healthz` - Basic health check
- `/readyz` - Readiness check (verifies inventory initialized)

Kubernetes probes are configured in the deployment manifest.

### Logs

View logs with kubectl:
```bash
kubectl -n aetherv logs -f deployment/aetherv-orchestrator
```

## Security Considerations

1. **Authentication**: Always enable OIDC in production
2. **Secrets**: Use Kubernetes Secrets, never commit credentials
3. **Network**: Use Ingress with TLS termination
4. **RBAC**: Configure Kubernetes RBAC appropriately
5. **WinRM**: Use HTTPS transport (port 5986) in production

## Troubleshooting

### Inventory not updating
- Check WinRM connectivity: `Test-WSMan -ComputerName <host>`
- Verify credentials in Secret
- Check firewall rules for WinRM port

### Authentication failures
- Verify OIDC configuration in ConfigMap
- Check OIDC provider is reachable
- Validate client ID and secret

### Job failures
- Check job output: `GET /api/v1/jobs/{job_id}`
- Verify PowerShell scripts are deployed on hosts
- Check host logs in job output

## Development

### Project Structure
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

### Running Tests

(Tests to be added in future iterations)

```bash
pytest
```

### Building Container Locally

```bash
cd server
docker build -t aetherv-orchestrator:dev .
docker run -p 8000:8000 --env-file .env aetherv-orchestrator:dev
```

## Roadmap

- [x] Basic FastAPI application
- [x] WinRM connectivity
- [x] Inventory management
- [x] Job execution
- [x] Web UI
- [x] OIDC authentication
- [x] Kubernetes manifests
- [x] Container build pipeline
- [x] ISO building at container build time
- [x] Script and ISO deployment to hosts at startup
- [ ] Enhanced job logging
- [ ] Terraform provider integration
- [ ] Multiple replica support with leader election
- [ ] Persistent job history

## Contributing

See the main [HLVMM repository](https://github.com/charlespick/HLVMM) for contribution guidelines.

## License

See LICENSE file in the repository root.
