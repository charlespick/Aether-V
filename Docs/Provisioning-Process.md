# VM Provisioning Process

This document describes the VM provisioning process, both the historical Ansible-based approach and the current service-integrated orchestration.

## Overview

VM provisioning is the process of creating and configuring a new virtual machine on a Hyper-V host. This includes copying the image, attaching provisioning media, configuring the VM, and publishing configuration data via Hyper-V's KVP (Key-Value Pair) integration.

## Current Service-Integrated Provisioning

The Aether-V service orchestrates VM provisioning through its job execution system, maintaining compatibility with the original Ansible playbook workflow.

### Provisioning Flow

Provisioning requests are serialized into YAML and streamed to the host-side orchestration script `Invoke-ProvisioningJob.ps1`. The master script reads the job definition from standard input, validates parameter-set requirements, and then invokes the individual provisioning helpers that live beside it (`Provisioning.CopyImage.ps1`, `Provisioning.CopyProvisioningISO.ps1`, `Provisioning.RegisterVM.ps1`, `Provisioning.WaitForProvisioningKey.ps1`, and `Provisioning.PublishProvisioningData.ps1`). Optional clustering is performed from within the same master script after guest configuration data has been published.

The service executes these steps when provisioning a new VM:

#### 1. Pre-Provisioning

- **OS Family Detection**: Determines whether the image is Windows or Linux based on image name patterns
  - Windows: `Windows*`, `Microsoft Windows*`
  - Linux: `Ubuntu*`, `RHEL*`, `CentOS*`, `Rocky Linux*`, `AlmaLinux*`, `Oracle Linux*`, `Debian*`, `SUSE*`, `openSUSE*`, `Fedora*`

- **Credential Validation**: 
  - For Linux VMs: Clear domain join parameters (not supported)
  - For Windows VMs: Clear SSH configuration (not applicable)

#### 2. Image Preparation (Provisioning.CopyImage.ps1)

Executed via WinRM on the target Hyper-V host:

```powershell
Provisioning.CopyImage.ps1 -VMName "vm-name" -ImageName "image-template"
```

**Actions:**
- Locates golden image in cluster storage
- Creates new VM data folder
- Copies VHDX to VM folder
- Returns VM data folder path for subsequent steps

#### 3. Provisioning ISO Attachment (Provisioning.CopyProvisioningISO.ps1)

```powershell
Provisioning.CopyProvisioningISO.ps1 -OSFamily "windows|linux" -VMDataFolder "path"
```

**Actions:**
- Determines correct ISO (Windows or Linux provisioning)
- Copies ISO from `{HOST_INSTALL_DIRECTORY}` to VM folder
- ISO will be attached when VM is registered

#### 4. VM Registration (Provisioning.RegisterVM.ps1)

```powershell
Provisioning.RegisterVM.ps1 -OSFamily "windows|linux" -GBRam 4 -CPUcores 2 `
               -VMDataFolder "path" [-VLANId 10]
```

**Actions:**
- Registers VM with Hyper-V
- Configures memory and CPU allocation
- Attaches VHDX and provisioning ISO
- Applies VLAN configuration if specified
- Starts the VM

#### 5. Provisioning Readiness (Provisioning.WaitForProvisioningKey.ps1)

```powershell
Provisioning.WaitForProvisioningKey.ps1 -VMName "vm-name"
```

**Actions:**
- Monitors Hyper-V KVP exchange
- Waits for VM to write "ProvisioningReady" key
- Signals that guest is ready to receive configuration

#### 6. Configuration Publishing (Provisioning.PublishProvisioningData.ps1)

```powershell
Provisioning.PublishProvisioningData.ps1 -GuestHostName "vm-name" `
    -GuestLaUid "Administrator" `
    -GuestV4IpAddr "192.168.1.100" `
    -GuestV4CidrPrefix 24 `
    -GuestV4DefaultGw "192.168.1.1" `
    # ... additional parameters
```

