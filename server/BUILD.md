# Building the Aether-V Orchestrator Container

## Overview

The Aether-V Orchestrator is built as a multi-stage Docker container that includes:
1. ISO building (Windows and Linux provisioning ISOs)
2. PowerShell scripts for host management
3. Python FastAPI application

## Building Locally

To build the container locally:

```bash
# From the repository root
cd /path/to/HLVMM
docker build -f server/Dockerfile -t aetherv-orchestrator:latest .
```

**Important**: The build context must be the repository root, not the `server` directory, because the Dockerfile needs access to:
- `Windows/` - Windows provisioning files
- `Linux/` - Linux provisioning files
- `Powershell/` - PowerShell scripts to deploy to hosts
- `Scripts/Build-ProvisioningISOs.ps1` - ISO building script
- `version` - Version file

## Multi-Stage Build Process

### Stage 1: ISO Builder
- Base: `mcr.microsoft.com/powershell:lts-ubuntu-22.04`
- Installs `xorriso` and `genisoimage` for ISO creation
- Copies source files (Windows/, Linux/, Scripts/, version)
- Runs `Build-ProvisioningISOs.ps1` to create ISOs
- Output: `WindowsProvisioning.iso` and `LinuxProvisioning.iso`

### Stage 2: Python Dependencies
- Base: `python:3.11-slim`
- Installs Python dependencies from `server/requirements.txt`

### Stage 3: Application
- Copies Python dependencies from Stage 2
- Copies application code from `server/app/`
- Copies built ISOs from Stage 1 to `/app/artifacts/isos/`
- Copies PowerShell scripts to `/app/artifacts/scripts/`
- Copies version file to `/app/artifacts/version`
- Creates non-root user
- Exposes port 8000

## Artifacts in Container

After building, the container contains:

```
/app/
├── app/                          # Python application
├── artifacts/
│   ├── isos/
│   │   ├── WindowsProvisioning.iso
│   │   └── LinuxProvisioning.iso
│   ├── scripts/
│   │   ├── CopyImage.ps1
│   │   ├── CopyProvisioningISO.ps1
│   │   ├── PublishProvisioningData.ps1
│   │   ├── RegisterVM.ps1
│   │   └── WaitForProvisioningKey.ps1
│   └── version                   # Single version file
```

## Automated CI/CD Build

The GitHub Actions workflow `.github/workflows/build-server.yml` automatically builds and publishes the container when:
- Code is pushed to the `server` branch
- Changes are made to relevant paths (server/, Windows/, Linux/, Powershell/, Scripts/, version)
- Workflow is manually triggered

Published images are available at:
```
ghcr.io/charlespick/aetherv-orchestrator:latest
```

## Testing the Build

After building, you can test the container:

```bash
# Run the container
docker run -p 8000:8000 \
  -e OIDC_ENABLED=false \
  -e DEBUG=true \
  aetherv-orchestrator:latest

# Check artifacts are present
docker run --rm aetherv-orchestrator:latest ls -la /app/artifacts/
docker run --rm aetherv-orchestrator:latest ls -la /app/artifacts/isos/
docker run --rm aetherv-orchestrator:latest cat /app/artifacts/version
```

## Troubleshooting

### Build fails with "not found" errors
Ensure you're running the build from the repository root with the correct context:
```bash
docker build -f server/Dockerfile -t aetherv-orchestrator:latest .
```

### ISO building fails
The ISO builder stage requires:
- Valid source files in Windows/ and Linux/ directories
- `Build-ProvisioningISOs.ps1` script
- `xorriso` or `genisoimage` installed

### Python dependency issues
Check that `server/requirements.txt` is accessible and contains valid dependencies.

## Version Management

The container version is read from the `version` file at the repository root. This same version is:
- Embedded in the container at `/app/artifacts/version`
- Used by the service to compare with host versions
- Deployed to hosts during service startup

To update the version:
1. Edit the `version` file at repository root
2. Rebuild the container
3. Deploy the new container - hosts will be automatically updated
