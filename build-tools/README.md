# Build Tools Image

This directory defines a lightweight container image that bundles the utilities
required by the CI pipelines to author provisioning artifacts (for example,
bootable ISO files) without repeatedly installing them on each run.

## Contents

- Base image: [`mcr.microsoft.com/powershell:7.4-ubuntu-22.04`]
- Packages: `xorriso`, `genisoimage`
- Default work directory: `/github/workspace`
- Entrypoint: `pwsh -NoLogo -NoProfile -File`

## Usage

The accompanying GitHub Actions workflow builds and publishes the image to the
GitHub Container Registry at `ghcr.io/<owner>/aetherv-build-tools`. Other
workflows can reference the published image to execute PowerShell scripts that
need the ISO authoring utilities.
