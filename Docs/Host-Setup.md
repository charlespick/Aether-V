# Host Setup Process

This document describes how the Aether-V service deploys and manages scripts and ISOs on Hyper-V hosts.

## Overview

The Aether-V service automatically deploys PowerShell scripts and provisioning ISOs to Hyper-V hosts at service startup. This eliminates the need for manual host setup and ensures version consistency across all hosts.

## Installation Directory Configuration

The `HOST_INSTALL_DIRECTORY` environment variable controls where scripts and ISOs are deployed on Hyper-V hosts.

Hosts download those artifacts from the HTTP endpoint defined by `AGENT_DOWNLOAD_BASE_URL`. This value must point to the public
URL (including scheme and the `/agent` mount path) that Hyper-V hosts can reach.

**Default Location:**
```
C:\Program Files\Home Lab Virtual Machine Manager
```

### Use Cases for Custom Installation Directories

#### Testing and Development

Use separate directories to run multiple versions of the service against the same hosts without conflicts:

```bash
# Production deployment
HOST_INSTALL_DIRECTORY=C:\Program Files\Home Lab Virtual Machine Manager

# Development deployment
HOST_INSTALL_DIRECTORY=C:\Program Files\Home Lab Virtual Machine Manager (Devel)

# Testing deployment
HOST_INSTALL_DIRECTORY=C:\Program Files\Home Lab Virtual Machine Manager (Test)
```

Each service instance will:
- Deploy its artifacts to its own directory
- Manage its own version tracking
- Operate independently without interfering with other instances

#### Custom Paths

You can use any valid Windows path:

```bash
# Custom location outside Program Files
HOST_INSTALL_DIRECTORY=C:\CustomPath\HLVMM

# Network location (ensure service has access)
HOST_INSTALL_DIRECTORY=\\FileServer\Share\HLVMM
```

**Note:** Ensure the WinRM user has write permissions to the target directory.

## Deployment Process

### Automatic Deployment on Service Startup

When the service starts, it:

1. **Reads Container Version**: Loads version from `/app/agent/version` in the container
2. **Connects to Hosts**: Establishes WinRM connections to all configured Hyper-V hosts
3. **Checks Host Versions**: For each host, reads `{HOST_INSTALL_DIRECTORY}\version`
4. **Deploys if Needed**: If version mismatch detected:
   - Creates installation directory if it doesn't exist
   - Deploys all PowerShell scripts
   - Deploys Windows and Linux provisioning ISOs
   - Writes version file

### Deployed Artifacts

The service deploys the following to `{HOST_INSTALL_DIRECTORY}` on each host:

**PowerShell Scripts:**
- `Invoke-ProvisioningJob.ps1` - Master orchestrator that reads JSON job definitions and invokes the helper scripts
- `Provisioning.CopyImage.ps1` - Copies VM image files from template location
- `Provisioning.CopyProvisioningISO.ps1` - Copies the appropriate provisioning ISO to VM folder
- `Provisioning.RegisterVM.ps1` - Registers VM with Hyper-V and applies configuration
- `Provisioning.WaitForProvisioningKey.ps1` - Waits for VM to signal readiness via KVP
- `Provisioning.PublishProvisioningData.ps1` - Publishes provisioning data to VM via Hyper-V KVP

**ISOs:**
- `WindowsProvisioning.iso` - Windows provisioning service and modules
- `LinuxProvisioning.iso` - Cloud-init compatible Linux provisioning

**Version Tracking:**
- `version` - Version file matching container version

### Version Management

The service uses a single version file for all components:

- **Container Version**: Embedded at build time from repository root `version` file
- **Host Version**: Stored in `{HOST_INSTALL_DIRECTORY}\version` on each host
- **Comparison**: Service compares versions using semantic versioning (major.minor.build)
- **Updates**: Automatic when container version is newer than host version

### File Transfer Mechanism

Files are downloaded directly over HTTP from the orchestrator's built-in web server:

1. Service enumerates artifacts under `/app/agent`
2. Builds download URLs from `AGENT_DOWNLOAD_BASE_URL`
3. Executes `Invoke-WebRequest` on the host to fetch each file into `{HOST_INSTALL_DIRECTORY}`

This approach keeps host deployments lightweight, avoids large WinRM payloads, and automatically includes new scripts or ISOs
added to the agent directory at build time.

## Historical Context: Legacy Installation Process

