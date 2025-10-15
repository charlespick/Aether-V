# Aether-V Orchestrator - Quick Start

Get up and running in 5 minutes!

## 🎯 What is This?

Aether-V Orchestrator is a lightweight service that manages Hyper-V virtual machines. It replaces AWX/Ansible with a simpler, containerized solution that runs on Kubernetes.

**Key Features:**
- 🌐 Web UI for viewing VMs and hosts
- 🔌 REST API for automation
- 🔐 OIDC authentication (optional)
- 📦 Single container deployment
- ⚡ Fast and stateless

## ⚡ Quick Start Options

### Option 1: Local Development (No Hyper-V Needed)

Perfect for trying out the UI and API:

```bash
cd server
cp .env.example .env
# Edit .env: Set OIDC_ENABLED=false, leave HYPERV_HOSTS empty
./dev.sh
```

Open http://localhost:8000 - You'll see empty inventory but can test the UI.

### Option 2: Local with Hyper-V Hosts

Test with real Hyper-V infrastructure:

```bash
cd server
cp .env.example .env
```

Edit `.env`:
```bash
OIDC_ENABLED=false
HYPERV_HOSTS=hyperv01.yourdomain.com
WINRM_USERNAME=DOMAIN\\username
WINRM_PASSWORD=password
```

Run:
```bash
./dev.sh
```

Open http://localhost:8000 - You'll see your hosts and VMs!

### Option 3: Kubernetes Deployment

Deploy to your cluster:

```bash
cd server/k8s

# Edit secret.yaml with your credentials
# Edit configmap.yaml with your hosts
# Edit ingress.yaml with your domain

kubectl apply -k .

# Watch it start
kubectl -n aetherv get pods -w
```

Access via your ingress domain!

## 📖 Common Tasks

### View Inventory

**Web UI**: http://localhost:8000

**API**:
```bash
curl http://localhost:8000/api/v1/inventory | jq
```

### Create a VM

> **Note**: Always use strong, unique passwords in production. The example password below is for demonstration only.

```bash
curl -X POST http://localhost:8000/api/v1/vms/create \
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
    "guest_v4_defaultgw": "192.168.1.1"
  }' | jq
```

### Check Job Status

```bash
# Get job ID from create response
JOB_ID="abc-123-def"

curl http://localhost:8000/api/v1/jobs/$JOB_ID | jq
```

### Delete a VM

```bash
curl -X POST http://localhost:8000/api/v1/vms/delete \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-vm-01",
    "hyperv_host": "hyperv01.local",
    "force": true
  }' | jq
```

## 🔍 API Documentation

Visit http://localhost:8000/docs for interactive API documentation!

## 🛠️ Make Commands

```bash
make help     # Show all commands
make dev      # Start dev server
make build    # Build Docker image
make deploy   # Deploy to Kubernetes
```

## 📚 Full Documentation

- **README.md** - Complete usage guide
- **DEPLOYMENT.md** - Kubernetes deployment details
- **TESTING.md** - Comprehensive testing guide
- **Docs/Server-Migration-Guide.md** - Migration from AWX

## 🚨 Troubleshooting

### Can't connect to Hyper-V hosts?

1. Check WinRM is enabled: `Test-WSMan -ComputerName <host>`
2. Verify credentials are correct
3. Check firewall allows port 5985
4. Look at logs for specific errors

### UI shows empty inventory?

1. Check HYPERV_HOSTS is configured
2. Verify hosts are reachable
3. Wait for initial inventory refresh (60 seconds default)
4. Check logs: `kubectl logs deployment/aetherv-orchestrator`

### Authentication errors?

- For development: Set `OIDC_ENABLED=false`
- For production: Verify OIDC configuration
- Use static `API_TOKEN` for automation

## 💬 Get Help

- GitHub Issues: https://github.com/charlespick/HLVMM/issues
- Check logs for detailed errors
- Review TESTING.md for specific scenarios

## 🎉 What's Next?

1. Explore the Web UI
2. Try creating a test VM
3. Check out the API docs
4. Read the full deployment guide
5. Set up OIDC for production

Welcome to Aether-V! 🚀