**Environment Variables (for secrets):**
- `GuestLaPw` - Local administrator password
- `GuestDomainJoinPw` - Domain join password (Windows only)

**Actions:**
- Encrypts sensitive data
- Publishes configuration to VM via Hyper-V KVP
- VM guest reads and applies configuration
- Guest completes provisioning autonomously

#### 7. Cluster Integration (Optional)

If clustering is requested:

```powershell
Add-ClusterVirtualMachineRole -VMName "vm-name"
```

**Requirements:**
- Failover Clustering feature installed
- VM registered on cluster-capable host

### Configuration Parameters

#### Required Parameters

- `vm_name` - Name of the VM
- `image_name` - Template image to use
- `gb_ram` - RAM in gigabytes
- `cpu_cores` - Number of CPU cores
- `guest_la_uid` - Guest local administrator username
- `guest_la_pw` - Guest local administrator password (secret)

> **Host selection:** The destination Hyper-V host is chosen separately when submitting a job (UI dropdown or API `target_host` property) and is no longer part of the schema-defined field list.

#### Optional Network Configuration

- `guest_v4_ipaddr` - Static IPv4 address
- `guest_v4_cidrprefix` - Subnet prefix length (e.g., 24 for /24)
- `guest_v4_defaultgw` - Default gateway
- `guest_v4_dns1` - Primary DNS server
- `guest_v4_dns2` - Secondary DNS server
- `guest_net_dnssuffix` - DNS suffix/search domain
- `vlan_id` - VLAN tag (0 for untagged)

#### Optional Windows Domain Join

- `guest_domain_jointarget` - Domain FQDN (e.g., example.com)
- `guest_domain_joinuid` - Domain join account username
- `guest_domain_joinpw` - Domain join account password (secret)
- `guest_domain_joinou` - Target OU for computer object (e.g., OU=Servers,DC=example,DC=com)

#### Optional Linux Configuration

- `cnf_ansible_ssh_user` - Ansible SSH username for post-provisioning management
- `cnf_ansible_ssh_key` - Ansible SSH public key

#### Optional Clustering

- `vm_clustered` - Set to "Yes" to add VM to Failover Cluster

### Security Considerations

**Credential Handling:**
- Passwords passed via environment variables (not command line)
- Guest credentials encrypted with VM-specific key via KVP
- Credentials not exposed in process listings or logs
- Service logs configured with `no_log` for sensitive operations

**KVP Security:**
- Data encrypted using Hyper-V integration services
- Only accessible from within guest VM
- Keys deleted after guest retrieves configuration
- No persistence on host after provisioning completes

## Historical: Ansible-Based Provisioning

### Original Provisioning.yaml Playbook

The original implementation used Ansible to orchestrate provisioning:

```yaml
---
- name: Provision VM
  hosts: "{{ target_host }}"
  gather_facts: no
  vars:
    develop: false
    install_directory: "{{ 'Home Lab Virtual Machine Manager (Devel)' 
                           if develop else 'Home Lab Virtual Machine Manager' }}"
```

**Key Characteristics:**
- Ansible playbook executed from AWX or command line
- Direct WinRM commands to Hyper-V host
- Sequential task execution with error handling
- Support for both stable and development mode via `develop` flag

### Workflow Differences

| Aspect | Ansible Playbook | Service-Integrated |
|--------|-----------------|-------------------|
| **Execution** | External Ansible/AWX | Internal job service |
| **State** | Playbook run state | In-memory job tracking |
| **Parallelism** | Ansible parallelism | Async Python workers |
| **Host Selection** | Ansible inventory | Service configuration |
| **Error Handling** | Playbook retry logic | Service job retry |
| **Logging** | Ansible logs | Service API logs |
| **Installation Dir** | `develop` boolean | `HOST_INSTALL_DIRECTORY` config |

### Migration Path

