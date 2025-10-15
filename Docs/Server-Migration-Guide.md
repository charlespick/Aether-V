# Aether-V Server Migration Guide

This document describes the migration from AWX/Ansible-based orchestration to the new Aether-V Orchestrator service.

## Overview

The Aether-V project is transitioning from using AWX/Ansible for VM orchestration to a lightweight, containerized Python service. This migration brings several benefits while maintaining compatibility with the existing provisioning logic.

### Why Migrate?

- **Simpler Architecture**: Single containerized service vs. AWX + Ansible + PostgreSQL
- **Lower Maintenance**: No database schema migrations, no complex dependencies
- **Better Integration**: Native REST API for future Terraform provider
- **Modern UI**: Built-in web interface for inventory management
- **Kubernetes-Native**: Designed from the ground up for K8s deployment
- **Stateless**: No persistent storage requirements, easier scaling and recovery

### What Stays the Same?

- **PowerShell Scripts**: All existing scripts are reused as-is
- **Provisioning Logic**: VM creation/deletion follows the exact same workflow
- **KVP Communication**: Guest provisioning still uses Hyper-V KVP integration
- **Security Model**: Same encryption, same secure data transfer
- **Image Format**: Same VHDX golden images
- **ISO Format**: Same provisioning ISOs (cloud-init for Linux, custom for Windows)

## Architecture Comparison

### Old Architecture (AWX/Ansible)

```
┌─────────────────────────────────────────────────────┐
│ User Interface (AWX Web UI)                         │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ AWX Application Server                               │
│  - Job scheduling                                    │
│  - Credential management                             │
│  - RBAC                                              │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ PostgreSQL Database                                  │
│  - Job history                                       │
│  - Credentials                                       │
│  - Configuration                                     │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ Ansible Engine                                       │
│  - Runs playbooks (Provisioning.yaml, HostSetup)    │
│  - WinRM to Hyper-V hosts                           │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ Hyper-V Hosts                                        │
│  - PowerShell scripts manually deployed              │
│  - ISOs manually deployed via CI/CD                  │
└─────────────────────────────────────────────────────┘
```

### New Architecture (Aether-V Orchestrator)

```
┌─────────────────────────────────────────────────────┐
│ User Interface (Built-in Web UI) + REST API          │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ Aether-V Orchestrator (Single Container)             │
│  - FastAPI web server                                │
│  - OIDC authentication                               │
│  - In-memory inventory                               │
│  - Job queue and executor                            │
│  - WinRM client                                      │
│  - Auto host discovery                               │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ Kubernetes (Configuration & Secrets)                 │
│  - ConfigMaps for settings                           │
│  - Secrets for credentials                           │
│  - No persistent storage needed                      │
└─────────────────────────────────────────────────────┘
                        │
┌─────────────────────────────────────────────────────┐
│ Hyper-V Hosts                                        │
│  - PowerShell scripts (same as before)               │
│  - ISOs (same as before)                             │
└─────────────────────────────────────────────────────┘
```

## Migration Path

### Phase 1: Current State (Main Branch)
- AWX/Ansible-based orchestration
- Manual host setup via Ansible playbooks
- Manual ISO deployment via CI/CD
- Job execution via AWX web UI or API

**Status**: ✅ Available on `main` branch

### Phase 2: Server Development (Server Branch)
- Build new orchestrator service
- Implement API and web UI
- Mirror existing Ansible playbook logic
- Test with existing hosts

**Status**: 🚧 In progress on `server` branch

### Phase 3: Beta Testing
- Deploy orchestrator alongside existing AWX
- Test VM creation/deletion workflows
- Verify inventory accuracy
- Collect user feedback

**Status**: 📅 Upcoming

### Phase 4: Production Migration
- Switch primary orchestration to new service
- Deprecate AWX deployment
- Document migration process
- Provide rollback plan

**Status**: 📅 Future

### Phase 5: Enhanced Features
- Terraform provider
- Advanced scheduling
- ISO building at runtime
- Script auto-deployment
- Enhanced logging and audit

**Status**: 📅 Future

## Feature Parity Matrix

| Feature | AWX/Ansible | Aether-V | Notes |
|---------|-------------|----------|-------|
| VM Creation | ✅ | ✅ | Same logic, same parameters |
| VM Deletion | ✅ | ✅ | Same cleanup process |
| Inventory Management | ✅ | ✅ | Auto-refresh vs. dynamic inventory |
| Authentication | ✅ (LDAP/OIDC) | ✅ (OIDC) | Simpler config |
| RBAC | ✅ | 🚧 | Role claim in OIDC token |
| Job History | ✅ (Persistent) | ⚠️ (In-memory) | Future: optional persistence |
| Scheduled Jobs | ✅ | ❌ | Use external scheduler (K8s CronJob) |
| Multi-tenancy | ✅ | ❌ | Not currently needed |
| Custom Workflows | ✅ | ❌ | API provides building blocks |
| Notifications | ✅ | ❌ | Use external monitoring |
| Host Provisioning | Manual Playbook | 🚧 | Future: auto at runtime |
| ISO Management | CI/CD | 🚧 | Future: build at runtime |
| API | Limited | ✅ | Full REST API |
| Web UI | ✅ | ✅ | Simpler, focused on VMs |
| Terraform Integration | ❌ | 🚧 | Future provider |

