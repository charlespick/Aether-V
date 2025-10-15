# Aether-V Orchestrator - Deployment Guide

This guide covers deploying the Aether-V Orchestrator on Kubernetes for development and production environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Preparing Hyper-V Hosts](#preparing-hyper-v-hosts)
3. [Setting up OIDC (Optional but Recommended)](#setting-up-oidc)
4. [Deploying to Kubernetes](#deploying-to-kubernetes)
5. [Verifying Deployment](#verifying-deployment)
6. [Development Deployment](#development-deployment)

## Prerequisites

### Infrastructure Requirements

- **Kubernetes Cluster**: v1.24+ recommended
  - kubectl configured to access your cluster
  - Sufficient resources (minimum 512Mi memory, 500m CPU)
  
- **Hyper-V Hosts**: One or more Windows Server hosts running Hyper-V
  - PowerShell scripts from HLVMM project deployed
  - WinRM enabled and accessible from Kubernetes cluster
  
- **OIDC Provider** (optional for production):
  - Microsoft Entra ID (Azure AD) recommended
  - Or any OIDC-compliant identity provider

### Tools Required

- `kubectl` - Kubernetes CLI
- `docker` (optional, for local testing)
- `helm` (optional, for advanced deployments)

## Preparing Hyper-V Hosts

### 1. Deploy PowerShell Scripts

The orchestrator uses the existing PowerShell scripts from the HLVMM project. Deploy them to each Hyper-V host:

```powershell
# On each Hyper-V host
$url = "https://raw.githubusercontent.com/charlespick/HLVMM/main/Scripts/InstallHostScripts.ps1"
Invoke-WebRequest -Uri $url -OutFile C:\Temp\InstallHostScripts.ps1
C:\Temp\InstallHostScripts.ps1
```

This installs scripts to: `C:\Program Files\Home Lab Virtual Machine Manager\`

### 2. Enable WinRM

Ensure WinRM is enabled and configured:

```powershell
# Enable WinRM
Enable-PSRemoting -Force

# Configure basic auth (if needed)
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true

# Allow unencrypted traffic (for HTTP, use HTTPS in production)
Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $true

# Configure firewall
New-NetFirewallRule -Name "WinRM-HTTP" -DisplayName "WinRM HTTP" `
  -Enabled True -Direction Inbound -Protocol TCP -LocalPort 5985

# Test WinRM
Test-WSMan
```

### 3. Prepare Golden Images

Ensure golden images are available on cluster storage:
- Path: `C:\ClusterStorage\*\DiskImages\`
- Format: VHDX files named `<ImageName>.vhdx`

### 4. Network Connectivity

Verify network connectivity from Kubernetes to Hyper-V hosts:
- Ensure Kubernetes nodes or pods can reach hosts on port 5985 (HTTP) or 5986 (HTTPS)
- Configure firewall rules as needed

## Setting up OIDC

### Microsoft Entra ID (Azure AD) Setup

1. **Register an Application**:
   - Go to Azure Portal → Azure Active Directory → App registrations
   - New registration
   - Name: "Aether-V Orchestrator"
   - Redirect URI: `https://aetherv.example.com/oidc/callback` (adjust domain)

2. **Configure App Roles**:
   - In your app registration, go to App roles
   - Create new role:
     - Display name: "VM Administrator"
     - Value: `vm-admin`
     - Description: "Can manage virtual machines"
     - Allowed member types: Users/Groups

3. **Generate Client Secret**:
   - Certificates & secrets → New client secret
   - Copy the secret value (you won't see it again)

4. **Assign Users**:
   - Enterprise applications → Your app → Assign users and groups
   - Add users/groups with the "VM Administrator" role

5. **Note Configuration Values**:
   - Client ID: Found in app overview
   - Tenant ID: Found in app overview
   - Client Secret: From step 3
   - Issuer URL: `https://login.microsoftonline.com/<tenant-id>/v2.0`

### Development Mode (No OIDC)

For development, you can disable OIDC authentication:

Set in ConfigMap:
```yaml
OIDC_ENABLED: "false"
```

This allows all requests without authentication. **DO NOT use in production!**

## Deploying to Kubernetes

### Step 1: Create Namespace

```bash
kubectl apply -f k8s/namespace.yaml
```

### Step 2: Configure Secrets

Edit `k8s/secret.yaml` and replace placeholders:

```yaml
stringData:
  # OIDC (if enabled)
  OIDC_CLIENT_SECRET: "your-actual-secret-here"
  
  # Optional API token for automation
  API_TOKEN: "generate-a-secure-token"
  
  # WinRM credentials
  WINRM_USERNAME: "DOMAIN\\serviceaccount"
  WINRM_PASSWORD: "actual-password-here"
```

Apply the secret:
```bash
kubectl apply -f k8s/secret.yaml
```

**Security Note**: Never commit secrets to version control. Consider using:
- Sealed Secrets
- External Secrets Operator
- Vault
- Cloud provider secret managers

### Step 3: Configure Settings

Edit `k8s/configmap.yaml`:

```yaml
data:
  # Your OIDC configuration
  OIDC_ISSUER_URL: "https://login.microsoftonline.com/<your-tenant-id>/v2.0"
  OIDC_CLIENT_ID: "<your-client-id>"
  
  # Your Hyper-V hosts
  HYPERV_HOSTS: "hyperv01.mydomain.com,hyperv02.mydomain.com"
  
  # Adjust settings as needed
  INVENTORY_REFRESH_INTERVAL: "60"
```

Apply the ConfigMap:
```bash
kubectl apply -f k8s/configmap.yaml
```

### Step 4: Deploy Application

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### Step 5: Configure Ingress

Edit `k8s/ingress.yaml` with your domain:

```yaml
spec:
  tls:
  - hosts:
    - aetherv.yourdomain.com  # Your actual domain
    secretName: aetherv-tls
  rules:
  - host: aetherv.yourdomain.com  # Your actual domain
```

Apply the Ingress:
```bash
kubectl apply -f k8s/ingress.yaml
```

**Note**: Ensure you have:
- An Ingress Controller installed (nginx, traefik, etc.)
- DNS pointing to your ingress controller
- cert-manager for automatic TLS (or manually create TLS secret)

## Verifying Deployment

### Check Pod Status

```bash
kubectl -n aetherv get pods
```

Expected output:
```
NAME                                    READY   STATUS    RESTARTS   AGE
aetherv-orchestrator-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
```

### Check Logs

```bash
kubectl -n aetherv logs -f deployment/aetherv-orchestrator
```

Look for:
```
INFO - Starting Aether-V Orchestrator
INFO - Version: 0.1.0
INFO - Starting inventory service
INFO - Refreshing inventory for host: hyperv01.local
INFO - Host hyperv01.local: 5 VMs
INFO - Application started successfully
```

### Test Health Endpoints

```bash
# Inside cluster
kubectl -n aetherv run curl --image=curlimages/curl --rm -it --restart=Never -- \
  curl http://aetherv-orchestrator/healthz

# From outside cluster (after ingress setup)
curl https://aetherv.yourdomain.com/healthz
```

Expected response:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### Access Web UI

Open in browser:
```
https://aetherv.yourdomain.com/
```

You should see the Aether-V dashboard with hosts and VMs.

### Test API

```bash
# Get API token (from your authentication provider or use static token)
TOKEN="your-token-here"

# List hosts
curl -H "Authorization: Bearer $TOKEN" \
  https://aetherv.yourdomain.com/api/v1/hosts

# List VMs
curl -H "Authorization: Bearer $TOKEN" \
  https://aetherv.yourdomain.com/api/v1/vms
```

## Development Deployment

For rapid development without OIDC:

### Local Docker Deployment

1. Create `.env` file:
```bash
cd server
cp .env.example .env
# Edit .env with your settings
```

2. Build and run:
```bash
docker build -t aetherv-orchestrator:dev .
docker run -p 8000:8000 --env-file .env aetherv-orchestrator:dev
```

3. Access at http://localhost:8000

### Kubernetes Development Deployment

Use the same steps as production but with:

1. **Disable OIDC** in ConfigMap:
```yaml
OIDC_ENABLED: "false"
```

2. **Use NodePort** instead of Ingress:
```yaml
# In k8s/service.yaml
spec:
  type: NodePort
  ports:
  - port: 80
    targetPort: http
    nodePort: 30800  # Pick an available port
```

3. Access via: `http://<node-ip>:30800`

### Hot Reload for Development

For active development:

```bash
cd server
pip install -r requirements.txt

# Run with auto-reload
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Troubleshooting

### Pods not starting

```bash
# Describe pod for events
kubectl -n aetherv describe pod <pod-name>

# Check logs
kubectl -n aetherv logs <pod-name>
```

Common issues:
- Missing secrets or configmap
- Image pull errors (check GHCR access)
- Resource limits too low

### Inventory not refreshing

- Verify WinRM connectivity from pod to hosts
- Check credentials in Secret
- Test manually:
```bash
kubectl -n aetherv exec -it deployment/aetherv-orchestrator -- /bin/bash
# Inside pod, try reaching host
```

### Authentication issues

- Verify OIDC configuration matches your provider
- Check redirect URI is correct
- Ensure users have the required role assigned
- Check logs for OIDC-related errors

### Job execution failures

- Check PowerShell scripts are deployed on hosts
- Verify WinRM credentials have sufficient privileges
- Review job output via API: `GET /api/v1/jobs/{job_id}`

## Updating Deployment

### Update Configuration

```bash
# Edit configmap
kubectl -n aetherv edit configmap aetherv-config

# Or apply updated file
kubectl apply -f k8s/configmap.yaml

# Restart pods to pick up changes
kubectl -n aetherv rollout restart deployment aetherv-orchestrator
```

### Update Container Image

```bash
# Update image in deployment
kubectl -n aetherv set image deployment/aetherv-orchestrator \
  orchestrator=ghcr.io/charlespick/aetherv-orchestrator:latest

# Or apply updated deployment file
kubectl apply -f k8s/deployment.yaml
```

## Scaling

The orchestrator uses in-memory state and is designed to run as a **single replica**. 

For high availability:
- Kubernetes will restart the pod if it crashes
- Inventory is rebuilt on startup
- In-flight jobs may be lost on restart (future enhancement)

Future versions may support:
- Multiple replicas with leader election
- Persistent job queue
- Distributed caching

## Backup and Recovery

### Configuration Backup

```bash
# Export current configuration
kubectl -n aetherv get configmap aetherv-config -o yaml > backup-configmap.yaml
kubectl -n aetherv get secret aetherv-secrets -o yaml > backup-secret.yaml
```

### Disaster Recovery

If the pod is lost:
1. Kubernetes will automatically restart it
2. Inventory is rebuilt from Hyper-V hosts
3. Previous job history is lost (in-memory only)

For critical jobs, use external monitoring/automation (e.g., Terraform) to ensure desired state.

## Next Steps

- Configure monitoring with Prometheus
- Set up log aggregation with Loki/ELK
- Implement automated backups of configuration
- Integrate with CI/CD pipelines
- Develop Terraform provider for IaC integration

## Support

For issues or questions:
- Check GitHub Issues: https://github.com/charlespick/HLVMM/issues
- Review logs for detailed error messages
- Consult the main README.md for API documentation
