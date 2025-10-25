[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Get-ChildItem -Path (Join-Path $scriptRoot 'Provisioning.*.ps1') -File |
    Sort-Object Name |
    ForEach-Object { . $_.FullName }

function ConvertTo-Hashtable {
    param([Parameter(Mandatory)] [object]$InputObject)

    if ($InputObject -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $InputObject.Keys) {
            $result[$key] = $InputObject[$key]
        }
        return $result
    }

    if ($InputObject -is [System.Management.Automation.PSObject]) {
        $result = @{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
        return $result
    }

    throw "Expected a mapping object but received type '$($InputObject.GetType().FullName)'."
}

function Test-ProvisioningValuePresent {
    param([object]$Value)

    if ($null -eq $Value) { return $false }
    if ($Value -is [string]) { return -not [string]::IsNullOrWhiteSpace($Value) }
    return $true
}

function Get-ProvisioningOsFamily {
    param([hashtable]$Values)

    if ($Values.ContainsKey('os_family') -and (Test-ProvisioningValuePresent $Values['os_family'])) {
        return ($Values['os_family'].ToString().ToLowerInvariant())
    }

    if (-not (Test-ProvisioningValuePresent $Values['image_name'])) {
        throw "Job definition missing 'image_name'; unable to determine OS family."
    }

    $imageName = $Values['image_name'].ToString().ToLowerInvariant()
    $windowsPrefixes = @('windows', 'microsoft windows')
    foreach ($prefix in $windowsPrefixes) {
        if ($imageName.StartsWith($prefix)) {
            return 'windows'
        }
    }

    $linuxPrefixes = @(
        'ubuntu',
        'rhel',
        'red hat enterprise linux',
        'centos',
        'rocky linux',
        'almalinux',
        'oracle linux',
        'debian',
        'suse',
        'opensuse',
        'fedora'
    )
    foreach ($prefix in $linuxPrefixes) {
        if ($imageName.StartsWith($prefix)) {
            return 'linux'
        }
    }

    throw "Unable to infer operating system family from image '$($Values['image_name'])'. Provide an 'os_family' field or update the detection rules."
}

function Test-AllOrNoneParameterSet {
    param(
        [string]$SetName,
        [string[]]$Members,
        [hashtable]$Values
    )

    $provided = @()
    foreach ($member in $Members) {
        if ($Values.ContainsKey($member) -and (Test-ProvisioningValuePresent $Values[$member])) {
            $provided += $member
        }
    }

    if ($provided.Count -gt 0 -and $provided.Count -ne $Members.Count) {
        $missing = @()
        foreach ($member in $Members) {
            if (-not ($provided -contains $member)) {
                $missing += $member
            }
        }
        throw "Parameter set '$SetName' requires fields: $($missing -join ', ')"
    }
}

function Update-OsSpecificConfiguration {
    param(
        [string]$OsFamily,
        [hashtable]$Values
    )

    if ($OsFamily -eq 'windows') {
        if ((Test-ProvisioningValuePresent $Values['cnf_ansible_ssh_user']) -or (Test-ProvisioningValuePresent $Values['cnf_ansible_ssh_key'])) {
            Write-Warning "Ansible SSH credentials are not supported for Windows systems. Clearing all Ansible SSH variables."
            foreach ($field in @('cnf_ansible_ssh_user', 'cnf_ansible_ssh_key')) {
                $Values[$field] = ''
            }
        }
    }

    if ($OsFamily -eq 'linux') {
        $domainJoinFields = @('guest_domain_joinuid', 'guest_domain_jointarget', 'guest_domain_joinou', 'guest_domain_joinpw')
        $domainDataProvided = $false

        foreach ($field in $domainJoinFields) {
            if (Test-ProvisioningValuePresent $Values[$field]) {
                $domainDataProvided = $true
                break
            }
        }

        if ($domainDataProvided) {
            Write-Warning "Domain join is not supported for Linux systems. Clearing all domain join variables."
            foreach ($field in $domainJoinFields) {
                $Values[$field] = ''
            }
        }
    }
    return $Values
}

function Invoke-ProvisioningClusterEnrollment {
    param([string]$VmName)

    try {
        Import-Module FailoverClusters -ErrorAction Stop | Out-Null
    }
    catch {
        throw "FailoverClusters module is required to add VM '$VmName' to the cluster: $_"
    }

    $existing = Get-ClusterGroup -Name $VmName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "VM '$VmName' is already part of the cluster." -ForegroundColor Yellow
        return
    }

    Write-Host "Adding VM '$VmName' to the Failover Cluster..."
    try {
        Add-ClusterVirtualMachineRole -VMName $VmName -ErrorAction Stop | Out-Null
        Write-Host "VM '$VmName' added to cluster." -ForegroundColor Green
    }
    catch {
        throw "Failed to add VM '$VmName' to the cluster: $_"
    }
}

