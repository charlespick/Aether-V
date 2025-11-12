# Build Tools Image

This directory defines a container image that bundles the utilities required by
the CI pipelines to author provisioning artifacts (for example, bootable ISO
files) without repeatedly installing them on each run.

## Contents

- Base image: [`ubuntu:22.04`]
- Packages: `powershell`, `nodejs` (20.x), `git`, Docker CLI (`docker-ce-cli`,
  `docker-buildx-plugin`, `docker-compose-plugin`), `curl`, `xorriso`,
  `genisoimage`
- Default work directory: `/github/workspace`
- Entrypoint: `pwsh -NoLogo -NoProfile -File`

## Usage

The accompanying GitHub Actions workflow builds and publishes the image to the
GitHub Container Registry at `ghcr.io/<owner>/aetherv-build-tools`. Other
workflows can reference the published image to execute PowerShell scripts that
need the ISO authoring utilities alongside the tooling required by the build
pipeline.
