# Aether-V CI/CD Process

## Overview

This document describes the CI/CD process for Aether-V. As of the service migration, ISOs are built at container build time and bundled within the service container, eliminating the need for separate ISO releases and distribution.

## Service-Integrated Architecture

### New Approach (Current)

ISOs and scripts are now managed as part of the service:

- **Container Build**: ISOs are built during container build process
- **Artifact Bundling**: Scripts and ISOs are packaged in the container at `/app/artifacts`
- **Automatic Deployment**: Service deploys artifacts to hosts at startup if version mismatch detected
- **No External Releases**: No need for GitHub releases of ISOs or installation scripts

### Benefits

1. **Simplified Distribution**: Single container image contains everything needed
2. **Version Consistency**: Scripts and ISOs always match the service version
3. **Transparent Updates**: Hosts are automatically updated when service is deployed
4. **Reduced Complexity**: No separate release management for ISOs
5. **No External Dependencies**: Service is self-contained

## Current Workflows

### Server Build Workflow (`build-server.yml`)

Builds and publishes the Aether-V service container:

- **Triggers**: Push to `server` branch
- **Actions**:
  1. Build ISOs during container build
  2. Package scripts and ISOs in container
  3. Build container image
  4. Publish to GitHub Container Registry (GHCR)
- **Output**: `ghcr.io/charlespick/aetherv-orchestrator:latest`

### Version Check Workflow (`version-check.yml`)

Validates version consistency across the repository:

- **Triggers**: Pull requests and pushes
- **Actions**: Ensures version file is properly formatted and consistent

## Deployment Process

### Container Deployment

1. **Pull Container**: Pull latest image from GHCR
   ```bash
   docker pull ghcr.io/charlespick/aetherv-orchestrator:latest
   ```

2. **Deploy to Kubernetes**: Apply Kubernetes manifests
   ```bash
   kubectl apply -k server/k8s/
   ```

3. **Service Startup**: On startup, the service:
   - Reads container version from `/app/artifacts/version`
   - Connects to each configured Hyper-V host
   - Checks host version
   - Deploys scripts and ISOs if version mismatch detected
   - Begins normal operation

### Version Management

- **Single Version Source**: `version` file at repository root
- **Automatic Synchronization**: Hosts automatically updated to match container version
- **Development Mode**: Use `DEVELOPMENT_INSTALL=true` to deploy to separate directory on hosts

## Migration from Legacy System

### What Was Removed

- ❌ `build-and-release.yml` - No longer needed for ISO distribution
- ❌ `nightly-cleanup.yml` - No releases to clean up
- ❌ `InstallHostProvisioningISOs.ps1` - Replaced by service deployment
- ❌ `InstallHostScripts.ps1` - Replaced by service deployment
- ❌ Ansible playbooks - Functionality integrated into service
- ❌ Separate version files for scripts/ISOs - Single version now

### What Remains

- ✅ `build-server.yml` - Builds and publishes service container
- ✅ `version-check.yml` - Validates version consistency
- ✅ `Build-ProvisioningISOs.ps1` - Used during container build

## Benefits of New Approach

1. **Simplified Management**: One version, one deployment
2. **Automatic Updates**: Hosts stay in sync with service
3. **Self-Contained**: No external dependencies
4. **Transparent to Users**: Updates happen automatically
5. **Reduced CI Complexity**: Fewer workflows to maintain