try {
    $inputText = [Console]::In.ReadToEnd()
    if (-not (Test-ProvisioningValuePresent $inputText)) {
        throw "No job definition provided on standard input."
    }

    if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
        try {
            Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
        }
        catch {
            throw "ConvertFrom-Yaml cmdlet is unavailable. Install PowerShell 7+ or the 'powershell-yaml' module."
        }
    }

    try {
        $jobDefinition = ConvertFrom-Yaml -Yaml $inputText -ErrorAction Stop
    }
    catch {
        throw "Failed to parse job definition YAML: $_"
    }

    if (-not $jobDefinition) {
        throw "Parsed job definition is empty."
    }

    if (-not ($jobDefinition.PSObject.Properties.Name -contains 'fields')) {
        throw "Job definition must contain a 'fields' mapping."
    }

    $values = ConvertTo-Hashtable $jobDefinition.fields

    foreach ($required in @('vm_name', 'image_name', 'gb_ram', 'cpu_cores', 'guest_la_uid', 'guest_la_pw')) {
        if (-not (Test-ProvisioningValuePresent $values[$required])) {
            throw "Job definition missing required field '$required'."
        }
    }

    $vmName = $values['vm_name']
    $osFamily = Get-ProvisioningOsFamily -Values $values
    $values = Update-OsSpecificConfiguration -OsFamily $osFamily -Values $values

    Test-AllOrNoneParameterSet -SetName 'Static IPv4 configuration' -Members @('guest_v4_ipaddr', 'guest_v4_cidrprefix', 'guest_v4_defaultgw', 'guest_v4_dns1', 'guest_v4_dns2') -Values $values
    Test-AllOrNoneParameterSet -SetName 'Windows domain join' -Members @('guest_domain_jointarget', 'guest_domain_joinuid', 'guest_domain_joinpw', 'guest_domain_joinou') -Values $values
    Test-AllOrNoneParameterSet -SetName 'Linux Ansible automation' -Members @('cnf_ansible_ssh_user', 'cnf_ansible_ssh_key') -Values $values

    $gbRam = [int]$values['gb_ram']
    $cpuCores = [int]$values['cpu_cores']
    $vlanId = if (($values.ContainsKey('vlan_id')) -and ($values['vlan_id'] -ne $null)) { [int]$values['vlan_id'] } else { $null }
    $clusterRequested = [bool]$values['vm_clustered']

    $currentHost = $env:COMPUTERNAME
    Write-Host "Starting provisioning workflow for VM '$vmName' on host '$currentHost' (OS: $osFamily)."

    $vmDataFolder = Invoke-ProvisioningCopyImage -VMName $vmName -ImageName $values['image_name']
    Write-Host "Image copied to $vmDataFolder" -ForegroundColor Green

    Invoke-ProvisioningCopyProvisioningIso -OSFamily $osFamily -VMDataFolder $vmDataFolder

    $registerParams = @{
        OSFamily = $osFamily
        GBRam = $gbRam
        CPUcores = $cpuCores
        VMDataFolder = $vmDataFolder
    }
    if ($vlanId -ne $null) {
        $registerParams.VLANId = $vlanId
    }
    Invoke-ProvisioningRegisterVm @registerParams | Out-Null

    Invoke-ProvisioningWaitForProvisioningKey -VMName $vmName | Out-Null

    $env:GuestLaPw = [string]$values['guest_la_pw']
    if (Test-ProvisioningValuePresent $values['guest_domain_joinpw']) {
        $env:GuestDomainJoinPw = [string]$values['guest_domain_joinpw']
    }
    else {
        Remove-Item Env:GuestDomainJoinPw -ErrorAction SilentlyContinue
    }

    $publishParams = @{
        GuestLaUid = [string]$values['guest_la_uid']
        GuestHostName = [string]$vmName
    }

    if (Test-ProvisioningValuePresent $values['guest_v4_ipaddr']) {
        $publishParams.GuestV4IpAddr = [string]$values['guest_v4_ipaddr']
        $publishParams.GuestV4CidrPrefix = [string]$values['guest_v4_cidrprefix']
        $publishParams.GuestV4DefaultGw = [string]$values['guest_v4_defaultgw']
        $publishParams.GuestV4Dns1 = [string]$values['guest_v4_dns1']
        $publishParams.GuestV4Dns2 = [string]$values['guest_v4_dns2']
    }

    if (Test-ProvisioningValuePresent $values['guest_net_dnssuffix']) {
        $publishParams.GuestNetDnsSuffix = [string]$values['guest_net_dnssuffix']
    }

    if (($osFamily -eq 'windows') -and (Test-ProvisioningValuePresent $values['guest_domain_jointarget'])) {
        $publishParams.GuestDomainJoinTarget = [string]$values['guest_domain_jointarget']
        $publishParams.GuestDomainJoinUid = [string]$values['guest_domain_joinuid']
        $publishParams.GuestDomainJoinOU = [string]$values['guest_domain_joinou']
    }

    if (($osFamily -eq 'linux') -and (Test-ProvisioningValuePresent $values['cnf_ansible_ssh_user'])) {
        $publishParams.AnsibleSshUser = [string]$values['cnf_ansible_ssh_user']
        $publishParams.AnsibleSshKey = [string]$values['cnf_ansible_ssh_key']
    }

    Invoke-ProvisioningPublishProvisioningData @publishParams

    if ($clusterRequested) {
        Invoke-ProvisioningClusterEnrollment -VmName $vmName
    }

    Write-Host "Provisioning workflow completed for VM '$vmName'." -ForegroundColor Green
    exit 0
}
catch {
    Write-Error ("Provisioning job failed: " + $_.Exception.Message)
    exit 1
}
finally {
    Remove-Item Env:GuestLaPw -ErrorAction SilentlyContinue
    Remove-Item Env:GuestDomainJoinPw -ErrorAction SilentlyContinue
}
