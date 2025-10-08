# Quick Start: Managed Deployment Mode

This guide shows you how to quickly get started with HLVMM's managed deployment mode.

## What is Managed Mode?

Managed mode is an intelligent deployment option that:
- ✅ Checks if a VM already exists before creating it
- ✅ Skips provisioning if the VM is already in the cluster
- ✅ Enables self-healing infrastructure (recreates VMs if deleted)
- ✅ Works great with automated workflows (AWX, cron, etc.)

## 5-Minute Setup

### Step 1: Verify Prerequisites

```bash
# Check that your VM will be on a Hyper-V cluster
# Managed mode requires clustered VMs
```

**Requirements:**
- ✅ Hyper-V cluster configured
- ✅ HLVMM installed on hosts
- ✅ CredSSP configured for cluster operations
- ✅ vm_clustered: Yes in your variables

### Step 2: Add Two Variables

Just add these two lines to your existing playbook variables:

```yaml
vm_clustered: Yes          # REQUIRED for managed mode
deployment_type: managed   # NEW: Enable managed mode
```

### Step 3: Run Your Playbook

That's it! Run your playbook as normal:

```bash
ansible-playbook Ansible/Provisioning.yaml \
  -e "hyperv_host=hyperv01.example.com" \
  -e "vm_name=my-webserver" \
  -e "image_name='Ubuntu 22.04 LTS'" \
  -e "gb_ram=8" \
  -e "cpu_cores=4" \
  -e "vm_clustered=Yes" \
  -e "deployment_type=managed" \
  -e "guest_la_uid=admin" \
  -e "guest_la_pw=SecurePass123"
```

### Step 4: See the Magic

**First Run:**
```
TASK [Check if VM exists in cluster] *************************************
ok: VM 'my-webserver' does not exist in cluster. Proceeding with provisioning.

TASK [Copy Image] ********************************************************
changed

TASK [Register VM] *******************************************************
changed

... (VM gets created and provisioned)
```

**Second Run (VM already exists):**
```
TASK [Check if VM exists in cluster] *************************************
ok: VM exists in cluster. Ending playbook early.

PLAY RECAP ***************************************************************
hyperv01.example.com       : ok=3    changed=0    unreachable=0    failed=0
```

**After VM Deletion:**
```
TASK [Check if VM exists in cluster] *************************************
ok: VM 'my-webserver' does not exist in cluster. Proceeding with provisioning.

... (VM gets recreated automatically)
```

## Common Use Cases

### Use Case 1: Self-Healing Infrastructure

Set up a cron job or scheduled task:

```bash
# Run every hour to ensure VMs exist
0 * * * * /usr/bin/ansible-playbook /path/to/Provisioning.yaml -e @/path/to/vm-config.yml
```

If a VM gets deleted, it's automatically recreated on the next run!

### Use Case 2: AWX Workflow Template

Create a job template in AWX:

1. **Job Template Name:** Ensure Web Servers Exist
2. **Playbook:** Ansible/Provisioning.yaml
3. **Schedule:** Every 6 hours
4. **Extra Variables:**
   ```yaml
   deployment_type: managed
   vm_clustered: Yes
   hyperv_host: hyperv01.example.com
   vm_name: web-server-{{ item }}
   # ... other variables
   ```

### Use Case 3: Infrastructure as Code

Store your VM definitions in Git:

```yaml
# vms/production/web-servers.yml
web_vms:
  - name: web-01
    ip: 192.168.1.101
    ram: 8
    cpus: 4
  - name: web-02
    ip: 192.168.1.102
    ram: 8
    cpus: 4
```

Run a playbook that loops through and ensures all VMs exist:

```yaml
- name: Ensure all web servers exist
  include_tasks: provision_vm.yml
  loop: "{{ web_vms }}"
  vars:
    deployment_type: managed
    vm_clustered: Yes
```

## Comparison: Provisioned vs Managed

| Action | Provisioned Mode | Managed Mode |
|--------|------------------|--------------|
| First run | ✅ Creates VM | ✅ Creates VM |
| Second run | ❌ May fail (VM exists) | ✅ Exits early (no changes) |
| After VM deleted | ❌ User must manually rerun | ✅ Automatically recreates |
| Requires clustering | ❌ No | ✅ Yes |
| Idempotent | ❌ No | ✅ Yes |

## Switching from Provisioned to Managed

Already using HLVMM? Switching is easy:

**Before (Provisioned Mode):**
```yaml
vm_name: my-vm
vm_clustered: Yes
# Other variables...
```

**After (Managed Mode):**
```yaml
vm_name: my-vm
vm_clustered: Yes
deployment_type: managed  # <-- Just add this line!
# Other variables...
```

That's it! Your existing playbooks work with this one addition.

## Troubleshooting

### Error: "deployment_type 'managed' is only compatible with vm_clustered: Yes"

**Solution:** Add `vm_clustered: Yes` to your variables.

```yaml
vm_clustered: Yes          # Add this
deployment_type: managed
```

### Error: CredSSP authentication failed

**Solution:** Verify CredSSP is configured:

```powershell
# On Ansible controller
Enable-WSManCredSSP -Role Client -DelegateComputer "*.example.com"

# On Hyper-V host (automatically handled by playbook)
Enable-WSManCredSSP -Role Server
```

### VM not detected after creation

**Check:** Ensure VM was added to cluster:

```powershell
Get-ClusterGroup -Name 'my-vm-name'
```

## Next Steps

- 📖 Read the [complete documentation](../Deployment-Types.md)
- 🧪 Try the [test scenarios](testing-managed-deployment.md)
- 💡 View the [full example](managed-deployment-example.yaml)
- 🔧 Learn about [AWX integration](../Deployment-Types.md#using-deployment-types-with-awxansible-tower)

## Summary

Managed deployment mode makes HLVMM infrastructure management:
- ✅ **Idempotent** - Safe to run multiple times
- ✅ **Self-healing** - Automatically recreates deleted VMs
- ✅ **Automation-friendly** - Perfect for scheduled jobs
- ✅ **Simple** - Just add one variable!

Start using it today! 🚀
