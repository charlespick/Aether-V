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
param(
    [Parameter(ValueFromPipeline = $true)]
    [string]$InputJson
)

$ErrorActionPreference = 'Stop'

# Handle pipeline input - collect all input if coming from pipeline
if (-not $InputJson) {
    # Read from stdin if not provided via pipeline
    $inputLines = @()
    while ($null -ne ($line = [Console]::ReadLine())) {
        $inputLines += $line
    }
    
    if ($inputLines.Count -eq 0) {
        throw "No JSON input received"
    }
    
    $InputJson = $inputLines -join "`n"
}

try {
    $config = ConvertFrom-Json -InputObject $InputJson -ErrorAction Stop
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
$copyIsoScript = Join-Path -Path $scriptDir -ChildPath "Provisioning.CopyProvisioningISO.ps1"

if (-not (Test-Path -LiteralPath $waitForKeyScript)) {
    throw "Required script not found: $waitForKeyScript"
}

if (-not (Test-Path -LiteralPath $publishDataScript)) {
    throw "Required script not found: $publishDataScript"
}

if (-not (Test-Path -LiteralPath $copyIsoScript)) {
    throw "Required script not found: $copyIsoScript"
}

Write-Host "Sourcing provisioning functions..."
. $waitForKeyScript
. $publishDataScript
. $copyIsoScript

# Step 1: Copy and mount provisioning ISO
Write-Host ""
Write-Host "Step 1: Preparing provisioning ISO..."

# Get VM object to determine storage location and OS family
$vm = Get-VM -Id $vmId -ErrorAction Stop
if (-not $vm) {
    throw "VM with ID '$vmId' not found"
}

# Get the VM's configuration path to determine storage location
$vmConfigPath = $vm.ConfigurationLocation
if ([string]::IsNullOrWhiteSpace($vmConfigPath)) {
    throw "Unable to determine VM configuration location for VM '$($vm.Name)'"
}

# Use the VM's parent folder for ISO storage
$vmFolder = Split-Path -Parent $vmConfigPath
$storagePath = $vmFolder

# Determine OS family - default to Windows
$osFamily = 'windows'

# Copy provisioning ISO to VM's storage location
Write-Host "Copying provisioning ISO for $osFamily guest..."
try {
    $isoPath = Invoke-ProvisioningCopyProvisioningIso -OSFamily $osFamily -StoragePath $storagePath -VMName $vmName
    Write-Host "Provisioning ISO copied to: $isoPath"
}
catch {
    Write-Error "Failed to copy provisioning ISO: $_"
    throw
}

# Mount the provisioning ISO
Write-Host "Mounting provisioning ISO to VM..."
try {
    Add-VMDvdDrive -VM $vm -Path $isoPath -ErrorAction Stop
    Write-Host "Provisioning ISO mounted successfully"
}
catch {
    Write-Error "Failed to mount provisioning ISO: $_"
    throw
}

# Step 2: Start the VM
Write-Host ""
Write-Host "Step 2: Starting VM..."
try {
    Start-VM -VM $vm -ErrorAction Stop
    Write-Host "VM started successfully"
}
catch {
    Write-Error "Failed to start VM: $_"
    throw
}

# Step 3: Wait for guest provisioning readiness
Write-Host ""
Write-Host "Step 3: Waiting for guest to signal provisioning readiness..."
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

# Step 4: Publish provisioning data to guest
Write-Host ""
Write-Host "Step 4: Publishing provisioning data to guest..."

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

# Step 5: Wait for guest to complete provisioning
Write-Host ""
Write-Host "Step 5: Waiting for guest to complete provisioning..."
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