Legend:
- ✅ Available
- 🚧 In development
- ⚠️ Different implementation
- ❌ Not planned

## API Comparison

### AWX API Example (Old)

```bash
# Launch a job template
curl -X POST https://awx.example.com/api/v2/job_templates/123/launch/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "extra_vars": {
      "vm_name": "test-vm",
      "hyperv_host": "hyperv01",
      "image_name": "Windows Server 2022",
      "gb_ram": 4,
      "cpu_cores": 2
    }
  }'
```

### Aether-V API (New)

```bash
# Create a VM
curl -X POST https://aetherv.example.com/api/v1/vms/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "vm_name": "test-vm",
    "hyperv_host": "hyperv01",
    "image_name": "Windows Server 2022",
    "gb_ram": 4,
    "cpu_cores": 2,
    "guest_la_uid": "Administrator",
    "guest_la_pw": "P@ssw0rd"
  }'
```

**Benefits of new API:**
- More direct, less abstraction
- Built-in OpenAPI documentation
- Simpler authentication
- Faster response (no database queries)

## Deployment Comparison

### AWX Deployment (Old)

```bash
# Complex multi-container setup
kubectl apply -f awx-operator.yaml
kubectl apply -f awx-instance.yaml
kubectl apply -f postgres-pvc.yaml

# Wait for database initialization
# Configure AWX via web UI
# Create inventory, credentials, job templates
# Assign permissions
```

### Aether-V Deployment (New)

```bash
# Simple single-deployment setup
kubectl apply -k server/k8s/

# Service is immediately ready
# Auto-discovers hosts
# No manual configuration needed
```

## Configuration Migration

### AWX Configuration

- Stored in PostgreSQL database
- Configured via web UI or API
- Requires database backups
- Complex to version control

### Aether-V Configuration

- Stored in Kubernetes ConfigMaps and Secrets
- Declarative YAML manifests
- Easy to version control with GitOps
- Simple to backup and restore

Example migration:

**AWX Inventory** → **Aether-V ConfigMap**
```yaml
# In k8s/configmap.yaml
HYPERV_HOSTS: "hyperv01.local,hyperv02.local,hyperv03.local"
```

**AWX Credentials** → **Aether-V Secret**
```yaml
# In k8s/secret.yaml
WINRM_USERNAME: "DOMAIN\\svc-hyperv"
WINRM_PASSWORD: "secure-password"
```

## Testing Strategy

### Pre-Migration Testing

1. **Deploy Orchestrator** in test namespace
2. **Configure** with subset of hosts
3. **Test VM Creation** with each OS type
4. **Verify** provisioning completes correctly
5. **Test VM Deletion** and cleanup
6. **Check** inventory accuracy
7. **Test** API endpoints
8. **Review** job logs

### Parallel Running

During beta testing:
- AWX remains primary orchestration
- Aether-V runs alongside for testing
- Compare results between systems
- Identify and fix discrepancies

### Migration Validation

After migration:
- Monitor job success rates
- Compare with historical AWX metrics
- Verify all hosts are discovered
- Check all VMs are visible
- Test failover and recovery

## Rollback Plan

If issues are discovered post-migration:

1. **Immediate Rollback**: Switch back to AWX
   - AWX infrastructure remains in place during beta
   - Redirect users to AWX UI
   - Update DNS/Ingress as needed

2. **Data Preservation**:
   - No data loss (state is in Hyper-V hosts)
   - Job history may be lost (in-memory)
   - Configuration preserved in git

3. **Fix and Retry**:
   - Fix issues in Aether-V
   - Deploy updated version
   - Re-test thoroughly
   - Migrate again when ready

## Timeline

- **Q1 2024**: Server development (current)
- **Q2 2024**: Beta testing with select users
- **Q3 2024**: Production migration
- **Q4 2024**: AWX decommission
- **2025+**: Enhanced features (Terraform, etc.)

## Support During Migration

### Documentation
- Comprehensive deployment guide in `server/DEPLOYMENT.md`
- API documentation at `/docs` endpoint
- Examples in `server/README.md`

### Getting Help
- GitHub Issues for bug reports
- Discussions for questions
- Migration assistance available

### Feedback
We welcome feedback during the beta testing phase:
- Feature requests
- Bug reports
- UX improvements
- Performance observations

## Conclusion

The migration to Aether-V Orchestrator represents a significant architectural improvement while maintaining full compatibility with existing provisioning logic. The transition will be gradual, with ample testing and validation at each stage.

The new system is designed to be simpler to deploy, easier to maintain, and more extensible for future enhancements like the planned Terraform provider integration.

For technical details, see:
- `server/README.md` - Usage and API documentation
- `server/DEPLOYMENT.md` - Kubernetes deployment guide  
- `Docs/Service-architecture.md` - Detailed architecture document
- `Docs/Aether-V-roadmap.md` - Project roadmap
