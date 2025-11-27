# Main-NewProtocol.ps1
# Resource operation entry point for all VM, Disk, and NIC operations
#
# This script accepts a JSON job envelope via STDIN and returns a JSON job result.
# Implements all VM, Disk, and NIC create/update/delete operations using the
# standardized JobRequest/JobResult envelope protocol.
#
# Expected input envelope format:
# {
#   "operation": "vm.create" | "vm.update" | "vm.delete" | "disk.create" | "disk.update" | "disk.delete" | "nic.create" | "nic.update" | "nic.delete" | "noop-test",
#   "resource_spec": { ... },
#   "correlation_id": "uuid",
#   "metadata": { ... }
# }
#
# Output result format:
# {
#   "status": "success" | "error" | "partial",
#   "message": "Operation completed",
#   "data": { ... },
#   "correlation_id": "uuid",
#   "logs": []
# }

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
    
    # Source common provisioning functions
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    . (Join-Path $scriptRoot 'Provisioning.CleanupISO.ps1')
    . (Join-Path $scriptRoot 'Provisioning.CopyImage.ps1')
    . (Join-Path $scriptRoot 'Provisioning.CopyProvisioningISO.ps1')
    . (Join-Path $scriptRoot 'Provisioning.PublishProvisioningData.ps1')
    . (Join-Path $scriptRoot 'Provisioning.RegisterVM.ps1')
    . (Join-Path $scriptRoot 'Provisioning.WaitForProvisioningKey.ps1')
    
    # Initialize provisioning scripts version from version file if available
    # This is required for KVP version exchange with guest agents during vm.initialize
    # but is optional for other operations (vm.create, disk.create, etc.)
    $script:VersionFilePath = Join-Path $scriptRoot 'version'
    if (Test-Path -LiteralPath $script:VersionFilePath -PathType Leaf) {
        $rawVersion = Get-Content -LiteralPath $script:VersionFilePath -Raw -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($rawVersion)) {
            $global:ProvisioningScriptsVersion = $rawVersion.Trim()
        }
    }
}

process {
    if ($PSBoundParameters.ContainsKey('InputObject')) {
        $null = $script:CollectedInput.Add($InputObject)
    }
}

