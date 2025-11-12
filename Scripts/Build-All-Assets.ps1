#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build all assets needed for the server container (ISOs and static web assets).

.DESCRIPTION
    This script builds:
    1. Provisioning ISOs for Windows and Linux
    2. Static web assets (icons and Swagger UI files) from npm packages

.PARAMETER OutputPath
    Directory where ISO files will be created. Defaults to 'ISOs'.

.EXAMPLE
    ./Build-All-Assets.ps1 -OutputPath ISOs
#>

param(
    [Parameter()]
    [string]$OutputPath = "ISOs"
)

$ErrorActionPreference = 'Stop'

# Build ISOs
Write-Host "Building provisioning ISOs..." -ForegroundColor Cyan
& "$PSScriptRoot/Build-ProvisioningISOs.ps1" -OutputPath $OutputPath

# Build static web assets
Write-Host "`nBuilding static web assets..." -ForegroundColor Cyan

$ServerDir = Join-Path $PSScriptRoot ".." "server"
Push-Location $ServerDir

try {
    # Install npm dependencies
    Write-Host "Installing npm packages..." -ForegroundColor Yellow
    npm install --omit=dev

    # Extract icons
    Write-Host "Extracting icons..." -ForegroundColor Yellow
    python3 scripts/extract_icons.py

    # Extract Swagger UI
    Write-Host "Extracting Swagger UI assets..." -ForegroundColor Yellow
    python3 scripts/extract_swagger_ui.py

    Write-Host "`n✓ All assets built successfully" -ForegroundColor Green
}
finally {
    Pop-Location
}
