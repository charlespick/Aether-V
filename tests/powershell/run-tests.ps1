#!/usr/bin/env pwsh
# PowerShell test runner using Pester
# Runs all PowerShell tests with coverage reporting

param(
    [switch]$CI,
    [switch]$Coverage,
    [string]$TestPath = "tests/powershell"
)

Write-Host "🧪 Aether-V PowerShell Test Suite" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Check if Pester is installed
$pesterModule = Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge '5.0.0' }
if (-not $pesterModule) {
    Write-Host "❌ Pester 5.x not found. Installing..." -ForegroundColor Yellow
    Install-Module -Name Pester -MinimumVersion 5.0.0 -Force -Scope CurrentUser -SkipPublisherCheck
    Write-Host ""
}

# Import Pester
Import-Module Pester -MinimumVersion 5.0.0

# Configure Pester
$config = New-PesterConfiguration

$config.Run.Path = $TestPath
$config.Run.Exit = $true
$config.Output.Verbosity = 'Detailed'

if ($Coverage) {
    Write-Host "📊 Coverage reporting enabled" -ForegroundColor Green
    $config.CodeCoverage.Enabled = $true
    $config.CodeCoverage.OutputPath = 'coverage-ps.xml'
    $config.CodeCoverage.OutputFormat = 'JaCoCo'
    
    # Add paths to track coverage for
    $config.CodeCoverage.Path = @(
        'Powershell/*.ps1',
        'Windows/*.ps1'
    )
}

if ($CI) {
    Write-Host "🔧 CI mode enabled - adjusting settings" -ForegroundColor Yellow
    $config.Output.Verbosity = 'Normal'
    $config.Run.Exit = $true
}

Write-Host ""
Write-Host "Running PowerShell tests..." -ForegroundColor Cyan
Write-Host ""

# Run tests
$result = Invoke-Pester -Configuration $config

# Report results
Write-Host ""
if ($result.Failed -eq 0) {
    Write-Host "✅ All PowerShell tests passed!" -ForegroundColor Green
    if ($Coverage) {
        Write-Host ""
        Write-Host "📊 Coverage report generated: coverage-ps.xml" -ForegroundColor Green
    }
    exit 0
} else {
    Write-Host "❌ Some PowerShell tests failed" -ForegroundColor Red
    exit 1
}
