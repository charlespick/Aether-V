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

    # Source common provisioning functions
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

        if ($null -eq $InputObject) {
            return $null
        }

        if ($InputObject -is [System.Collections.IDictionary]) {
            $result = @{}
            foreach ($key in $InputObject.Keys) {
                $value = $InputObject[$key]
                if ($value -is [System.Management.Automation.PSObject] -or $value -is [System.Collections.IDictionary]) {
                    $result[$key] = ConvertTo-Hashtable -InputObject $value
                }
                elseif ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
                    $result[$key] = @($value | ForEach-Object { 
                        if ($_ -is [System.Management.Automation.PSObject] -or $_ -is [System.Collections.IDictionary]) {
                            ConvertTo-Hashtable -InputObject $_
                        }
                        else {
                            $_
                        }
                    })
                }
                else {
                    $result[$key] = $value
                }
            }
            return $result
        }

        if ($InputObject -is [System.Management.Automation.PSObject]) {
            $result = @{}
            foreach ($property in $InputObject.PSObject.Properties) {
                $value = $property.Value
                if ($value -is [System.Management.Automation.PSObject] -or $value -is [System.Collections.IDictionary]) {
                    $result[$property.Name] = ConvertTo-Hashtable -InputObject $value
                }
                elseif ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
                    $result[$property.Name] = @($value | ForEach-Object { 
                        if ($_ -is [System.Management.Automation.PSObject] -or $_ -is [System.Collections.IDictionary]) {
                            ConvertTo-Hashtable -InputObject $_
                        }
                        else {
                            $_
                        }
                    })
                }
                else {
                    $result[$property.Name] = $value
                }
            }
            return $result
        }

        throw "Expected a mapping object but received type '$($InputObject.GetType().FullName)'."
    }

    function Read-JobDefinition {
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

                if ($item -is [System.Collections.IDictionary] -or $item -is [System.Management.Automation.PSObject]) {
                    $stringified += ($item | ConvertTo-Json -Depth 16 -Compress)
                    continue
                }

                $stringified += [string]$item
            }

            if ($stringified.Count -gt 0) {
                $rawInput = [string]::Join([Environment]::NewLine, $stringified)
            }
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            $rawInput = [Console]::In.ReadToEnd()
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            throw "No job definition supplied via pipeline or standard input."
        }

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Failed to parse job definition as JSON: $($_.Exception.Message)"
        }

        return ConvertTo-Hashtable -InputObject $parsed
    }

    function Invoke-CreateVmWorkflow {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelineValues
        )

        $jobDefinition = Read-JobDefinition -PipelinedInput $PipelineValues

        $schemaMetadata = $jobDefinition.schema
        if (-not $schemaMetadata) {
            throw "Job definition missing 'schema' metadata."
        }

        $schemaId = $schemaMetadata.id
        $schemaVersion = $schemaMetadata.version
        $rawFields = $jobDefinition.fields

        if (-not $schemaId) {
            throw "Job definition missing schema identifier."
        }

        if (-not $schemaVersion) {
            throw "Job definition missing schema version."
        }

        if (-not $rawFields) {
            throw "Job definition missing 'fields' mapping."
        }

        $values = ConvertTo-Hashtable $rawFields

        # Validate required fields
        foreach ($required in @('vm_name', 'image_name', 'gb_ram', 'cpu_cores', 'guest_la_uid', 'guest_la_pw')) {
            if (-not ($values.ContainsKey($required) -and $values[$required])) {
                throw "Job definition missing required field '$required'."
            }
        }

        $values['gb_ram'] = [int]$values['gb_ram']
        $values['cpu_cores'] = [int]$values['cpu_cores']

        $vmClustered = $false
        if ($values.ContainsKey('vm_clustered')) {
            $vmClustered = [bool]$values['vm_clustered']
        }

        # Determine OS family
        $osFamily = 'windows'
        if ($values.ContainsKey('os_family') -and $values['os_family']) {
            $osFamily = $values['os_family'].ToString().ToLowerInvariant()
        }
        else {
            $imageName = $values['image_name'].ToString().ToLowerInvariant()
            if ($imageName.StartsWith('ubuntu') -or $imageName.StartsWith('rhel') -or $imageName.StartsWith('centos') -or $imageName.StartsWith('rocky') -or $imageName.StartsWith('debian')) {
                $osFamily = 'linux'
            }
        }

        # Load host resources configuration
        $configPath = "C:\ProgramData\Aether-V\hostresources.json"
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            $configPath = "C:\ProgramData\Aether-V\hostresources.yaml"
            if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
                throw "Host resources configuration file not found"
            }
        }

        $rawConfig = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop
        
        $hostConfig = $null
        if ($configPath.EndsWith('.json')) {
            $hostConfig = $rawConfig | ConvertFrom-Json -ErrorAction Stop
        }
        elseif ($configPath.EndsWith('.yaml') -or $configPath.EndsWith('.yml')) {
            if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
                Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
            }
            $hostConfig = ConvertFrom-Yaml -Yaml $rawConfig -ErrorAction Stop
        }

        $hostConfig = ConvertTo-Hashtable -InputObject $hostConfig

        # Resolve storage path
        $storagePath = $null
        if ($values.ContainsKey('storage_class') -and $values['storage_class']) {
            $storageClasses = $hostConfig['storage_classes']
            $storageClassName = $values['storage_class']
            foreach ($storageClass in $storageClasses) {
                if ($storageClass['name'] -eq $storageClassName) {
                    $storagePath = $storageClass['path']
                    break
                }
            }
            if (-not $storagePath) {
                throw "Storage class '$storageClassName' not found in host configuration"
            }
        }
        else {
            $storageClasses = $hostConfig['storage_classes']
            if ($storageClasses -and $storageClasses.Count -gt 0) {
                $storagePath = $storageClasses[0]['path']
            }
            else {
                throw "No storage classes defined in host configuration"
            }
        }

        # Resolve VM path
        $vmBasePath = $hostConfig['virtual_machines_path']
        if ([string]::IsNullOrWhiteSpace($vmBasePath)) {
            throw "No virtual_machines_path defined in host configuration"
        }

        $vmName = [string]$values['vm_name']
        $imageName = [string]$values['image_name']
        $gbRam = [int]$values['gb_ram']
        $cpuCores = [int]$values['cpu_cores']

        $currentHost = $env:COMPUTERNAME
        Write-Host "Creating VM '$vmName' on host '$currentHost' (OS: $osFamily)."

        # Copy image - this creates the VM config folder and initial disk
        $copyResult = Invoke-ProvisioningCopyImage -VMName $vmName -ImageName $imageName -StoragePath $storagePath -VMBasePath $vmBasePath
        $vmDataFolder = $copyResult.VMConfigPath
        $vhdxPath = $copyResult.VhdxPath
        
        Write-Host "Image copied to $vhdxPath" -ForegroundColor Green
        Write-Host "VM config directory: $vmDataFolder" -ForegroundColor Green

        # Create provisioning ISO for guest configuration
        $isoPath = Invoke-ProvisioningCopyProvisioningIso -OSFamily $osFamily -StoragePath $storagePath -VMName $vmName

        # Register VM with Hyper-V (without network adapter - that will be added separately)
        $registerParams = @{
            VMName       = $vmName
            OSFamily     = $osFamily
            GBRam        = $gbRam
            CPUcores     = $cpuCores
            VMDataFolder = $vmDataFolder
            VhdxPath     = $vhdxPath
            IsoPath      = $isoPath
        }

        Invoke-ProvisioningRegisterVm @registerParams | Out-Null

        # Get the VM ID
        $vm = Get-VM -Name $vmName -ErrorAction Stop
        $vmId = $vm.Id.ToString()

        # Wait for provisioning key (VM starts automatically during registration)
        Invoke-ProvisioningWaitForProvisioningKey -VMName $vmName | Out-Null

        # Publish provisioning data
        $env:GuestLaPw = [string]$values['guest_la_pw']
        if ($values.ContainsKey('guest_domain_joinpw') -and $values['guest_domain_joinpw']) {
            $env:GuestDomainJoinPw = [string]$values['guest_domain_joinpw']
        }
        else {
            Remove-Item Env:GuestDomainJoinPw -ErrorAction SilentlyContinue
        }

        $publishParams = @{
            GuestLaUid    = [string]$values['guest_la_uid']
            GuestHostName = $vmName
        }

        if ($osFamily -eq 'windows' -and $values.ContainsKey('guest_domain_jointarget') -and $values['guest_domain_jointarget']) {
            $publishParams.GuestDomainJoinTarget = [string]$values['guest_domain_jointarget']
            $publishParams.GuestDomainJoinUid = [string]$values['guest_domain_joinuid']
            if ($values.ContainsKey('guest_domain_joinou') -and $values['guest_domain_joinou']) {
                $publishParams.GuestDomainJoinOU = [string]$values['guest_domain_joinou']
            }
        }

        if ($osFamily -eq 'linux' -and $values.ContainsKey('cnf_ansible_ssh_user') -and $values['cnf_ansible_ssh_user']) {
            $publishParams.AnsibleSshUser = [string]$values['cnf_ansible_ssh_user']
            if ($values.ContainsKey('cnf_ansible_ssh_key') -and $values['cnf_ansible_ssh_key']) {
                $publishParams.AnsibleSshKey = [string]$values['cnf_ansible_ssh_key']
            }
        }

        Invoke-ProvisioningPublishProvisioningData @publishParams

        # Wait for provisioning to complete
        Invoke-ProvisioningWaitForProvisioningCompletion -VMName $vmName | Out-Null

        # Cleanup ISO
        Invoke-ProvisioningCleanupIso -VMName $vmName -IsoPath $isoPath

        # Add to cluster if requested
        if ($vmClustered) {
            try {
                Import-Module FailoverClusters -ErrorAction Stop | Out-Null
                $existing = Get-ClusterGroup -Name $vmName -ErrorAction SilentlyContinue
                if (-not $existing) {
                    Write-Host "Adding VM '$vmName' to the Failover Cluster..."
                    Add-ClusterVirtualMachineRole -VMName $vmName -ErrorAction Stop | Out-Null
                    Write-Host "VM '$vmName' added to cluster." -ForegroundColor Green
                }
            }
            catch {
                Write-Warning "Failed to add VM '$vmName' to cluster: $_"
            }
        }

        Write-Host "VM creation completed successfully." -ForegroundColor Green
        Write-Host "VM ID: $vmId" -ForegroundColor Cyan
        
        # Output the VM ID as JSON for the control plane
        $result = @{
            vm_id = $vmId
            vm_name = $vmName
            status = "created"
        }
        $result | ConvertTo-Json -Depth 2
    }

    try {
        $pipelineValues = @()
        if ($script:CollectedInput) {
            $pipelineValues = $script:CollectedInput.ToArray()
        }

        Invoke-CreateVmWorkflow -PipelineValues $pipelineValues
        exit 0
    }
    catch {
        Write-Error ("VM creation job failed: " + $_.Exception.Message)
        exit 1
    }
    finally {
        Remove-Item Env:GuestLaPw -ErrorAction SilentlyContinue
        Remove-Item Env:GuestDomainJoinPw -ErrorAction SilentlyContinue
    }
}
