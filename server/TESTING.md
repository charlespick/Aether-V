# Testing Guide for Aether-V Orchestrator

This guide covers various testing scenarios for the Aether-V Orchestrator.

## Quick Start Testing

### Local Testing Without Hyper-V

For development and testing the API/UI without actual Hyper-V hosts:

1. **Create a minimal config**:
```bash
cd server
cat > .env << EOF
DEBUG=true
OIDC_ENABLED=false
HYPERV_HOSTS=
INVENTORY_REFRESH_INTERVAL=300
EOF
```

2. **Run the server**:
```bash
./dev.sh
```

3. **Access the UI**: http://localhost:8000
   - You'll see empty inventory (no hosts configured)
   - UI and health checks should work

4. **Test API endpoints**:
```bash
# Health check
curl http://localhost:8000/healthz

# API documentation
open http://localhost:8000/docs

# Empty inventory
curl http://localhost:8000/api/v1/inventory
```

### Testing with Mock Hosts

You can test the application logic without real Hyper-V by setting up mock WinRM responses (requires additional code not included in MVP).

## Integration Testing with Real Hyper-V

### Prerequisites

1. **Hyper-V Host Setup**:
   - Windows Server with Hyper-V role
   - WinRM enabled
   - PowerShell scripts deployed
   - At least one golden image

2. **Network Access**:
   - Server can reach host on port 5985
   - Firewall rules configured

3. **Credentials**:
   - Domain/local account with Hyper-V admin rights
   - WinRM configured to accept these credentials

### Test Configuration

1. **Create test config**:
```bash
cd server
cat > .env << EOF
DEBUG=true
OIDC_ENABLED=false

# Your test Hyper-V host
HYPERV_HOSTS=hyperv-test.yourdomain.local

# Your credentials
WINRM_USERNAME=DOMAIN\\testuser
WINRM_PASSWORD=YourPassword123
WINRM_TRANSPORT=ntlm
WINRM_PORT=5985

# Quick refresh for testing
INVENTORY_REFRESH_INTERVAL=30
EOF
```

2. **Start the server**:
```bash
./dev.sh
```

3. **Verify connection**:
   - Check logs for "Host hyperv-test.yourdomain.local: X VMs"
   - Access UI at http://localhost:8000
   - Should see host listed as "Connected"
   - Should see existing VMs

### Test Cases

#### Test 1: Inventory Discovery
```bash
# Check hosts
curl http://localhost:8000/api/v1/hosts | jq

# Expected: List of configured hosts with "connected": true

# Check VMs
curl http://localhost:8000/api/v1/vms | jq

# Expected: List of VMs from your hosts
```

#### Test 2: Create a Windows VM
```bash
curl -X POST http://localhost:8000/api/v1/vms/create \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-win-01",
    "image_name": "Windows Server 2022",
    "hyperv_host": "hyperv-test.yourdomain.local",
    "gb_ram": 4,
    "cpu_cores": 2,
    "guest_la_uid": "Administrator",
    "guest_la_pw": "YourSecurePassword123!",
    "guest_v4_ipaddr": "192.168.1.100",
    "guest_v4_cidrprefix": 24,
    "guest_v4_defaultgw": "192.168.1.1",
    "guest_v4_dns1": "192.168.1.10"
  }' | jq

# Save the job_id from the response
JOB_ID="<returned-job-id>"

# Monitor job progress
watch -n 2 "curl -s http://localhost:8000/api/v1/jobs/$JOB_ID | jq '.status, .output'"
```

**Expected Behavior**:
1. Job created with `status: "pending"`
2. Job transitions to `status: "running"`
3. Output shows each step:
   - "Step 1: Copying image..."
   - "Step 2: Copying provisioning ISO..."
   - "Step 3: Registering VM..."
   - "Step 4: Waiting for VM to signal..."
   - "Step 5: Publishing provisioning data..."
4. Job completes with `status: "completed"`
5. VM visible in inventory after refresh

