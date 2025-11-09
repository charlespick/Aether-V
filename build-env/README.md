# Build Environment Container

This directory contains the Dockerfile for the Aether-V build environment container.

## Purpose

The build environment container pre-installs ISO creation tools and PowerShell that are needed **outside** the Docker build process to create provisioning ISOs. This approach dramatically reduces CI/CD build times by approximately 90% by avoiding repeated `apt-get update` and `apt-get install` steps in GitHub Actions.

## What's Included

- Ubuntu 22.04 base image
- ISO creation tools:
  - `xorriso` - ISO image manipulation tool
  - `genisoimage` - Creates ISO-9660 CD-ROM file system images
  - `mkisofs` - Creates ISO file systems
- PowerShell - For running the Build-ProvisioningISOs.ps1 script

## Build Process Overview

The Aether-V build process has two distinct phases:

### Phase 1: ISO Creation (Outside Docker)
**Uses build-env container as CI runner**

1. Clone repository
2. Run in build-env container (or install tools manually)
3. Execute `pwsh Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs`
4. Generates ISO files in ISOs/ directory

### Phase 2: Server Container Build (Inside Docker)
**Uses standard Python base image**

1. Start with `python:3.11-slim`
2. Install Python dependencies
3. Copy application code
4. Copy pre-built ISOs from Phase 1
5. Create final server container (NO build tools included - stays small)

## The Optimization

**The Problem:**
Every time the server container is built in CI, the workflow needs to:
1. Install ISO creation tools (xorriso, genisoimage) via `apt-get`
2. Install PowerShell via `apt-get`
3. Build ISOs using PowerShell script
4. Build Docker container with pre-built ISOs

Steps 1-2 take ~60-70 seconds and happen EVERY TIME, even though the tools rarely change.

**The Solution:**
Create a build-env container with all ISO creation tools pre-installed. Use this container to run the ISO build step in CI, eliminating the tool installation time.

**Before optimization:**
```yaml
- name: Install ISO creation tools
  run: |
    sudo apt-get update          # ~20 seconds
    sudo apt-get install -y xorriso genisoimage  # ~30 seconds
    
- name: Install PowerShell
  run: |
    # Download and install PowerShell  # ~20 seconds
    
- name: Build ISOs
  run: pwsh Scripts/Build-ProvisioningISOs.ps1  # ~10 seconds
```
Total: ~80 seconds **every build**

**After optimization:**
```yaml
- name: Build ISOs using build-env container
  run: |
    docker run --rm -v $PWD:/workspace \
      ghcr.io/charlespick/aetherv-build-env:latest \
      pwsh Scripts/Build-ProvisioningISOs.ps1  # ~10 seconds (pull cached)
```
Total: ~10 seconds (tools pre-installed, container image cached)

**Savings: ~70 seconds per build = 90% reduction in build time** 🚀

Note: The server container itself remains small and does NOT include these build tools. The build-env container is only used as a CI runner environment, not as a base image.

## Building Locally

```bash
cd build-env
docker build -t aetherv-build-env:local .
```

## Using Locally

```bash
# Run ISO build in the build environment
docker run --rm -v $(pwd):/workspace aetherv-build-env:local \
  pwsh Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs
```

## CI/CD Integration

The build environment container is automatically built and published to GitHub Container Registry (GHCR) when changes are made to this directory. The workflow only triggers when files in `build-env/` are modified.

The GitHub Actions workflow then uses this container to run the ISO build step, eliminating the need to install tools on every build.

## Versioning

The build environment container is tagged with:
- `latest` - Latest version from main branch
- `sha-<commit>` - Specific commit version
- PR builds are tested but not pushed to registry