The service maintains **exact orchestration parity** with the original Ansible playbook:

1. Same PowerShell scripts executed in same order
2. Same parameters passed to each script
3. Same error conditions handled
4. Same KVP-based guest communication

**Enhancements:**
- More flexible installation directory configuration
- Better integration with modern orchestration (Kubernetes)
- API-first design for automation (Terraform, etc.)
- Simplified deployment without external Ansible dependencies

## Provisioning Best Practices

### Golden Image Preparation

**Windows Images:**
- Run `sysprep` with generalize option
- Install Hyper-V integration services
- Consider AVMA (Automatic VM Activation) for licensing
- Include any common software/updates in golden image

**Linux Images:**
- Install `cloud-init` configured for NoCloud datasource
- Install Hyper-V KVP daemons (hv_kvp_daemon)
- Ensure KVP services start automatically
- Test KVP communication before creating golden image

### Network Configuration

**Static IP Assignment:**
- Ensure IP addresses don't conflict with DHCP ranges
- Verify gateway and DNS are reachable from VLAN
- Consider DNS registration after provisioning completes

**VLAN Configuration:**
- Confirm VLAN exists on physical switches
- Verify Hyper-V virtual switch supports VLAN tagging
- Test connectivity after provisioning

### Domain Join Considerations

**Windows Domain Join:**
- Use service account with computer object creation rights
- Specify target OU if computer objects need specific GPOs
- Ensure DNS resolution works for domain controllers
- Consider pre-creating computer objects for tighter control

**Troubleshooting Domain Join:**
- Check domain join account permissions
- Verify network connectivity from VM to domain controllers
- Ensure DNS can resolve domain name
- Review VM guest logs for specific join errors

## Monitoring and Validation

### Successful Provisioning Indicators

1. **VM State**: VM running and responding to ping
2. **KVP Exchange**: Provisioning keys present in KVP data
3. **Network**: Correct IP configuration applied
4. **Domain**: Computer object present in AD (if domain-joined)
5. **Services**: Guest services running as expected

### Common Issues

**VM Fails to Start:**
- Check Hyper-V event logs on host
- Verify VHDX file integrity
- Ensure sufficient host resources (RAM, CPU)

**Provisioning Timeout:**
- Verify provisioning ISO attached correctly
- Check guest OS can read ISO (integration services)
- Review guest logs for provisioning service errors

**Network Configuration Not Applied:**
- Confirm static IP parameters correct
- Verify guest networking service running
- Check for IP conflicts on network

**Domain Join Fails:**
- Validate domain join credentials
- Ensure DNS resolution working
- Check domain controller accessibility
- Review domain join account permissions

## API Integration

### Creating a VM via REST API

```bash
curl -X POST "https://aetherv.example.com/api/v1/jobs/provision" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": 1,
    "target_host": "hyperv01.local",
    "values": {
      "vm_name": "web-server-01",
      "image_name": "Windows Server 2022",
      "gb_ram": 8,
      "cpu_cores": 4,
      "guest_la_uid": "Administrator",
      "guest_la_pw": "SecurePassword123!",
      "guest_v4_ipaddr": "192.168.1.100",
      "guest_v4_cidrprefix": 24,
      "guest_v4_defaultgw": "192.168.1.1",
      "guest_v4_dns1": "192.168.1.10",
      "guest_domain_jointarget": "example.com",
      "guest_domain_joinuid": "svc-domainjoin",
      "guest_domain_joinpw": "DomainPassword123!",
      "vlan_id": 10
    }
  }'
```

### Checking Job Status

```bash
curl "https://aetherv.example.com/api/v1/jobs/{job_id}" \
  -H "Authorization: Bearer <token>"
```

## Future Enhancements

- Terraform provider for declarative VM management
- Enhanced job history with persistent storage
- Rollback capability for failed provisions
- Template-based provisioning with parameter validation
- Integration with infrastructure-as-code workflows