#### Test 3: Create a Linux VM
```bash
curl -X POST http://localhost:8000/api/v1/vms/create \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-ubuntu-01",
    "image_name": "Ubuntu 22.04",
    "hyperv_host": "hyperv-test.yourdomain.local",
    "gb_ram": 2,
    "cpu_cores": 2,
    "guest_la_uid": "ubuntu",
    "guest_la_pw": "ubuntu123",
    "guest_v4_ipaddr": "192.168.1.101",
    "guest_v4_cidrprefix": 24,
    "guest_v4_defaultgw": "192.168.1.1",
    "guest_v4_dns1": "192.168.1.10",
    "cnf_ansible_ssh_user": "ansible",
    "cnf_ansible_ssh_key": "ssh-rsa AAAA..."
  }' | jq
```

**Expected Behavior**:
- Same flow as Windows
- Domain join parameters ignored (Linux)
- SSH config applied via cloud-init

#### Test 4: Delete a VM
```bash
curl -X POST http://localhost:8000/api/v1/vms/delete \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-win-01",
    "hyperv_host": "hyperv-test.yourdomain.local",
    "force": true
  }' | jq

# Monitor deletion
JOB_ID="<returned-job-id>"
watch -n 2 "curl -s http://localhost:8000/api/v1/jobs/$JOB_ID | jq '.status, .output'"
```

**Expected Behavior**:
1. VM stopped (if running)
2. VM removed from Hyper-V
3. VM files deleted
4. VM removed from inventory

#### Test 5: Error Handling

**Test invalid host**:
```bash
curl -X POST http://localhost:8000/api/v1/vms/create \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-vm",
    "image_name": "Windows Server 2022",
    "hyperv_host": "nonexistent-host",
    ...
  }'

# Expected: 404 error "Host not found"
```

**Test duplicate VM**:
```bash
# Create VM twice with same name
# Expected: 409 error "VM already exists"
```

**Test invalid image**:
```bash
# Create VM with non-existent image
# Expected: Job fails with "Failed to copy image"
```

## Performance Testing

### Inventory Refresh Performance

Test inventory refresh time with different numbers of VMs:

```bash
# Time a manual refresh
time curl -X POST http://localhost:8000/api/v1/inventory/refresh

# Check logs for timing
grep "Inventory refresh completed" logs.txt
```

**Benchmarks** (approximate, depends on network):
- 10 VMs: < 2 seconds
- 50 VMs: < 5 seconds  
- 100 VMs: < 10 seconds

### Concurrent Job Execution

Test multiple jobs in parallel:

```bash
# Submit 5 jobs quickly
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/vms/create \
    -H "Content-Type: application/json" \
    -d "{...vm_name: test-vm-$i...}" &
done

# Jobs should queue and execute sequentially
```

**Expected Behavior**:
- Jobs queued immediately
- Executed one at a time (sequential)
- No race conditions

## Kubernetes Testing

### Deploy to Test Cluster

```bash
cd server/k8s

# Create test namespace
kubectl create namespace aetherv-test

# Update kustomization.yaml to use test namespace
sed -i 's/namespace: aetherv/namespace: aetherv-test/' kustomization.yaml

# Edit configmap.yaml and secret.yaml with test values
# ...

# Deploy
kubectl apply -k .

# Watch pod startup
kubectl -n aetherv-test get pods -w

# Check logs
kubectl -n aetherv-test logs -f deployment/aetherv-orchestrator
```

### Test Health Probes

```bash
# Liveness probe (should always succeed)
kubectl -n aetherv-test exec deployment/aetherv-orchestrator -- \
  curl -f http://localhost:8000/healthz

# Readiness probe (succeeds after inventory initialized)
kubectl -n aetherv-test exec deployment/aetherv-orchestrator -- \
  curl -f http://localhost:8000/readyz
```

### Test Pod Restart

```bash
# Delete pod - should restart automatically
kubectl -n aetherv-test delete pod -l app=aetherv-orchestrator

# Watch it restart
kubectl -n aetherv-test get pods -w

# Verify inventory rebuilds
kubectl -n aetherv-test logs -f deployment/aetherv-orchestrator | grep "Inventory refresh"
```

### Test Configuration Changes

```bash
# Update ConfigMap (e.g., change refresh interval)
kubectl -n aetherv-test edit configmap aetherv-config

# Restart pods to pick up changes
kubectl -n aetherv-test rollout restart deployment/aetherv-orchestrator

# Verify new config is active
kubectl -n aetherv-test logs deployment/aetherv-orchestrator | grep INVENTORY_REFRESH_INTERVAL
```

