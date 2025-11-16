[CmdletBinding()]
param(
    [Parameter(ValueFromPipeline = $true)]
    [AllowNull()]
    [object]$InputObject
)

begin {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    $script:CollectedInput = New-Object System.Collections.Generic.List[object]
}

process {
    if ($PSBoundParameters.ContainsKey('InputObject')) {
        $null = $script:CollectedInput.Add($InputObject)
    }
}

end {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    Get-ChildItem -Path (Join-Path $scriptRoot 'Provisioning.*.ps1') -File |
    Sort-Object Name |
    ForEach-Object { . $_.FullName }

    function ConvertTo-Hashtable {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [object]$InputObject
        )

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
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object]$Value
        )

        if ($null -eq $Value) {
            return $false
        }

        if ($Value -is [string]) {
            return -not [string]::IsNullOrWhiteSpace($Value)
        }

        if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
            foreach ($item in $Value) {
                return $true
            }
            return $false
        }

        return $true
    }

    function Read-ProvisioningJobDefinition {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null

        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $stringified = @()
            foreach ($item in $PipelinedInput) {
                if ($null -eq $item) {
                    continue
                }

                if ($item -is [string]) {
                    $stringified += [string]$item
                    continue
                }

                if ($item -is [System.Collections.IDictionary]) {
                    $stringified += ($item | ConvertTo-Json -Depth 16 -Compress)
                    continue
                }

                if ($item -is [System.Management.Automation.PSObject]) {
                    $stringified += (($item | ConvertTo-Json -Depth 16 -Compress))
                    continue
                }

                $stringified += [string]$item
            }

            if ($stringified.Count -gt 0) {
                $rawInput = [string]::Join([Environment]::NewLine, $stringified)
            }
        }

        if (-not (Test-ProvisioningValuePresent -Value $rawInput)) {
            $rawInput = [Console]::In.ReadToEnd()
        }

        if (-not (Test-ProvisioningValuePresent -Value $rawInput)) {
            throw "No job definition supplied via pipeline or standard input."
        }

        $parsed = $null
        $parseErrors = @()

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            $parseErrors += "JSON: $($_.Exception.Message)"
        }

        if (-not $parsed) {
            if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
                try {
                    Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
                }
                catch {
                    throw "Failed to parse job definition. JSON parse error: $($parseErrors -join '; '). YAML parser unavailable."
                }
            }

            try {
                $parsed = ConvertFrom-Yaml -Yaml $rawInput -ErrorAction Stop
            }
            catch {
                $parseErrors += "YAML: $($_.Exception.Message)"
            }
        }

        if (-not $parsed) {
            throw "Unable to parse job definition. Parse errors: $($parseErrors -join '; ')"
        }

        return $parsed
    }

    function Get-ProvisioningOsFamily {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [hashtable]$Values
        )

        if ($Values.ContainsKey('os_family') -and (Test-ProvisioningValuePresent -Value $Values['os_family'])) {
            return $Values['os_family'].ToString().ToLowerInvariant()
        }

        if (-not (Test-ProvisioningValuePresent -Value $Values['image_name'])) {
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

    function Assert-ProvisioningParameterSet {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [string]$Name,

            [Parameter(Mandatory = $true)]
            [string[]]$Members,

            [Parameter(Mandatory = $true)]
            [hashtable]$Values
        )

        $providedMembers = @()
        foreach ($member in $Members) {
            if ($Values.ContainsKey($member) -and (Test-ProvisioningValuePresent -Value $Values[$member])) {
                $providedMembers += $member
            }
        }

        if ($providedMembers -and $providedMembers.Count -gt 0 -and $providedMembers.Count -ne $Members.Count) {
            $missing = @()
            foreach ($member in $Members) {
                if (-not ($providedMembers -contains $member)) {
                    $missing += $member
                }
            }

            throw "Parameter set '$Name' requires fields: $($missing -join ', ')"
        }
    }

    function Apply-OsSpecificAdjustments {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [string]$OsFamily,

            [Parameter(Mandatory = $true)]
            [hashtable]$Values
        )

        if ($OsFamily -eq 'windows') {
            $sshFields = @('cnf_ansible_ssh_user', 'cnf_ansible_ssh_key')
            $sshSupplied = $false
            foreach ($field in $sshFields) {
                if ($Values.ContainsKey($field) -and (Test-ProvisioningValuePresent -Value $Values[$field])) {
                    $sshSupplied = $true
                    break
                }
            }

            if ($sshSupplied) {
                Write-Warning "Ansible SSH credentials are not supported for Windows systems. These values will be ignored."
            }

            foreach ($field in $sshFields) {
                if ($Values.ContainsKey($field)) {
                    $Values.Remove($field)
                }
            }
        }

        if ($OsFamily -eq 'linux') {
            $domainFields = @('guest_domain_joinuid', 'guest_domain_joinpw', 'guest_domain_jointarget', 'guest_domain_joinou')
            $domainSupplied = $false
            foreach ($field in $domainFields) {
                if ($Values.ContainsKey($field) -and (Test-ProvisioningValuePresent -Value $Values[$field])) {
                    $domainSupplied = $true
                    break
                }
            }

            if ($domainSupplied) {
                Write-Warning "Domain join is not supported for Linux systems. Domain join parameters will be ignored."
            }

            foreach ($field in $domainFields) {
                if ($Values.ContainsKey($field)) {
                    $Values.Remove($field)
                }
            }
        }
    }

    function Get-ProvisioningFieldReport {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [string[]]$KnownFields,

            [Parameter(Mandatory = $true)]
            [hashtable]$Values
        )

        $present = @()
        $omitted = @()

        foreach ($field in $KnownFields | Sort-Object) {
            if ($Values.ContainsKey($field) -and (Test-ProvisioningValuePresent -Value $Values[$field])) {
                $present += $field
            }
            else {
                $omitted += $field
            }
        }

        return [pscustomobject]@{
            Present = $present
            Omitted = $omitted
        }
    }

    function New-ProvisioningPublishParameters {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [hashtable]$Values,

            [Parameter(Mandatory = $true)]
            [string]$OsFamily
        )

        $params = @{
            GuestLaUid    = [string]$Values['guest_la_uid']
            GuestHostName = [string]$Values['vm_name']
        }

        if ($Values.ContainsKey('guest_v4_ipaddr') -and (Test-ProvisioningValuePresent -Value $Values['guest_v4_ipaddr'])) {
            $params.GuestV4IpAddr = [string]$Values['guest_v4_ipaddr']
            $params.GuestV4CidrPrefix = [string]$Values['guest_v4_cidrprefix']
            $params.GuestV4DefaultGw = [string]$Values['guest_v4_defaultgw']
            if ($Values.ContainsKey('guest_v4_dns1') -and (Test-ProvisioningValuePresent -Value $Values['guest_v4_dns1'])) {
                $params.GuestV4Dns1 = [string]$Values['guest_v4_dns1']
            }
            if ($Values.ContainsKey('guest_v4_dns2') -and (Test-ProvisioningValuePresent -Value $Values['guest_v4_dns2'])) {
                $params.GuestV4Dns2 = [string]$Values['guest_v4_dns2']
            }
        }

        if ($Values.ContainsKey('guest_net_dnssuffix') -and (Test-ProvisioningValuePresent -Value $Values['guest_net_dnssuffix'])) {
            $params.GuestNetDnsSuffix = [string]$Values['guest_net_dnssuffix']
        }

        if ($OsFamily -eq 'windows' -and $Values.ContainsKey('guest_domain_jointarget') -and (Test-ProvisioningValuePresent -Value $Values['guest_domain_jointarget'])) {
            $params.GuestDomainJoinTarget = [string]$Values['guest_domain_jointarget']
            $params.GuestDomainJoinUid = [string]$Values['guest_domain_joinuid']
            if ($Values.ContainsKey('guest_domain_joinou') -and (Test-ProvisioningValuePresent -Value $Values['guest_domain_joinou'])) {
                $params.GuestDomainJoinOU = [string]$Values['guest_domain_joinou']
            }
        }

        if ($OsFamily -eq 'linux' -and $Values.ContainsKey('cnf_ansible_ssh_user') -and (Test-ProvisioningValuePresent -Value $Values['cnf_ansible_ssh_user'])) {
            $params.AnsibleSshUser = [string]$Values['cnf_ansible_ssh_user']
            if ($Values.ContainsKey('cnf_ansible_ssh_key') -and (Test-ProvisioningValuePresent -Value $Values['cnf_ansible_ssh_key'])) {
                $params.AnsibleSshKey = [string]$Values['cnf_ansible_ssh_key']
            }
        }

        return $params
    }

    function Assert-StaticIpDependencies {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [hashtable]$Values
        )

        $coreFields = @('guest_v4_ipaddr', 'guest_v4_cidrprefix', 'guest_v4_defaultgw')
        $coreProvided = @()
        foreach ($field in $coreFields) {
            if ($Values.ContainsKey($field) -and (Test-ProvisioningValuePresent -Value $Values[$field])) {
                $coreProvided += $field
            }
        }

        if ($coreProvided -and $coreProvided.Count -gt 0 -and $coreProvided.Count -ne $coreFields.Count) {
            throw "Static IPv4 configuration requires fields: $($coreFields -join ', ')"
        }

        if ($Values.ContainsKey('guest_v4_dns2') -and (Test-ProvisioningValuePresent -Value $Values['guest_v4_dns2'])) {
            if (-not ($Values.ContainsKey('guest_v4_dns1') -and (Test-ProvisioningValuePresent -Value $Values['guest_v4_dns1']))) {
                throw "Guest_v4_dns2 provided without guest_v4_dns1. Provide a primary DNS server when specifying a secondary DNS server."
            }
        }
    }

    function Get-HostResourcesConfiguration {
        [CmdletBinding()]
        param()

        $configPath = "C:\ProgramData\Aether-V\hostresources.json"
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            # Try YAML as fallback
            $configPath = "C:\ProgramData\Aether-V\hostresources.yaml"
            if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
                throw "Host resources configuration file not found at C:\ProgramData\Aether-V\hostresources.json or .yaml"
            }
        }

        $rawContent = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop
        
        if ($configPath.EndsWith('.json')) {
            $config = $rawContent | ConvertFrom-Json -ErrorAction Stop
        }
        elseif ($configPath.EndsWith('.yaml') -or $configPath.EndsWith('.yml')) {
            if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
                Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
            }
            $config = ConvertFrom-Yaml -Yaml $rawContent -ErrorAction Stop
        }
        else {
            throw "Unsupported configuration file format: $configPath"
        }

        return ConvertTo-Hashtable -InputObject $config
    }

    function Resolve-NetworkConfiguration {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [hashtable]$HostConfig,

            [Parameter()]
            [AllowNull()]
            [string]$NetworkName
        )

        if ([string]::IsNullOrWhiteSpace($NetworkName)) {
            return $null
        }

        $networks = $HostConfig['networks']
        if (-not $networks -or $networks.Count -eq 0) {
            throw "No networks defined in host configuration"
        }

        foreach ($network in $networks) {
            $netHashtable = ConvertTo-Hashtable -InputObject $network
            if ($netHashtable['name'] -eq $NetworkName) {
                return $netHashtable
            }
        }

        $availableNetworks = ($networks | ForEach-Object { 
            $n = ConvertTo-Hashtable -InputObject $_
            $n['name']
        }) -join ', '
        throw "Network '$NetworkName' not found in host configuration. Available networks: $availableNetworks"
    }

    function Resolve-StorageClassPath {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [hashtable]$HostConfig,

            [Parameter()]
            [AllowNull()]
            [string]$StorageClassName
        )

        if ([string]::IsNullOrWhiteSpace($StorageClassName)) {
            # Return first storage class if no specific one requested
            $storageClasses = $HostConfig['storage_classes']
            if ($storageClasses -and $storageClasses.Count -gt 0) {
                $firstClass = ConvertTo-Hashtable -InputObject $storageClasses[0]
                return $firstClass['path']
            }
            throw "No storage classes defined in host configuration"
        }

        $storageClasses = $HostConfig['storage_classes']
        if (-not $storageClasses -or $storageClasses.Count -eq 0) {
            throw "No storage classes defined in host configuration"
        }

        foreach ($storageClass in $storageClasses) {
            $scHashtable = ConvertTo-Hashtable -InputObject $storageClass
            if ($scHashtable['name'] -eq $StorageClassName) {
                return $scHashtable['path']
            }
        }

        $availableClasses = ($storageClasses | ForEach-Object { 
            $sc = ConvertTo-Hashtable -InputObject $_
            $sc['name']
        }) -join ', '
        throw "Storage class '$StorageClassName' not found in host configuration. Available classes: $availableClasses"
    }

    function Invoke-ProvisioningClusterEnrollment {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [string]$VmName
        )

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

    function Invoke-ProvisioningWorkflow {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelineValues
        )

        $jobDefinition = Read-ProvisioningJobDefinition -PipelinedInput $PipelineValues

        $schemaMetadata = $jobDefinition.schema
        if (-not $schemaMetadata) {
            throw "Job definition missing 'schema' metadata."
        }

        $schemaId = $schemaMetadata.id
        $schemaVersion = $schemaMetadata.version
        $rawFields = $jobDefinition.fields

        if (-not (Test-ProvisioningValuePresent -Value $schemaId)) {
            throw "Job definition missing schema identifier."
        }

        if (-not (Test-ProvisioningValuePresent -Value $schemaVersion)) {
            throw "Job definition missing schema version."
        }

        if (-not $rawFields) {
            throw "Job definition missing 'fields' mapping."
        }

        $values = ConvertTo-Hashtable $rawFields

        $knownFields = @(
            'vm_name',
            'image_name',
            'gb_ram',
            'cpu_cores',
            'guest_la_uid',
            'guest_la_pw',
            'os_family',
            'guest_v4_ipaddr',
            'guest_v4_cidrprefix',
            'guest_v4_defaultgw',
            'guest_v4_dns1',
            'guest_v4_dns2',
            'guest_net_dnssuffix',
            'guest_domain_jointarget',
            'guest_domain_joinuid',
            'guest_domain_joinou',
            'guest_domain_joinpw',
            'cnf_ansible_ssh_user',
            'cnf_ansible_ssh_key',
            'network',
            'storage_class',
            'vm_path',
            'storage_path',
            'vm_clustered'
        )

        foreach ($required in @('vm_name', 'image_name', 'gb_ram', 'cpu_cores', 'guest_la_uid', 'guest_la_pw')) {
            if (-not ($values.ContainsKey($required) -and (Test-ProvisioningValuePresent -Value $values[$required]))) {
                throw "Job definition missing required field '$required'."
            }
        }

        $osFamily = Get-ProvisioningOsFamily -Values $values
        Apply-OsSpecificAdjustments -OsFamily $osFamily -Values $values

        Assert-StaticIpDependencies -Values $values
        Assert-ProvisioningParameterSet -Name 'Windows domain join' -Members @('guest_domain_jointarget', 'guest_domain_joinuid', 'guest_domain_joinpw') -Values $values
        Assert-ProvisioningParameterSet -Name 'Linux Ansible automation' -Members @('cnf_ansible_ssh_user', 'cnf_ansible_ssh_key') -Values $values

        $values['gb_ram'] = [int]$values['gb_ram']
        $values['cpu_cores'] = [int]$values['cpu_cores']

        $vmClustered = $false
        if ($values.ContainsKey('vm_clustered')) {
            $vmClustered = [bool]$values['vm_clustered']
        }

        # Load host resources configuration
        $hostConfig = Get-HostResourcesConfiguration

        # Resolve network configuration if network name provided
        $networkConfig = $null
        if ($values.ContainsKey('network') -and (Test-ProvisioningValuePresent -Value $values['network'])) {
            $networkConfig = Resolve-NetworkConfiguration -HostConfig $hostConfig -NetworkName ([string]$values['network'])
        }

        # Resolve storage path
        $storagePath = $null
        if ($values.ContainsKey('storage_path') -and (Test-ProvisioningValuePresent -Value $values['storage_path'])) {
            $storagePath = [string]$values['storage_path']
        }
        elseif ($values.ContainsKey('storage_class') -and (Test-ProvisioningValuePresent -Value $values['storage_class'])) {
            $storagePath = Resolve-StorageClassPath -HostConfig $hostConfig -StorageClassName ([string]$values['storage_class'])
        }
        else {
            $storagePath = Resolve-StorageClassPath -HostConfig $hostConfig -StorageClassName $null
        }

        # Resolve VM path
        $vmBasePath = $null
        if ($values.ContainsKey('vm_path') -and (Test-ProvisioningValuePresent -Value $values['vm_path'])) {
            $vmBasePath = [string]$values['vm_path']
        }
        else {
            $vmBasePath = $hostConfig['virtual_machines_path']
            if ([string]::IsNullOrWhiteSpace($vmBasePath)) {
                throw "No virtual_machines_path defined in host configuration and no vm_path provided"
            }
        }

        $fieldReport = Get-ProvisioningFieldReport -KnownFields $knownFields -Values $values
        if ($fieldReport.Present.Count -gt 0) {
            Write-Host "Provisioning payload fields provided: $($fieldReport.Present -join ', ')"
        }
        if ($fieldReport.Omitted.Count -gt 0) {
            Write-Host "Provisioning payload fields omitted: $($fieldReport.Omitted -join ', ')"
        }

        $vmName = [string]$values['vm_name']
        $imageName = [string]$values['image_name']
        $gbRam = [int]$values['gb_ram']
        $cpuCores = [int]$values['cpu_cores']

        $currentHost = $env:COMPUTERNAME
        Write-Host "Starting provisioning workflow for VM '$vmName' on host '$currentHost' (OS: $osFamily)."

        $copyResult = Invoke-ProvisioningCopyImage -VMName $vmName -ImageName $imageName -StoragePath $storagePath -VMBasePath $vmBasePath
        $vmDataFolder = $copyResult.VMConfigPath
        $vhdxPath = $copyResult.VhdxPath
        Write-Host "Image copied to $vhdxPath" -ForegroundColor Green
        Write-Host "VM config directory: $vmDataFolder" -ForegroundColor Green

        Invoke-ProvisioningCopyProvisioningIso -OSFamily $osFamily -VMDataFolder $vmDataFolder

        $registerParams = @{
            OSFamily     = $osFamily
            GBRam        = $gbRam
            CPUcores     = $cpuCores
            VMDataFolder = $vmDataFolder
            VhdxPath     = $vhdxPath
        }

        if ($null -ne $networkConfig) {
            $config = ConvertTo-Hashtable -InputObject $networkConfig['configuration']
            $registerParams.VirtualSwitch = $config['virtual_switch']
            if ($config.ContainsKey('vlan_id') -and $null -ne $config['vlan_id']) {
                $registerParams.VLANId = [int]$config['vlan_id']
            }
        }

        Invoke-ProvisioningRegisterVm @registerParams | Out-Null
        Invoke-ProvisioningWaitForProvisioningKey -VMName $vmName | Out-Null

        $env:GuestLaPw = [string]$values['guest_la_pw']
        if ($values.ContainsKey('guest_domain_joinpw') -and (Test-ProvisioningValuePresent -Value $values['guest_domain_joinpw'])) {
            $env:GuestDomainJoinPw = [string]$values['guest_domain_joinpw']
        }
        else {
            Remove-Item Env:GuestDomainJoinPw -ErrorAction SilentlyContinue
        }

        $publishParams = New-ProvisioningPublishParameters -Values $values -OsFamily $osFamily
        Invoke-ProvisioningPublishProvisioningData @publishParams

        Invoke-ProvisioningWaitForProvisioningCompletion -VMName $vmName | Out-Null

        if ($vmClustered) {
            Invoke-ProvisioningClusterEnrollment -VmName $vmName
        }

        Write-Host "Provisioning workflow completed for VM '$vmName'." -ForegroundColor Green
    }

    try {
        # Validate provisioning system version before starting workflow
        $versionPath = Join-Path -Path $PSScriptRoot -ChildPath "version"
        if (-not (Test-Path -LiteralPath $versionPath)) {
            throw "FATAL: Version file not found at '$versionPath'. Cannot continue provisioning without version verification."
        }
        
        $scriptsVersion = (Get-Content -LiteralPath $versionPath -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($scriptsVersion)) {
            throw "FATAL: Version file is empty at '$versionPath'. Cannot continue provisioning."
        }
        
        Write-Host "Provisioning system version: $scriptsVersion"
        
        # Store the version globally for use by other functions
        $global:ProvisioningScriptsVersion = $scriptsVersion

        $pipelineValues = @()
        if ($script:CollectedInput) {
            $pipelineValues = $script:CollectedInput.ToArray()
        }

        Invoke-ProvisioningWorkflow -PipelineValues $pipelineValues
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
}
