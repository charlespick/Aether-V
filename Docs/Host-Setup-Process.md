# Host Setup and Provisioning Process

This document describes the host setup and provisioning configuration/process that was previously implemented in Ansible playbooks. These processes are now integrated into the Aether-V service.

## Historical Context

Previously, HLVMM used Ansible playbooks to set up Hyper-V hosts and provision VMs. This required:
1. Running Ansible playbooks manually or via AWX
2. Managing scripts and ISOs separately on GitHub releases
3. Version checking and updates via PowerShell installation scripts

The new architecture integrates these processes into the service itself, making deployment transparent to users.

## Host Setup Process (Previously HostSetup.yaml)

The host setup process ensures that Hyper-V hosts have the necessary scripts and ISOs to provision VMs.

### Scripts Installation

**Purpose**: Deploy PowerShell orchestration scripts to Hyper-V hosts

**Target Location**: `C:\Program Files\Home Lab Virtual Machine Manager\` (or `...(Devel)` for development)

**Scripts Deployed**:
- `CopyImage.ps1` - Copies VM image files from template location
- `CopyProvisioningISO.ps1` - Copies the appropriate provisioning ISO to VM folder
- `RegisterVM.ps1` - Registers VM with Hyper-V and applies configuration
- `WaitForProvisioningKey.ps1` - Waits for VM to signal readiness via KVP
- `PublishProvisioningData.ps1` - Publishes provisioning data to VM via Hyper-V KVP

**Version Management**:
- Version file: `scriptsversion` (contained current version of deployed scripts)
- Version source: Root `version` file from repository
- Update logic: Compare versions, only update if repository version is newer

**Installation Steps** (from InstallHostScripts.ps1):
1. Check local `scriptsversion` file (default to 0.0.0 if not exists)
2. Fetch repository version from GitHub raw content
3. Compare versions using semantic versioning
4. If update needed:
   - Fetch PowerShell directory contents via GitHub API
   - Delete all existing .ps1 files in install directory
   - Download each script file from repository
   - Save new version to `scriptsversion` file

### ISOs Installation

**Purpose**: Deploy provisioning ISOs to Hyper-V hosts for VM customization

**Target Location**: Same as scripts (`C:\Program Files\Home Lab Virtual Machine Manager\`)

**ISOs Deployed**:
- `WindowsProvisioning.iso` - Contains Windows provisioning service and modules
- `LinuxProvisioning.iso` - Contains cloud-init compatible Linux provisioning

**Version Management**:
- Version file: `isosversion` (contained current version of deployed ISOs)
- Version source: GitHub releases (latest stable or latest prerelease for development)
- Update logic: Compare versions, only update if release version is newer

**Installation Steps** (from InstallHostProvisioningISOs.ps1):
1. Check local `isosversion` file (default to 0.0.0 if not exists)
2. Query GitHub Releases API for latest release:
   - Stable: `/repos/{owner}/{repo}/releases/latest`
   - Development: Get all releases, find latest prerelease
3. Extract version from release tag name
4. Compare versions using semantic versioning
5. If update needed:
   - Delete all existing .ISO files in install directory
   - Download WindowsProvisioning.iso from release assets
   - Download LinuxProvisioning.iso from release assets
   - Save new version to `isosversion` file

## VM Provisioning Process (Previously Provisioning.yaml)

The provisioning playbook orchestrated the creation of new VMs on Hyper-V hosts.

### Provisioning Flow

#### Pre-Tasks

1. **Determine OS Family**: Parse image name to identify Windows or Linux
   - Windows patterns: `Windows*`, `Microsoft Windows*`
   - Linux patterns: `Ubuntu*`, `RHEL*`, `CentOS*`, `Rocky Linux*`, `AlmaLinux*`, `Oracle Linux*`, `Debian*`, `SUSE*`, `openSUSE*`, `Fedora*`

2. **Credential Management**:
   - Domain join credentials: Can be set via environment variables (`guest_domain_joinuid`, `guest_domain_joinpw`)
   - Linux: Clear domain join variables (not supported)
   - Windows: Clear Ansible SSH variables (not supported)

#### Main Provisioning Tasks

1. **Copy Image** (CopyImage.ps1)
   - Input: VM name, image name
   - Action: Copy template image to new VM location
   - Output: VM data folder path

2. **Copy Provisioning ISO** (CopyProvisioningISO.ps1)
   - Input: OS family (windows/linux), VM data folder
   - Action: Copy appropriate ISO to VM folder
   - Output: ISO attached to VM

3. **Register VM** (RegisterVM.ps1)
   - Input: OS family, RAM (GB), CPU cores, VM data folder, optional VLAN ID
   - Action: Register VM with Hyper-V, configure resources, attach ISO
   - Output: VM ready to start

4. **Wait For Provisioning Start** (WaitForProvisioningKey.ps1)
   - Input: VM name
   - Action: Wait for VM to signal readiness via KVP exchange
   - Output: VM ready to receive provisioning data

5. **Publish Provisioning Data** (PublishProvisioningData.ps1)
   - Input: Multiple parameters for network, credentials, domain join, etc.
   - Action: Encrypt and publish provisioning data via Hyper-V KVP
   - Security: Secrets passed via environment variables (no_log: true)
   - Parameters:
     - Guest hostname
     - Local administrator credentials
     - IPv4 configuration (IP, subnet, gateway, DNS)
     - DNS suffix
     - Domain join credentials (Windows only)
     - Ansible SSH credentials (Linux only)

6. **Cluster Integration** (Optional, Windows only)
   - Condition: `vm_clustered == "Yes"`
   - Action: Add VM to Failover Cluster using CredSSP
   - Security: Enable CredSSP only for cluster operation, disable after

### Configuration Parameters

The provisioning process accepted these parameters:

**Required**:
- `vm_name` - Name of the VM
- `image_name` - Template image to use
- `hyperv_host` - Target Hyper-V host
- `gb_ram` - RAM in gigabytes
- `cpu_cores` - Number of CPU cores
- `guest_la_uid` - Guest local administrator username
- `guest_la_pw` - Guest local administrator password (secret)

**Optional Network**:
- `guest_v4_ipaddr` - Static IPv4 address
- `guest_v4_cidrprefix` - Subnet prefix length
- `guest_v4_defaultgw` - Default gateway
- `guest_v4_dns1` - Primary DNS server
- `guest_v4_dns2` - Secondary DNS server
- `guest_net_dnssuffix` - DNS suffix
- `vlan_id` - VLAN tag

**Optional Windows Domain Join**:
- `guest_domain_jointarget` - Domain FQDN
- `guest_domain_joinuid` - Domain join username
- `guest_domain_joinpw` - Domain join password (secret)
- `guest_domain_joinou` - Target OU for computer object

**Optional Linux Configuration**:
- `cnf_ansible_ssh_user` - Ansible SSH username
- `cnf_ansible_ssh_key` - Ansible SSH public key

**Optional Clustering**:
- `vm_clustered` - "Yes" to add to cluster

## New Service-Integrated Approach

The Aether-V service now handles these processes automatically:

1. **Container Build Time**:
   - ISOs are built during container build
   - Scripts are packaged with the container
   - Single version file for both scripts and ISOs

2. **Service Startup**:
   - Service deploys scripts and ISOs to hosts
   - Version checking ensures hosts have matching versions
   - Automatic updates when container version changes

3. **Benefits**:
   - No manual host setup required
   - Transparent to users
   - Version consistency guaranteed
   - Simplified deployment model
   - No external dependencies on GitHub releases for ISOs

## Version Management in New Architecture

- **Single Version**: One version file for entire system
- **Automatic Sync**: Service ensures hosts match container version
- **Development Mode**: `DEVELOPMENT_INSTALL` environment variable controls behavior
- **No External Downloads**: All artifacts bundled in container