## Authentication Testing

### Test OIDC Authentication

1. **Configure OIDC** in ConfigMap:
```yaml
OIDC_ENABLED: "true"
OIDC_ISSUER_URL: "https://login.microsoftonline.com/<tenant>/v2.0"
OIDC_CLIENT_ID: "<client-id>"
```

2. **Set client secret** in Secret:
```yaml
OIDC_CLIENT_SECRET: "<secret>"
```

3. **Test unauthenticated request**:
```bash
curl http://localhost:8000/api/v1/hosts
# Expected: 401 Unauthorized
```

4. **Get OIDC token** (depends on your provider)

5. **Test authenticated request**:
```bash
TOKEN="<your-oidc-token>"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/hosts
# Expected: 200 OK with host list
```

### Test API Token Authentication

```bash
# Set static token in Secret
API_TOKEN="test-token-12345"

# Test with token
curl -H "Authorization: Bearer test-token-12345" \
  http://localhost:8000/api/v1/hosts
# Expected: 200 OK
```

## UI Testing

### Manual UI Testing Checklist

1. **Dashboard**:
   - [ ] Stats display correctly (hosts, VMs counts)
   - [ ] Hosts table shows all hosts
   - [ ] VMs table shows all VMs
   - [ ] Connection status accurate
   - [ ] Last refresh timestamp updates

2. **Refresh Button**:
   - [ ] Click refresh button
   - [ ] Button shows "Refreshing..." state
   - [ ] Inventory updates after refresh
   - [ ] Button returns to normal state

3. **Auto-refresh**:
   - [ ] Leave UI open for 30+ seconds
   - [ ] Inventory auto-updates
   - [ ] No errors in browser console

4. **Error Handling**:
   - [ ] Disconnect from network
   - [ ] Error message displays
   - [ ] Reconnect
   - [ ] UI recovers

## Troubleshooting Tests

### Test: WinRM Connection Fails

**Simulate**: Configure invalid host or credentials

**Expected**:
- Host shows as "disconnected" in UI
- Error logged: "Failed to refresh host X"
- Other hosts still work
- Service remains healthy

### Test: PowerShell Script Missing

**Simulate**: Remove a script from host

**Expected**:
- Job fails with clear error
- Error message indicates missing script
- Service remains operational
- Other jobs can still run

### Test: Out of Disk Space

**Simulate**: Fill up cluster storage

**Expected**:
- VM creation job fails
- Error: "Not enough free space"
- Service continues running
- Other hosts unaffected

## Automated Testing (Future)

Future test automation plans:

```bash
# Unit tests
pytest tests/unit/

# Integration tests with mock WinRM
pytest tests/integration/

# End-to-end tests (requires test environment)
pytest tests/e2e/

# Load tests
locust -f tests/load/locustfile.py
```

## Test Reporting

### Log Analysis

```bash
# Check for errors
kubectl logs deployment/aetherv-orchestrator | grep ERROR

# Check job completion rate
kubectl logs deployment/aetherv-orchestrator | grep "Job.*completed"

# Check inventory refresh times
kubectl logs deployment/aetherv-orchestrator | grep "Inventory refresh completed"
```

### Metrics (Future)

Once monitoring is implemented:
- Job success rate
- Average job duration
- Inventory refresh time
- API response time
- Error rate by type

## Test Documentation

When reporting test results, include:

1. **Environment**:
   - Number of hosts
   - Number of existing VMs
   - Network topology
   - Kubernetes version

2. **Configuration**:
   - OIDC enabled?
   - Refresh interval
   - WinRM transport type

3. **Test Results**:
   - Pass/fail for each test
   - Execution times
   - Any errors encountered
   - Screenshots of UI

4. **Issues Found**:
   - Description
   - Steps to reproduce
   - Expected vs actual behavior
   - Logs/screenshots

## Next Steps

After completing these tests:

1. Document any issues found
2. Create GitHub issues for bugs
3. Provide feedback on usability
4. Suggest improvements
5. Test with production-like workload

For questions or issues during testing, please open a GitHub issue with the "testing" label.
