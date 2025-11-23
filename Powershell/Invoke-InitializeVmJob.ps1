<#
.SYNOPSIS
    Orchestrate guest OS initialization via Hyper-V KVP exchange.

.DESCRIPTION
    This script coordinates the VM guest initialization process:
    1. Waits for the guest to signal readiness for provisioning
    2. Publishes encrypted provisioning data to the guest via KVP
    3. Waits for the guest to complete provisioning
    
    It uses the existing Provisioning.WaitForProvisioningKey.ps1 and
    Provisioning.PublishProvisioningData.ps1 functions for the actual work.

.NOTES
    This script expects JSON input via stdin containing guest configuration fields.
    It sources the required provisioning functions and orchestrates the workflow.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Read JSON input from stdin
$inputJson = @()
while ($null -ne ($line = [Console]::ReadLine())) {
    $inputJson += $line
}

if (-not $inputJson) {
    throw "No JSON input received from stdin"
}

$jsonString = $inputJson -join "`n"

try {
    $config = ConvertFrom-Json -InputObject $jsonString -ErrorAction Stop
}
catch {
    throw "Failed to parse JSON input: $_"
}

# Extract required fields
$vmId = $config.vm_id
$vmName = $config.vm_name

if (-not $vmId) {
    throw "vm_id is required for guest initialization"
}

if (-not $vmName) {
    throw "vm_name is required for guest initialization"
}

Write-Host "=== VM Guest Initialization ==="
Write-Host "VM ID: $vmId"
Write-Host "VM Name: $vmName"

# Get the script directory to locate provisioning functions
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Source the provisioning function scripts
$waitForKeyScript = Join-Path -Path $scriptDir -ChildPath "Provisioning.WaitForProvisioningKey.ps1"
$publishDataScript = Join-Path -Path $scriptDir -ChildPath "Provisioning.PublishProvisioningData.ps1"

if (-not (Test-Path -LiteralPath $waitForKeyScript)) {
    throw "Required script not found: $waitForKeyScript"
}

if (-not (Test-Path -LiteralPath $publishDataScript)) {
    throw "Required script not found: $publishDataScript"
}

Write-Host "Sourcing provisioning functions..."
. $waitForKeyScript
. $publishDataScript

# Step 1: Wait for guest provisioning readiness
Write-Host ""
Write-Host "Step 1: Waiting for guest to signal provisioning readiness..."
try {
    $ready = Invoke-ProvisioningWaitForProvisioningKey -VMName $vmName -TimeoutSeconds 300
    if (-not $ready) {
        throw "Guest did not signal readiness for provisioning"
    }
}
catch {
    Write-Error "Failed to establish provisioning channel: $_"
    throw
}

# Step 2: Publish provisioning data to guest
Write-Host ""
Write-Host "Step 2: Publishing provisioning data to guest..."

# Build parameters for Invoke-ProvisioningPublishProvisioningData
$publishParams = @{
    GuestHostName = $vmName
    GuestLaUid = $config.guest_la_uid
}

# Optional networking configuration
if ($config.guest_v4_ip_addr) { $publishParams['GuestV4IpAddr'] = $config.guest_v4_ip_addr }
if ($config.guest_v4_cidr_prefix) { $publishParams['GuestV4CidrPrefix'] = $config.guest_v4_cidr_prefix }
if ($config.guest_v4_default_gw) { $publishParams['GuestV4DefaultGw'] = $config.guest_v4_default_gw }
if ($config.guest_v4_dns1) { $publishParams['GuestV4Dns1'] = $config.guest_v4_dns1 }
if ($config.guest_v4_dns2) { $publishParams['GuestV4Dns2'] = $config.guest_v4_dns2 }
if ($config.guest_net_dns_suffix) { $publishParams['GuestNetDnsSuffix'] = $config.guest_net_dns_suffix }

# Optional domain join configuration
if ($config.guest_domain_join_target) { $publishParams['GuestDomainJoinTarget'] = $config.guest_domain_join_target }
if ($config.guest_domain_join_uid) { $publishParams['GuestDomainJoinUid'] = $config.guest_domain_join_uid }
if ($config.guest_domain_join_ou) { $publishParams['GuestDomainJoinOU'] = $config.guest_domain_join_ou }

# Optional Ansible SSH configuration
if ($config.cnf_ansible_ssh_user) { $publishParams['AnsibleSshUser'] = $config.cnf_ansible_ssh_user }
if ($config.cnf_ansible_ssh_key) { $publishParams['AnsibleSshKey'] = $config.cnf_ansible_ssh_key }

# Set sensitive data from environment variables (as expected by PublishProvisioningData)
# The server should have already set these environment variables before invoking this script

try {
    Invoke-ProvisioningPublishProvisioningData @publishParams
}
catch {
    Write-Error "Failed to publish provisioning data: $_"
    throw
}

# Step 3: Wait for guest to complete provisioning
Write-Host ""
Write-Host "Step 3: Waiting for guest to complete provisioning..."
try {
    Invoke-ProvisioningWaitForProvisioningCompletion -VMName $vmName -TimeoutSeconds 1800 -PollIntervalSeconds 5
}
catch {
    Write-Error "Guest provisioning did not complete successfully: $_"
    throw
}

Write-Host ""
Write-Host "=== Guest initialization completed successfully ==="
Write-Host "VM '$vmName' is now fully provisioned and ready for use."
