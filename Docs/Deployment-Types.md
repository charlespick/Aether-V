# HLVMM Deployment Types

## Overview

HLVMM supports two deployment types that control how the provisioning playbook handles VM creation:

1. **Provisioned** (default) - Traditional behavior where VMs are created on every playbook run
2. **Managed** - Intelligent deployment that checks for existing VMs before provisioning

## Deployment Type: Provisioned

### Description

The `provisioned` deployment type maintains the original HLVMM behavior. When using this mode, the playbook will attempt to create and provision a VM every time it is executed, regardless of whether a VM with the same name already exists.

### Use Cases

- One-time VM deployments
- Development and testing environments
- Scenarios where you manually manage VM lifecycle
- Non-clustered VM deployments

### Configuration

```yaml
deployment_type: provisioned
```

Or simply omit the variable entirely (provisioned is the default):

```yaml
# deployment_type will default to "provisioned"
```

### Behavior

1. Playbook executes all provisioning steps
2. VM is created and configured
3. No pre-checks are performed
4. Compatible with both clustered and non-clustered deployments

## Deployment Type: Managed

### Description

The `managed` deployment type adds intelligent VM lifecycle management. Before attempting to create a VM, the playbook checks the Hyper-V cluster to see if a VM with the same name already exists. If found, the playbook ends gracefully without making any changes.

This mode is designed for creating "declarative" VM deployments where you can define your desired state and let HLVMM maintain it.

### Use Cases

- Infrastructure-as-Code deployments
- Disaster recovery scenarios where VMs should be automatically recreated if removed
- AWX/Ansible Tower workflows that enforce desired state
- Production environments with automated remediation

### Requirements

**Managed deployments are only compatible with clustered VMs.**

You must specify:
```yaml
deployment_type: managed
vm_clustered: Yes
```

If you attempt to use `deployment_type: managed` without `vm_clustered: Yes`, the playbook will fail with a validation error.

### Configuration

```yaml
deployment_type: managed
vm_clustered: Yes
```

### Behavior

1. **Pre-Check Phase** (managed mode only):
   - Enables CredSSP for cluster communication
   - Queries the Hyper-V cluster for a VM with the specified name
   - If VM exists: Playbook ends gracefully with no changes
   - If VM does not exist: Playbook continues to provisioning

2. **Provisioning Phase** (if VM not found):
   - All standard provisioning steps execute
   - VM is created and configured
   - VM is added to the cluster

### Authentication

Managed mode uses CredSSP authentication to communicate with the Hyper-V cluster, similar to the existing cluster operations for adding VMs. Ensure your Ansible controller is properly configured for CredSSP authentication with the target Hyper-V hosts.

## Using Deployment Types with AWX/Ansible Tower

### Scenario: Self-Healing Infrastructure

You can create an AWX workflow that periodically checks and enforces your desired VM state:

1. Create a job template with `deployment_type: managed`
2. Schedule it to run periodically (e.g., daily)
3. If a VM is accidentally deleted, the next scheduled run will recreate it
4. If the VM already exists, the playbook exits quickly without changes

### Example Playbook Invocation

```bash
ansible-playbook Provisioning.yaml \
  -e "hyperv_host=hyperv01.example.com" \
  -e "vm_name=web-server-01" \
  -e "image_name='Ubuntu 22.04 LTS'" \
  -e "gb_ram=8" \
  -e "cpu_cores=4" \
  -e "vm_clustered=Yes" \
  -e "deployment_type=managed" \
  -e "guest_la_uid=adminuser" \
  -e "guest_la_pw=SecurePassword123"
```

### Example AWX Survey Configuration

Add the following field to your AWX survey:

```
Field Type: Multiple Choice (single select)
Variable: deployment_type
Required: No
Default: provisioned
Choices:
  provisioned
  managed
```

## Comparison Table

| Feature | Provisioned | Managed |
|---------|-------------|---------|
| Default behavior | Yes | No |
| Requires vm_clustered | No | Yes |
| Pre-checks for existing VM | No | Yes |
| CredSSP required | Only for cluster add | For cluster check + add |
| Idempotent | No | Yes |
| Use with automation workflows | Basic | Advanced |

## Implementation Details

### Cluster Check Logic

The managed mode uses the following PowerShell command to check for VM existence:

```powershell
Get-ClusterGroup -Name '<vm_name>' -ErrorAction SilentlyContinue
```

This command:
- Queries the cluster for a cluster group (VM role) with the specified name
- Returns the VM if it exists
- Returns nothing if the VM is not found
- Does not throw errors if the VM doesn't exist (SilentlyContinue)

### CredSSP Configuration

Both the cluster check and cluster add operations use CredSSP authentication:

1. **Enable CredSSP** on the target host temporarily
2. **Execute cluster operations** with `ansible_winrm_transport: credssp`
3. **Disable CredSSP** via handler after completion

This ensures secure delegation of credentials for cluster management operations.

## Troubleshooting

### Error: "deployment_type must be either 'provisioned' or 'managed'"

**Cause:** Invalid value provided for `deployment_type`

**Solution:** Ensure you're using one of the two valid values: `provisioned` or `managed`

### Error: "deployment_type 'managed' is only compatible with vm_clustered: Yes"

**Cause:** Attempting to use managed mode without clustering enabled

**Solution:** Either:
- Change `deployment_type` to `provisioned`, or
- Add `vm_clustered: Yes` to your playbook variables

### Managed deployment keeps recreating VMs

**Cause:** VM name in cluster doesn't match the name specified in the playbook

**Solution:** Ensure the `vm_name` variable exactly matches the cluster group name for the VM

### CredSSP authentication failures

**Cause:** CredSSP not properly configured between Ansible controller and Hyper-V host

**Solution:**
1. Verify CredSSP is enabled on both client and server
2. Check that the Ansible controller can delegate credentials
3. Ensure proper DNS resolution and Kerberos configuration
4. Refer to Ansible WinRM documentation for CredSSP setup

## Migration from Existing Playbooks

Existing playbooks will continue to work without modification. The `deployment_type` variable defaults to `provisioned`, maintaining backward compatibility.

To migrate to managed deployments:

1. Ensure your VMs are clustered (`vm_clustered: Yes`)
2. Add `deployment_type: managed` to your playbook or AWX survey
3. Test the playbook to ensure it detects existing VMs correctly

## Best Practices

### When to Use Provisioned Mode

- Development and testing environments
- One-off VM deployments
- Non-clustered environments
- When you want explicit control over VM recreation

### When to Use Managed Mode

- Production environments
- Infrastructure-as-Code deployments
- Automated workflows with periodic execution
- Disaster recovery scenarios
- When you want declarative VM state management

### Combining with Other Automation

Managed mode works excellently with:

- **AWX/Ansible Tower workflows** - Schedule periodic state enforcement
- **GitOps practices** - Store VM definitions in Git, automatically apply changes
- **Monitoring systems** - Trigger remediation when VMs are detected missing
- **CI/CD pipelines** - Ensure development environments are always available

## Future Enhancements

Potential future additions to deployment types:

- Support for non-clustered managed deployments
- VM state verification (checking VM configuration matches desired state)
- Automatic updates when VM configuration drifts from desired state
- Integration with external CMDB systems for VM inventory