end {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    function Write-JobResult {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [ValidateSet('success', 'error', 'partial')]
            [string]$Status,

            [Parameter(Mandatory = $true)]
            [string]$Message,

            [Parameter()]
            [hashtable]$Data = @{},

            [Parameter()]
            [string]$Code = $null,

            [Parameter()]
            [string[]]$Logs = @(),

            [Parameter()]
            [string]$CorrelationId = $null
        )

        $result = @{
            status  = $Status
            message = $Message
            data    = $Data
        }

        if ($Code) {
            $result['code'] = $Code
        }

        if ($Logs) {
            $result['logs'] = $Logs
        }

        if ($CorrelationId) {
            $result['correlation_id'] = $CorrelationId
        }

        $json = $result | ConvertTo-Json -Depth 10 -Compress
        Write-Output $json
    }

    function Read-JobEnvelope {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null
        
        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $rawInput = $PipelinedInput -join "`n"
        }
        else {
            # Read from STDIN if no piped input
            $stdinLines = @()
            try {
                while ($null -ne ($line = [Console]::In.ReadLine())) {
                    $stdinLines += $line
                }
            }
            catch {
                # End of input
            }
            
            if ($stdinLines.Count -gt 0) {
                $rawInput = $stdinLines -join "`n"
            }
        }

        if (-not $rawInput -or $rawInput.Trim() -eq '') {
            throw 'No input received. Expected JSON job envelope via STDIN.'
        }

        try {
            $parsedJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
            $envelope = ConvertTo-Hashtable -InputObject $parsedJson
            return $envelope
        }
        catch {
            throw "Failed to parse JSON envelope: $_"
        }
    }

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

        return $InputObject
    }

    # Main execution
    # Initialize correlation_id before try block so it's available in catch
    $correlationId = $null
    
    try {
        # Read and parse the job envelope
        $envelope = Read-JobEnvelope -PipelinedInput $script:CollectedInput

        # Extract correlation_id early for error handling
        if ($envelope.ContainsKey('correlation_id')) {
            $correlationId = $envelope['correlation_id']
        }
        
        # Validate required fields
        if (-not $envelope.ContainsKey('operation')) {
            throw 'Job envelope missing required field: operation'
        }

        if (-not $envelope.ContainsKey('resource_spec')) {
            throw 'Job envelope missing required field: resource_spec'
        }

        $operation = $envelope['operation']
        $resourceSpec = $envelope['resource_spec']
        
        $logs = @()

        # Phase 4: Implement resource operations
        #
        # VM Operations
        #
        if ($operation -eq 'vm.create') {
            $logs += 'Executing vm.create operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract VM spec fields
            $vmName = $resourceSpec['vm_name']
            $gbRam = [int]$resourceSpec['gb_ram']
            $cpuCores = [int]$resourceSpec['cpu_cores']
            $storageClass = $resourceSpec['storage_class']
            $vmClustered = if ($resourceSpec.ContainsKey('vm_clustered')) { [bool]$resourceSpec['vm_clustered'] } else { $false }
            
            $currentHost = $env:COMPUTERNAME
            $logs += "Creating VM: $vmName (RAM: ${gbRam}GB, CPUs: $cpuCores, Storage Class: $storageClass)"
            $logs += "Host: $currentHost"
            
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

            # Resolve storage path from storage_class for VM configuration files
            $storagePath = $null
            if ($storageClass) {
                $storageClasses = $hostConfig['storage_classes']
                foreach ($sc in $storageClasses) {
                    if ($sc['name'] -eq $storageClass) {
                        $storagePath = $sc['path']
                        break
                    }
                }
                if (-not $storagePath) {
                    throw "Storage class '$storageClass' not found in host configuration"
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

            # Resolve VM configuration path - stored in the storage class location
            $vmDataFolder = Join-Path -Path $storagePath -ChildPath $vmName

            # Determine OS family - default to Windows for Phase 4
            $osFamily = 'windows'

            # Register VM with Hyper-V (without disk, network adapter, or ISO - those will be added separately)
            $registerParams = @{
                VMName       = $vmName
                OSFamily     = $osFamily
                GBRam        = $gbRam
                CPUcores     = $cpuCores
                VMDataFolder = $vmDataFolder
                VhdxPath     = $null  # No disk attached during VM creation
            }

            Invoke-ProvisioningRegisterVm @registerParams | Out-Null

            # Get the VM ID
            $vm = Get-VM -Name $vmName -ErrorAction Stop
            $vmId = $vm.Id.ToString()
            
            $logs += "VM created successfully with ID: $vmId"

            $resultData = @{
                vm_id   = $vmId
                vm_name = $vmName
                status  = "created"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "VM '$vmName' created successfully" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # vm.update operation (intentional stub for Phase 4)
        #
        elseif ($operation -eq 'vm.update') {
            $logs += 'Executing vm.update operation'
            $logs += "Correlation ID: $correlationId"
            
            # Phase 4: vm.update is intentionally a stub
            # Full implementation would update VM properties like RAM, CPU, etc.
            # This will be implemented in a future phase when update semantics are fully defined
            $vmId = $resourceSpec['vm_id']
            
            $logs += "VM update operation for VM ID: $vmId"
            
            $resultData = @{
                vm_id  = $vmId
                status = "updated"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "VM update completed (stub implementation)" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # vm.delete operation
        #
        elseif ($operation -eq 'vm.delete') {
            $logs += 'Executing vm.delete operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract VM identifier
            $vmName = $resourceSpec['vm_name']
            $vmId = $resourceSpec['vm_id']
            $deleteDisks = if ($resourceSpec.ContainsKey('delete_disks')) { [bool]$resourceSpec['delete_disks'] } else { $false }
            
            $logs += "Deleting VM: $vmName (ID: $vmId)"
            $logs += "Delete disks: $deleteDisks"
            
            # Get VM
            $vm = $null
            if ($vmId) {
                $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
            }
            elseif ($vmName) {
                $vm = Get-VM -Name $vmName -ErrorAction SilentlyContinue
            }
            
            if (-not $vm) {
                throw "VM not found: $vmName"
            }
            
            # Stop VM if running
            if ($vm.State -ne 'Off') {
                $logs += "Stopping VM..."
                Stop-VM -VM $vm -Force -ErrorAction Stop
            }
            
            # Handle disk cleanup if requested
            $diskPaths = @()
            if ($deleteDisks) {
                $hardDisks = @(Get-VMHardDiskDrive -VM $vm -ErrorAction SilentlyContinue)
                
                if ($hardDisks.Count -gt 0) {
                    $logs += "Checking for shared disks before deletion..."
                    
                    # Validate no shared disks using SupportPersistentReservations property
                    foreach ($disk in $hardDisks) {
                        if (-not $disk.Path) {
                            continue
                        }
                        
                        # Check if this is a shared disk (cluster shared volume)
                        if ($disk.SupportPersistentReservations) {
                            throw "Cannot delete VM with delete_disks=true: Disk '$($disk.Path)' is a shared disk (SupportPersistentReservations=True). Detach shared disks manually or set delete_disks=false."
                        }
                        
                        # Verify the disk file exists
                        if (-not (Test-Path -LiteralPath $disk.Path -PathType Leaf)) {
                            $logs += "WARNING: Disk file '$($disk.Path)' not found; will skip deletion."
                        }
                    }
                    
                    $logs += "No shared disks detected. Detaching and collecting disk paths..."
                    
                    # Collect disk paths and detach
                    foreach ($disk in $hardDisks) {
                        if ($disk.Path) {
                            $diskPaths += $disk.Path
                        }
                        $logs += "Detaching disk: $($disk.Path)"
                        Remove-VMHardDiskDrive -VMHardDiskDrive $disk -Confirm:$false -ErrorAction Stop
                    }
                }
            }
            
            # Remove VM
            $logs += "Removing VM from Hyper-V..."
            Remove-VM -VM $vm -Force -ErrorAction Stop
            
            # Delete disk files if requested
            if ($deleteDisks -and $diskPaths.Count -gt 0) {
                $logs += "Deleting $($diskPaths.Count) disk file(s)..."
                foreach ($diskPath in $diskPaths) {
                    if (Test-Path -LiteralPath $diskPath -PathType Leaf) {
                        $logs += "Deleting disk: $diskPath"
                        Remove-Item -LiteralPath $diskPath -Force -ErrorAction Stop
                        Start-Sleep -Milliseconds 200
                        
                        if (Test-Path -LiteralPath $diskPath) {
                            throw "Failed to delete disk file: $diskPath"
                        }
                    }
                    else {
                        $logs += "WARNING: Disk file not found (already deleted?): $diskPath"
                    }
                }
                $logs += "All disk files deleted successfully"
            }
            elseif (-not $deleteDisks) {
                $logs += "Disk deletion not requested (delete_disks=false)"
            }
            
            $logs += "VM deleted successfully"
            
            $resultData = @{
                vm_id         = $vmId
                vm_name       = $vmName
                status        = "deleted"
                disks_deleted = $deleteDisks
                disk_count    = $diskPaths.Count
            }

            Write-JobResult `
                -Status 'success' `
                -Message "VM '$vmName' deleted successfully" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # Disk Operations
        #
        elseif ($operation -eq 'disk.create') {
            $logs += 'Executing disk.create operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract disk spec fields
            $vmId = $resourceSpec['vm_id']
            $imageName = $resourceSpec['image_name']
            $diskSizeGb = if ($resourceSpec.ContainsKey('disk_size_gb')) { [int]$resourceSpec['disk_size_gb'] } else { 100 }
            $storageClass = $resourceSpec['storage_class']
            $diskType = if ($resourceSpec.ContainsKey('disk_type')) { $resourceSpec['disk_type'] } else { 'Dynamic' }
            $controllerType = if ($resourceSpec.ContainsKey('controller_type')) { $resourceSpec['controller_type'] } else { 'SCSI' }
            
            # Get VM by ID
            $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
            if (-not $vm) {
                throw "VM with ID '$vmId' not found on this host"
            }
            
            $vmName = $vm.Name
            $logs += "Creating disk for VM '$vmName' (ID: $vmId)"
            
            # Get the VM's configuration path - this is where disks should be stored
            # to keep VM config files and disks together
            $vmConfigPath = $vm.ConfigurationLocation
            if ([string]::IsNullOrWhiteSpace($vmConfigPath)) {
                throw "Unable to determine VM configuration location for VM '$vmName'"
            }
            
            # Use the VM's parent folder (where the VM and its Virtual Hard Disks folder are located)
            $vmFolder = Split-Path -Parent $vmConfigPath
            $storagePath = $vmFolder
            $logs += "Using VM's folder for disk storage: $storagePath"
            
            # Create or clone disk
            $vhdxPath = $null
            if ($imageName) {
                $logs += "Cloning from golden image: $imageName"
                
                # Find golden image
                $staticImagesPath = Get-ChildItem -Path "C:\ClusterStorage" -Directory |
                ForEach-Object {
                    $diskImagesPath = Join-Path $_.FullName "DiskImages"
                    if (Test-Path $diskImagesPath) {
                        return $diskImagesPath
                    }
                } |
                Select-Object -First 1
                
                if (-not $staticImagesPath) {
                    throw "Unable to locate a DiskImages directory on any cluster shared volume"
                }
                
                $imageFilename = "$imageName.vhdx"
                $imagePath = Join-Path -Path $staticImagesPath -ChildPath $imageFilename
                
                if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
                    throw "Golden image '$imageName' not found at $imagePath"
                }
                
                # Generate unique VHDX name
                $uniqueId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
                $uniqueVhdxName = "${imageName}-${uniqueId}.vhdx"
                $vhdxPath = Join-Path -Path $storagePath -ChildPath $uniqueVhdxName
                
                # Copy image
                Copy-Item -Path $imagePath -Destination $vhdxPath -Force -ErrorAction Stop
                $logs += "Image copied to: $vhdxPath"
            }
            else {
                $logs += "Creating blank ${diskSizeGb}GB disk"
                
                $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $vhdxFileName = "${vmName}-disk-${timestamp}.vhdx"
                $vhdxPath = Join-Path -Path $storagePath -ChildPath $vhdxFileName
                
                $diskSizeBytes = $diskSizeGb * 1GB
                if ($diskType -eq 'Fixed') {
                    New-VHD -Path $vhdxPath -SizeBytes $diskSizeBytes -Fixed -ErrorAction Stop | Out-Null
                }
                else {
                    New-VHD -Path $vhdxPath -SizeBytes $diskSizeBytes -Dynamic -ErrorAction Stop | Out-Null
                }
                $logs += "VHDX created at: $vhdxPath"
            }
            
            # Find next available controller slot
            $controllerNumber = 0
            $nextLocation = 0
            
            if ($controllerType -eq 'SCSI') {
                $scsiControllers = Get-VMScsiController -VM $vm
                if ($scsiControllers) {
                    $foundSlot = $false
                    foreach ($ctrl in $scsiControllers | Sort-Object ControllerNumber) {
                        $usedLocations = if ($ctrl.Drives) { @($ctrl.Drives | ForEach-Object { $_.ControllerLocation }) } else { @() }
                        for ($loc = 0; $loc -lt 64; $loc++) {
                            if ($loc -notin $usedLocations) {
                                $controllerNumber = $ctrl.ControllerNumber
                                $nextLocation = $loc
                                $foundSlot = $true
                                break
                            }
                        }
                        if ($foundSlot) { break }
                    }
                }
            }
            
            # Attach disk to VM
            $logs += "Attaching disk to $controllerType controller $controllerNumber at location $nextLocation"
            Add-VMHardDiskDrive -VM $vm -Path $vhdxPath -ControllerType $controllerType -ControllerNumber $controllerNumber -ControllerLocation $nextLocation -ErrorAction Stop
            
            # Get the disk ID
            $newDisk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Path -eq $vhdxPath }
            $diskId = $newDisk.Id
            
            $logs += "Disk created and attached successfully"
            
            $resultData = @{
                disk_id   = $diskId
                disk_path = $vhdxPath
                vm_id     = $vmId
                vm_name   = $vmName
                status    = "created"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "Disk created and attached to VM '$vmName'" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        elseif ($operation -eq 'disk.update') {
            $logs += 'Executing disk.update operation'
            $logs += "Correlation ID: $correlationId"
            
            # Phase 4: disk.update is intentionally a stub
            # Full implementation would resize disks or modify disk properties
            # This will be implemented in a future phase when update semantics are fully defined
            $vmId = $resourceSpec['vm_id']
            $resourceId = $resourceSpec['resource_id']
            
            $resultData = @{
                disk_id = $resourceId
                vm_id   = $vmId
                status  = "updated"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "Disk update completed (stub implementation)" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        elseif ($operation -eq 'disk.delete') {
            $logs += 'Executing disk.delete operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract identifiers
            $vmId = $resourceSpec['vm_id']
            $resourceId = $resourceSpec['resource_id']
            
            # Get VM
            $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
            if (-not $vm) {
                throw "VM with ID '$vmId' not found"
            }
            
            # Get disk by ID
            $disk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Id -eq $resourceId }
            if (-not $disk) {
                throw "Disk with ID '$resourceId' not found on VM"
            }
            
            $diskPath = $disk.Path
            $logs += "Removing disk: $diskPath"
            
            # Remove disk from VM
            Remove-VMHardDiskDrive -VMHardDiskDrive $disk -ErrorAction Stop
            
            # Optionally delete the VHDX file (for now, we'll delete it)
            if (Test-Path -LiteralPath $diskPath) {
                Remove-Item -LiteralPath $diskPath -Force -ErrorAction Stop
                $logs += "VHDX file deleted: $diskPath"
            }
            
            $resultData = @{
                disk_id = $resourceId
                vm_id   = $vmId
                status  = "deleted"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "Disk deleted successfully" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # NIC Operations
        #
        elseif ($operation -eq 'nic.create') {
            $logs += 'Executing nic.create operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract NIC spec fields
            $vmId = $resourceSpec['vm_id']
            $networkName = $resourceSpec['network']
            $adapterName = $resourceSpec['adapter_name']
            
            # Get VM by ID
            $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
            if (-not $vm) {
                throw "VM with ID '$vmId' not found on this host"
            }
            
            $vmName = $vm.Name
            $logs += "Creating network adapter for VM '$vmName' (ID: $vmId)"
            
            # Load host configuration
            $configPath = "C:\ProgramData\Aether-V\hostresources.json"
            if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
                $configPath = "C:\ProgramData\Aether-V\hostresources.yaml"
            }
            
            $rawConfig = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop
            $hostConfig = $null
            if ($configPath.EndsWith('.json')) {
                $hostConfig = $rawConfig | ConvertFrom-Json -ErrorAction Stop
            }
            else {
                if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
                    Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
                }
                $hostConfig = ConvertFrom-Yaml -Yaml $rawConfig -ErrorAction Stop
            }
            $hostConfig = ConvertTo-Hashtable -InputObject $hostConfig
            
            # Resolve network configuration
            $networkConfig = $null
            foreach ($network in $hostConfig['networks']) {
                if ($network['name'] -eq $networkName) {
                    $networkConfig = $network
                    break
                }
            }
            
            if (-not $networkConfig) {
                throw "Network '$networkName' not found in host configuration"
            }
            
            $virtualSwitch = $networkConfig['configuration']['virtual_switch']
            $vlanId = $null
            if ($networkConfig['configuration'].ContainsKey('vlan_id') -and $null -ne $networkConfig['configuration']['vlan_id']) {
                $vlanId = [int]$networkConfig['configuration']['vlan_id']
            }
            
            # Determine adapter name
            if (-not $adapterName) {
                $existingAdapters = @(Get-VMNetworkAdapter -VM $vm)
                $adapterCount = $existingAdapters.Count
                $adapterName = "Network Adapter $($adapterCount + 1)"
            }
            
            $logs += "Adding adapter '$adapterName' to switch '$virtualSwitch'"
            
            # Add network adapter
            Add-VMNetworkAdapter -VM $vm -Name $adapterName -SwitchName $virtualSwitch -ErrorAction Stop
            
            # Get the newly created adapter
            $newAdapter = Get-VMNetworkAdapter -VM $vm -Name $adapterName -ErrorAction Stop
            
            # Set VLAN if specified
            if ($null -ne $vlanId) {
                $logs += "Setting VLAN ID to $vlanId"
                Set-VMNetworkAdapterVlan -VMNetworkAdapter $newAdapter -Access -VlanId $vlanId -ErrorAction Stop
            }
            
            $adapterId = $newAdapter.Id
            $macAddress = $newAdapter.MacAddress
            
            $logs += "Network adapter created successfully"
            
            $resultData = @{
                nic_id         = $adapterId
                adapter_name   = $adapterName
                vm_id          = $vmId
                vm_name        = $vmName
                network        = $networkName
                virtual_switch = $virtualSwitch
                vlan_id        = $vlanId
                mac_address    = $macAddress
                status         = "created"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "Network adapter created for VM '$vmName'" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        elseif ($operation -eq 'nic.update') {
            $logs += 'Executing nic.update operation'
            $logs += "Correlation ID: $correlationId"
            
            # Phase 4: nic.update is intentionally a stub
            # Full implementation would change NIC network or VLAN settings
            # This will be implemented in a future phase when update semantics are fully defined
            $vmId = $resourceSpec['vm_id']
            $resourceId = $resourceSpec['resource_id']
            
            $resultData = @{
                nic_id = $resourceId
                vm_id  = $vmId
                status = "updated"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "NIC update completed (stub implementation)" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        elseif ($operation -eq 'nic.delete') {
            $logs += 'Executing nic.delete operation'
            $logs += "Correlation ID: $correlationId"
            
            # Extract identifiers
            $vmId = $resourceSpec['vm_id']
            $resourceId = $resourceSpec['resource_id']
            
            # Get VM
            $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
            if (-not $vm) {
                throw "VM with ID '$vmId' not found"
            }
            
            # Get NIC by ID
            $nic = Get-VMNetworkAdapter -VM $vm | Where-Object { $_.Id -eq $resourceId }
            if (-not $nic) {
                throw "Network adapter with ID '$resourceId' not found on VM"
            }
            
            $adapterName = $nic.Name
            $logs += "Removing network adapter: $adapterName"
            
            # Remove NIC from VM
            Remove-VMNetworkAdapter -VMNetworkAdapter $nic -ErrorAction Stop
            
            $logs += "Network adapter deleted successfully"
            
            $resultData = @{
                nic_id = $resourceId
                vm_id  = $vmId
                status = "deleted"
            }

            Write-JobResult `
                -Status 'success' `
                -Message "Network adapter deleted successfully" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # vm.initialize operation (Guest OS initialization via KVP)
        #
        elseif ($operation -eq 'vm.initialize') {
            $logs += 'Executing vm.initialize operation'
            $logs += "Correlation ID: $correlationId"
            
            # Validate provisioning scripts version is available
            # This is required for KVP version exchange with guest agents
            if ([string]::IsNullOrWhiteSpace($global:ProvisioningScriptsVersion)) {
                throw "Provisioning scripts version not initialized. Ensure the version file is deployed at '$($script:VersionFilePath)' with the agent scripts."
            }
            $logs += "Provisioning scripts version: $global:ProvisioningScriptsVersion"
            
            # Extract required fields
            $vmId = $resourceSpec['vm_id']
            $vmName = $resourceSpec['vm_name']
            
            if (-not $vmId) {
                throw "vm_id is required for guest initialization"
            }
            
            if (-not $vmName) {
                throw "vm_name is required for guest initialization"
            }
            
            $logs += "VM ID: $vmId"
            $logs += "VM Name: $vmName"
            
            # Get VM object
            $vm = Get-VM -Id $vmId -ErrorAction Stop
            if (-not $vm) {
                throw "VM with ID '$vmId' not found"
            }
            
            # Determine storage location for ISO
            $vmConfigPath = $vm.ConfigurationLocation
            if ([string]::IsNullOrWhiteSpace($vmConfigPath)) {
                throw "Unable to determine VM configuration location for VM '$($vm.Name)'"
            }
            
            $vmFolder = Split-Path -Parent $vmConfigPath
            $storagePath = $vmFolder
            
            # Determine OS family - default to Windows
            $osFamily = 'windows'
            
            # Step 1: Copy provisioning ISO
            $logs += "Copying provisioning ISO for $osFamily guest..."
            $isoPath = Invoke-ProvisioningCopyProvisioningIso -OSFamily $osFamily -StoragePath $storagePath -VMName $vmName
            $logs += "Provisioning ISO copied to: $isoPath"
            
            # Step 2: Mount provisioning ISO
            $logs += "Mounting provisioning ISO to VM..."
            Add-VMDvdDrive -VM $vm -Path $isoPath -ErrorAction Stop
            $logs += "Provisioning ISO mounted successfully"
            
            # Step 3: Start VM
            $logs += "Starting VM..."
            Start-VM -VM $vm -ErrorAction Stop
            $logs += "VM started successfully"
            
            # Step 4: Wait for guest readiness
            $logs += "Waiting for guest to signal provisioning readiness..."
            $ready = Invoke-ProvisioningWaitForProvisioningKey -VMName $vmName -TimeoutSeconds 300
            if (-not $ready) {
                throw "Guest did not signal readiness for provisioning"
            }
            $logs += "Guest is ready for provisioning"
            
            # Step 5: Publish provisioning data
            $logs += "Publishing provisioning data to guest..."
            
            if (-not $resourceSpec['guest_la_uid']) {
                throw "guest_la_uid is required for guest initialization"
            }
            
            # Build parameters for provisioning
            $publishParams = @{
                GuestHostName = $vmName
                GuestLaUid    = $resourceSpec['guest_la_uid']
            }
            
            # Optional networking configuration
            if ($resourceSpec.ContainsKey('guest_v4_ip_addr') -and $resourceSpec['guest_v4_ip_addr']) {
                $publishParams['GuestV4IpAddr'] = $resourceSpec['guest_v4_ip_addr']
            }
            if ($resourceSpec.ContainsKey('guest_v4_cidr_prefix') -and $resourceSpec['guest_v4_cidr_prefix']) {
                $publishParams['GuestV4CidrPrefix'] = $resourceSpec['guest_v4_cidr_prefix']
            }
            if ($resourceSpec.ContainsKey('guest_v4_default_gw') -and $resourceSpec['guest_v4_default_gw']) {
                $publishParams['GuestV4DefaultGw'] = $resourceSpec['guest_v4_default_gw']
            }
            if ($resourceSpec.ContainsKey('guest_v4_dns1') -and $resourceSpec['guest_v4_dns1']) {
                $publishParams['GuestV4Dns1'] = $resourceSpec['guest_v4_dns1']
            }
            if ($resourceSpec.ContainsKey('guest_v4_dns2') -and $resourceSpec['guest_v4_dns2']) {
                $publishParams['GuestV4Dns2'] = $resourceSpec['guest_v4_dns2']
            }
            if ($resourceSpec.ContainsKey('guest_net_dns_suffix') -and $resourceSpec['guest_net_dns_suffix']) {
                $publishParams['GuestNetDnsSuffix'] = $resourceSpec['guest_net_dns_suffix']
            }
            
            # Optional domain join configuration
            if ($resourceSpec.ContainsKey('guest_domain_join_target') -and $resourceSpec['guest_domain_join_target']) {
                $publishParams['GuestDomainJoinTarget'] = $resourceSpec['guest_domain_join_target']
            }
            if ($resourceSpec.ContainsKey('guest_domain_join_uid') -and $resourceSpec['guest_domain_join_uid']) {
                $publishParams['GuestDomainJoinUid'] = $resourceSpec['guest_domain_join_uid']
            }
            if ($resourceSpec.ContainsKey('guest_domain_join_ou') -and $resourceSpec['guest_domain_join_ou']) {
                $publishParams['GuestDomainJoinOU'] = $resourceSpec['guest_domain_join_ou']
            }
            
            # Optional Ansible SSH configuration
            if ($resourceSpec.ContainsKey('cnf_ansible_ssh_user') -and $resourceSpec['cnf_ansible_ssh_user']) {
                $publishParams['AnsibleSshUser'] = $resourceSpec['cnf_ansible_ssh_user']
            }
            if ($resourceSpec.ContainsKey('cnf_ansible_ssh_key') -and $resourceSpec['cnf_ansible_ssh_key']) {
                $publishParams['AnsibleSshKey'] = $resourceSpec['cnf_ansible_ssh_key']
            }
            
            # Password handling: Environment variables are used instead of command-line parameters
            # to avoid exposing credentials in process listings. While environment variables are
            # visible to child processes, this is acceptable here because:
            # 1. No child processes are spawned during password transmission
            # 2. Variables are cleared immediately after use in the finally block
            # 3. The provisioning publish function encrypts data before transmission via KVP
            # Note: SecureString would require changes throughout the entire provisioning chain
            # and would not prevent memory exposure in the receiving guest agent.
            if ($resourceSpec.ContainsKey('guest_la_pw') -and $resourceSpec['guest_la_pw']) {
                $env:GuestLaPw = $resourceSpec['guest_la_pw']
            } else {
                throw "guest_la_pw is required for guest initialization"
            }
            if ($resourceSpec.ContainsKey('guest_domain_join_pw') -and $resourceSpec['guest_domain_join_pw']) {
                $env:GuestDomainJoinPw = $resourceSpec['guest_domain_join_pw']
            }
            
            try {
                # Publish data to guest
                Invoke-ProvisioningPublishProvisioningData @publishParams
                $logs += "Provisioning data published successfully"
            }
            finally {
                # Clear sensitive environment variables immediately after use
                $env:GuestLaPw = $null
                $env:GuestDomainJoinPw = $null
            }
            
            # Step 6: Wait for guest to complete provisioning
            $logs += "Waiting for guest to complete provisioning..."
            Invoke-ProvisioningWaitForProvisioningCompletion -VMName $vmName -TimeoutSeconds 1800 -PollIntervalSeconds 5
            $logs += "Guest provisioning completed successfully"
            
            $resultData = @{
                vm_id                 = $vmId
                vm_name               = $vmName
                status                = "initialized"
                provisioning_iso_path = $isoPath
            }
            
            Write-JobResult `
                -Status 'success' `
                -Message "VM '$vmName' guest initialization completed successfully" `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        #
        # Noop-test operation (Phase 3)
        #
        elseif ($operation -eq 'noop-test') {
            # Noop-test: Validate JSON parsing and envelope structure
            $logs += 'Executing noop-test operation'
            $logs += "Correlation ID: $correlationId"
            $logs += "Resource spec validated: $($resourceSpec.Keys.Count) fields"
            
            # Validate STDIN parsing worked correctly
            if ($null -eq $resourceSpec) {
                throw 'Resource spec is null - STDIN parsing failed'
            }
            
            # Validate JSON correctness
            if (-not ($resourceSpec -is [hashtable])) {
                throw 'Resource spec is not a hashtable - JSON parsing failed'
            }
            
            # Echo back some of the resource spec to verify round-trip
            $resultData = @{
                operation_validated = $true
                envelope_parsed     = $true
                json_valid          = $true
                correlation_id      = $correlationId
            }
            
            # Include any test fields from the resource spec
            if ($resourceSpec.ContainsKey('test_field')) {
                $resultData['test_field_echo'] = $resourceSpec['test_field']
            }
            if ($resourceSpec.ContainsKey('test_number')) {
                $resultData['test_number_echo'] = $resourceSpec['test_number']
            }
            
            $logs += 'Noop-test completed successfully'
            
            Write-JobResult `
                -Status 'success' `
                -Message 'Noop-test operation completed successfully' `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        else {
            # Unsupported operations
            throw "Unsupported operation: $operation"
        }
    }
    catch {
        # Return error result
        $errorMessage = $_.Exception.Message
        $errorData = @{
            error_type = $_.Exception.GetType().Name
        }

        Write-JobResult `
            -Status 'error' `
            -Message "Operation error: $errorMessage" `
            -Data $errorData `
            -Code 'OPERATION_ERROR' `
            -CorrelationId $correlationId `
            -Logs @($_.ScriptStackTrace)
    }
}