### Previous Manual Installation (Now Deprecated)

Before service integration, host setup required manual execution of installation scripts:

**Scripts Installation** (via `InstallHostScripts.ps1`):
- Checked local `scriptsversion` file
- Fetched latest version from GitHub
- Downloaded scripts via GitHub API
- Saved to `C:\Program Files\Home Lab Virtual Machine Manager\`
- Updated `scriptsversion` file

**ISOs Installation** (via `InstallHostProvisioningISOs.ps1`):
- Checked local `isosversion` file  
- Queried GitHub Releases API (stable or prerelease)
- Downloaded ISOs from release assets
- Saved to `C:\Program Files\Home Lab Virtual Machine Manager\`
- Updated `isosversion` file

### Migration to Service-Integrated Approach

**What Changed:**
- ❌ Manual script execution → ✅ Automatic on service startup
- ❌ Two version files per host → ✅ Single version file
- ❌ External GitHub dependencies → ✅ Self-contained in container
- ❌ Branch-based dev mode → ✅ Flexible directory configuration

**Benefits:**
- No manual host setup required
- Transparent to users
- Version consistency guaranteed
- Simplified deployment model
- Support for multiple parallel installations
- No external dependencies

## Troubleshooting

### Directory Creation Fails

**Symptom:** Service logs show directory creation errors

**Solutions:**
- Verify WinRM user has write permissions to parent directory
- Check Windows path length limits (260 characters)
- Ensure path doesn't contain invalid characters

### Version Mismatch Persists

**Symptom:** Service continuously redeploys artifacts

**Solutions:**
- Check version file exists: `Test-Path "{HOST_INSTALL_DIRECTORY}\version"`
- Verify version file content matches container
- Ensure WinRM user can write to installation directory

### HTTP 503 Responses During Startup

**Symptom:** Hyper-V hosts receive `503 Service Temporarily Unavailable` when downloading agent artifacts.

**Explanation:** Kubernetes ingress only forwards traffic to pods that report ready through `/readyz`. During startup the orchestrator now returns an HTTP 200 response with status values such as `deploying_agents` or `initializing` while background deployment and inventory refresh complete. Older container builds returned HTTP 503 during this window, which caused ingress to serve a 503 page to hosts attempting to download scripts.

**Solutions:**
- Ensure you are running a container version that reports the transitional readiness statuses described above.
- If 503 responses persist, verify ingress routing for the agent download path and confirm the orchestrator pod is healthy.
- The orchestrator automatically retries failed artifact downloads up to `AGENT_DOWNLOAD_MAX_ATTEMPTS` times with a pause of `AGENT_DOWNLOAD_RETRY_INTERVAL` seconds between attempts, so transient ingress warm-up delays are handled automatically.

### Files Not Accessible to VMs

**Symptom:** VM provisioning fails to find scripts/ISOs

**Solutions:**
- Verify installation directory path in service configuration
- Ensure `Provisioning.CopyProvisioningISO.ps1` uses correct paths
- Check PowerShell scripts reference `HOST_INSTALL_DIRECTORY` correctly

## Testing Configuration

To test your `HOST_INSTALL_DIRECTORY` configuration:

```powershell
# On the Hyper-V host, verify directory and contents
$installDir = "C:\Program Files\Home Lab Virtual Machine Manager (Test)"
Test-Path $installDir
Get-ChildItem $installDir

# Check version
Get-Content "$installDir\version"

# Verify scripts are executable
Test-Path "$installDir\Invoke-ProvisioningJob.ps1"
Test-Path "$installDir\Provisioning.CopyImage.ps1"
```

## Configuration Examples

### Development Environment

For a development environment running in parallel with production:

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: aetherv-dev-config
data:
  HOST_INSTALL_DIRECTORY: "C:\\Program Files\\Home Lab Virtual Machine Manager (Devel)"
  HYPERV_HOSTS: "hyperv01.dev.local,hyperv02.dev.local"
```

### Multiple Test Environments

For running multiple test environments:

```bash
# Test Environment 1
HOST_INSTALL_DIRECTORY=C:\Program Files\Home Lab Virtual Machine Manager (Test1)

# Test Environment 2  
HOST_INSTALL_DIRECTORY=C:\Program Files\Home Lab Virtual Machine Manager (Test2)
```

Each environment maintains its own:
- Artifact versions
- Deployment state
- Configuration isolation
