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

    function Read-JobDefinition {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null

        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $buffer = @()
            foreach ($item in $PipelinedInput) {
                if ($null -eq $item) {
                    continue
                }

                if ($item -is [string]) {
                    $buffer += [string]$item
                    continue
                }

                if ($item -is [System.Collections.IDictionary] -or $item -is [System.Management.Automation.PSObject]) {
                    $buffer += ($item | ConvertTo-Json -Depth 16 -Compress)
                    continue
                }

                $buffer += [string]$item
            }

            if ($buffer.Count -gt 0) {
                $rawInput = [string]::Join([Environment]::NewLine, $buffer)
            }
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            $rawInput = [Console]::In.ReadToEnd()
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            throw "No job definition was supplied via pipeline or standard input."
        }

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Failed to parse job definition as JSON: $($_.Exception.Message)"
        }

        return ConvertTo-Hashtable -InputObject $parsed
    }

    function Invoke-CreateDiskWorkflow {
        [CmdletBinding()]
        param()

        $jobDefinition = Read-JobDefinition -PipelinedInput $script:CollectedInput

        $rawFields = $jobDefinition.fields
        if (-not $rawFields) {
            throw "Job definition missing 'fields' mapping."
        }

        $values = ConvertTo-Hashtable $rawFields

        # Validate required fields
        if (-not ($values.ContainsKey('vm_id') -and $values['vm_id'])) {
            throw "Job definition missing required field 'vm_id'."
        }

        if (-not ($values.ContainsKey('disk_size_gb') -and $values['disk_size_gb'])) {
            throw "Job definition missing required field 'disk_size_gb'."
        }

        $vmId = [string]$values['vm_id']
        $diskSizeGb = [int]$values['disk_size_gb']
        
        $diskType = 'Dynamic'
        if ($values.ContainsKey('disk_type') -and $values['disk_type']) {
            $diskType = [string]$values['disk_type']
        }

        $controllerType = 'SCSI'
        if ($values.ContainsKey('controller_type') -and $values['controller_type']) {
            $controllerType = [string]$values['controller_type']
        }

        # Get VM by ID
        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Creating disk for VM '$vmName' (ID: $vmId)."

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

        # Determine next available SCSI location
        $existingDisks = Get-VMHardDiskDrive -VM $vm
        $nextLocation = 0
        if ($controllerType -eq 'SCSI') {
            $scsiDisks = $existingDisks | Where-Object { $_.ControllerType -eq 'SCSI' }
            if ($scsiDisks) {
                $usedLocations = $scsiDisks | ForEach-Object { $_.ControllerLocation }
                $nextLocation = 0
                while ($nextLocation -in $usedLocations) {
                    $nextLocation++
                }
            }
        }

        # Create VHD path
        $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $vhdxFileName = "${vmName}-disk-${timestamp}.vhdx"
        $vhdxPath = Join-Path -Path $storagePath -ChildPath $vhdxFileName

        Write-Host "Creating new VHDX at $vhdxPath"
        
        # Create the virtual hard disk
        $diskSizeBytes = $diskSizeGb * 1GB
        if ($diskType -eq 'Fixed') {
            New-VHD -Path $vhdxPath -SizeBytes $diskSizeBytes -Fixed -ErrorAction Stop | Out-Null
        }
        else {
            New-VHD -Path $vhdxPath -SizeBytes $diskSizeBytes -Dynamic -ErrorAction Stop | Out-Null
        }

        Write-Host "VHDX created successfully" -ForegroundColor Green

        # Attach disk to VM
        if ($controllerType -eq 'SCSI') {
            Add-VMHardDiskDrive -VM $vm -Path $vhdxPath -ControllerType SCSI -ControllerLocation $nextLocation -ErrorAction Stop
            Write-Host "Disk attached to SCSI controller at location $nextLocation" -ForegroundColor Green
        }
        else {
            # For IDE, find next available location
            $ideDisks = $existingDisks | Where-Object { $_.ControllerType -eq 'IDE' }
            $ideLocation = 0
            if ($ideDisks) {
                $usedIdeLocations = $ideDisks | ForEach-Object { $_.ControllerLocation }
                while ($ideLocation -in $usedIdeLocations -and $ideLocation -lt 4) {
                    $ideLocation++
                }
                if ($ideLocation -ge 4) {
                    throw "No available IDE controller locations"
                }
            }
            Add-VMHardDiskDrive -VM $vm -Path $vhdxPath -ControllerType IDE -ControllerLocation $ideLocation -ErrorAction Stop
            Write-Host "Disk attached to IDE controller at location $ideLocation" -ForegroundColor Green
        }

        # Get the disk ID
        $newDisk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Path -eq $vhdxPath }
        if (-not $newDisk) {
            throw "Failed to retrieve newly attached disk"
        }

        $diskId = $newDisk.Id

        Write-Host "Disk creation completed successfully." -ForegroundColor Green
        Write-Host "Disk ID: $diskId" -ForegroundColor Cyan
        
        # Output the disk ID as JSON for the control plane
        $result = @{
            disk_id = $diskId
            disk_path = $vhdxPath
            vm_id = $vmId
            vm_name = $vmName
            size_gb = $diskSizeGb
            status = "created"
        }
        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-CreateDiskWorkflow
        exit 0
    }
    catch {
        Write-Error ("Disk creation job failed: " + $_.Exception.Message)
        exit 1
    }
}
