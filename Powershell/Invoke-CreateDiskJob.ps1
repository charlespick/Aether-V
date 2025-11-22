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

        # Either image_name or disk_size_gb is required
        $hasImageName = $values.ContainsKey('image_name') -and $values['image_name']
        $hasDiskSize = $values.ContainsKey('disk_size_gb') -and $values['disk_size_gb']
        
        if (-not $hasImageName -and -not $hasDiskSize) {
            throw "Job definition must provide either 'image_name' (to clone from golden image) or 'disk_size_gb' (to create blank disk)."
        }

        $vmId = [string]$values['vm_id']
        $imageName = if ($hasImageName) { [string]$values['image_name'] } else { $null }
        $diskSizeGb = if ($hasDiskSize) { [int]$values['disk_size_gb'] } else { 0 }
        
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

        # Determine next available SCSI controller and location
        $controllerNumber = 0
        $nextLocation = 0
        
        if ($controllerType -eq 'SCSI') {
            $scsiControllers = Get-VMScsiController -VM $vm
            $scsiCtrlCount = if ($scsiControllers) { @($scsiControllers).Count } else { 0 }
            Write-Host "VM has $scsiCtrlCount SCSI controller(s)" -ForegroundColor Cyan
            
            if ($scsiControllers) {
                # Display all drives on all SCSI controllers
                $allDrives = $scsiControllers | ForEach-Object { $_.Drives }
                $totalDrives = if ($allDrives) { @($allDrives).Count } else { 0 }
                Write-Host "Total SCSI drives attached: $totalDrives" -ForegroundColor Cyan
                
                foreach ($ctrl in $scsiControllers) {
                    $drives = $ctrl.Drives
                    $driveCount = if ($drives) { @($drives).Count } else { 0 }
                    Write-Host "  Controller $($ctrl.ControllerNumber): $driveCount drive(s)" -ForegroundColor Gray
                    
                    foreach ($drive in $drives) {
                        $drivePath = if ($drive.Path) { $drive.Path } else { "(empty)" }
                        $driveType = $drive.GetType().Name
                        Write-Host "    Location $($drive.ControllerLocation): $driveType - $drivePath" -ForegroundColor Gray
                    }
                }
                
                # Find first available slot
                $foundSlot = $false
                foreach ($ctrl in $scsiControllers | Sort-Object ControllerNumber) {
                    $ctrlNum = $ctrl.ControllerNumber
                    $usedLocations = if ($ctrl.Drives) { @($ctrl.Drives | ForEach-Object { $_.ControllerLocation }) } else { @() }
                    
                    # Find first free location on this controller (max 64 locations per SCSI controller)
                    for ($loc = 0; $loc -lt 64; $loc++) {
                        if ($loc -notin $usedLocations) {
                            $controllerNumber = $ctrlNum
                            $nextLocation = $loc
                            $foundSlot = $true
                            Write-Host "Found available slot on controller $controllerNumber at location $nextLocation" -ForegroundColor Green
                            break
                        }
                    }
                    if ($foundSlot) { break }
                }
                
                # If no free slot found on existing controllers, use next controller
                if (-not $foundSlot) {
                    $maxController = ($scsiControllers | ForEach-Object { $_.ControllerNumber } | Measure-Object -Maximum).Maximum
                    $controllerNumber = $maxController + 1
                    $nextLocation = 0
                    Write-Host "No free slots on existing controllers. Will use new controller $controllerNumber at location $nextLocation" -ForegroundColor Yellow
                    
                    if ($controllerNumber -gt 3) {
                        throw "All SCSI controllers are full (max 4 controllers with 64 locations each)"
                    }
                }
            }
            else {
                Write-Host "No existing SCSI controllers. Will use controller 0, location 0" -ForegroundColor Cyan
            }
        }

        # Create VHD path
        $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        
        # Determine VHDX path and size based on whether we're cloning or creating blank
        if ($imageName) {
            # Cloning from golden image
            Write-Host "Creating disk from golden image '$imageName' for VM '$vmName' (ID: $vmId)."
            
            # Find the golden image in DiskImages directory
            $staticImagesPath = Get-ChildItem -Path "C:\ClusterStorage" -Directory |
            ForEach-Object {
                $diskImagesPath = Join-Path $_.FullName "DiskImages"
                if (Test-Path $diskImagesPath) {
                    return $diskImagesPath
                }
            } |
            Select-Object -First 1

            if (-not $staticImagesPath) {
                throw "Unable to locate a DiskImages directory on any cluster shared volume."
            }

            $imageFilename = "$imageName.vhdx"
            $imagePath = Join-Path -Path $staticImagesPath -ChildPath $imageFilename
            
            if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
                throw "Golden image '$imageName' was not found at $imagePath."
            }
            
            # Generate unique ID for the VHDX to avoid collisions
            $uniqueId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
            $uniqueVhdxName = "${imageName}-${uniqueId}.vhdx"
            $vhdxPath = Join-Path -Path $storagePath -ChildPath $uniqueVhdxName
            
            $imageSize = (Get-Item -LiteralPath $imagePath).Length
            
            # Check if storage path has enough space
            $storageDrive = Split-Path -Path $storagePath -Qualifier
            if ($storageDrive) {
                try {
                    $drive = Get-PSDrive -Name $storageDrive.TrimEnd(':') -ErrorAction Stop
                    if ($drive.Free -lt $imageSize) {
                        throw "Insufficient free space on $storageDrive to clone image '$imageName'."
                    }
                }
                catch {
                    Write-Warning "Unable to verify free space on $storageDrive : $_"
                }
            }
            
            # Ensure storage path exists
            if (-not (Test-Path -LiteralPath $storagePath)) {
                New-Item -ItemType Directory -Path $storagePath -Force | Out-Null
            }
            
            Write-Host "Copying golden image to $vhdxPath"
            try {
                Copy-Item -Path $imagePath -Destination $vhdxPath -Force -ErrorAction Stop
            }
            catch {
                throw "Failed to copy golden image '$imageName' to ${vhdxPath}: $_"
            }
            
            Write-Host "Image copied successfully" -ForegroundColor Green
        }
        else {
            # Creating blank disk
            Write-Host "Creating blank ${diskSizeGb}GB disk for VM '$vmName' (ID: $vmId)."
            
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
        }

        # Attach disk to VM
        Write-Host "Attempting to attach disk to VM..." -ForegroundColor Cyan
        Write-Host "  Controller Type: $controllerType" -ForegroundColor Gray
        
        if ($controllerType -eq 'SCSI') {
            Write-Host "  Controller Number: $controllerNumber" -ForegroundColor Gray
            Write-Host "  Controller Location: $nextLocation" -ForegroundColor Gray
            Write-Host "  Disk Path: $vhdxPath" -ForegroundColor Gray
            
            try {
                Add-VMHardDiskDrive -VM $vm -Path $vhdxPath -ControllerType SCSI -ControllerNumber $controllerNumber -ControllerLocation $nextLocation -ErrorAction Stop
                Write-Host "Disk attached to SCSI controller $controllerNumber at location $nextLocation" -ForegroundColor Green
            }
            catch {
                Write-Host "Failed to attach disk. Error details:" -ForegroundColor Red
                Write-Host "  Exception: $($_.Exception.Message)" -ForegroundColor Red
                Write-Host "  Exception Type: $($_.Exception.GetType().FullName)" -ForegroundColor Red
                if ($_.Exception.InnerException) {
                    Write-Host "  Inner Exception: $($_.Exception.InnerException.Message)" -ForegroundColor Red
                }
                
                # Try to get more controller information
                Write-Host "`nVM Controller Information:" -ForegroundColor Yellow
                $scsiControllers = Get-VMScsiController -VM $vm
                $scsiCtrlCount = if ($scsiControllers) { @($scsiControllers).Count } else { 0 }
                Write-Host "  SCSI Controllers available: $scsiCtrlCount" -ForegroundColor Gray
                foreach ($ctrl in $scsiControllers) {
                    $drives = $ctrl.Drives
                    $driveCount = if ($drives) { @($drives).Count } else { 0 }
                    Write-Host "    Controller $($ctrl.ControllerNumber): $driveCount drives attached" -ForegroundColor Gray
                    foreach ($drive in $drives) {
                        Write-Host "      Location $($drive.ControllerLocation): $($drive.GetType().Name)" -ForegroundColor DarkGray
                    }
                }
                
                throw
            }
        }
        else {
            # For IDE, find next available controller and location
            Write-Host "Finding available IDE controller slot..." -ForegroundColor Cyan
            
            $ideControllers = Get-VMIdeController -VM $vm
            $ideCtrlCount = if ($ideControllers) { @($ideControllers).Count } else { 0 }
            Write-Host "VM has $ideCtrlCount IDE controller(s)" -ForegroundColor Cyan
            
            $ideControllerNumber = 0
            $ideLocation = 0
            
            if ($ideControllers) {
                # Display all drives on all IDE controllers
                $allDrives = $ideControllers | ForEach-Object { $_.Drives }
                $totalDrives = if ($allDrives) { @($allDrives).Count } else { 0 }
                Write-Host "Total IDE drives attached: $totalDrives" -ForegroundColor Cyan
                
                foreach ($ctrl in $ideControllers) {
                    $drives = $ctrl.Drives
                    $driveCount = if ($drives) { @($drives).Count } else { 0 }
                    Write-Host "  Controller $($ctrl.ControllerNumber): $driveCount drive(s)" -ForegroundColor Gray
                    
                    foreach ($drive in $drives) {
                        $drivePath = if ($drive.Path) { $drive.Path } else { "(empty)" }
                        $driveType = $drive.GetType().Name
                        Write-Host "    Location $($drive.ControllerLocation): $driveType - $drivePath" -ForegroundColor Gray
                    }
                }
                
                # IDE has max 2 controllers (0,1) with 2 locations each (0,1)
                $foundSlot = $false
                foreach ($ctrl in $ideControllers | Sort-Object ControllerNumber) {
                    $ctrlNum = $ctrl.ControllerNumber
                    $usedLocations = if ($ctrl.Drives) { @($ctrl.Drives | ForEach-Object { $_.ControllerLocation }) } else { @() }
                    
                    for ($loc = 0; $loc -lt 2; $loc++) {
                        if ($loc -notin $usedLocations) {
                            $ideControllerNumber = $ctrlNum
                            $ideLocation = $loc
                            $foundSlot = $true
                            Write-Host "Found available slot on controller $ideControllerNumber at location $ideLocation" -ForegroundColor Green
                            break
                        }
                    }
                    if ($foundSlot) { break }
                }
                
                if (-not $foundSlot) {
                    # Try next controller
                    $maxController = ($ideControllers | ForEach-Object { $_.ControllerNumber } | Measure-Object -Maximum).Maximum
                    $ideControllerNumber = $maxController + 1
                    $ideLocation = 0
                    Write-Host "No free slots on existing controllers. Will use new controller $ideControllerNumber at location $ideLocation" -ForegroundColor Yellow
                    
                    if ($ideControllerNumber -gt 1) {
                        throw "No available IDE controller locations (max 2 controllers with 2 locations each)"
                    }
                }
            }
            else {
                Write-Host "No existing IDE controllers. Will use controller 0, location 0" -ForegroundColor Cyan
            }
            
            Write-Host "  Controller Number: $ideControllerNumber" -ForegroundColor Gray
            Write-Host "  Controller Location: $ideLocation" -ForegroundColor Gray
            Write-Host "  Disk Path: $vhdxPath" -ForegroundColor Gray
            
            try {
                Add-VMHardDiskDrive -VM $vm -Path $vhdxPath -ControllerType IDE -ControllerNumber $ideControllerNumber -ControllerLocation $ideLocation -ErrorAction Stop
                Write-Host "Disk attached to IDE controller $ideControllerNumber at location $ideLocation" -ForegroundColor Green
            }
            catch {
                Write-Host "Failed to attach disk. Error details:" -ForegroundColor Red
                Write-Host "  Exception: $($_.Exception.Message)" -ForegroundColor Red
                Write-Host "  Exception Type: $($_.Exception.GetType().FullName)" -ForegroundColor Red
                if ($_.Exception.InnerException) {
                    Write-Host "  Inner Exception: $($_.Exception.InnerException.Message)" -ForegroundColor Red
                }
                
                # Try to get more controller information
                Write-Host "`nVM Controller Information:" -ForegroundColor Yellow
                $ideControllers = Get-VMIdeController -VM $vm
                $ideCtrlCount = if ($ideControllers) { @($ideControllers).Count } else { 0 }
                Write-Host "  IDE Controllers available: $ideCtrlCount" -ForegroundColor Gray
                foreach ($ctrl in $ideControllers) {
                    $drives = $ctrl.Drives
                    $driveCount = if ($drives) { @($drives).Count } else { 0 }
                    Write-Host "    Controller $($ctrl.ControllerNumber): $driveCount drives attached" -ForegroundColor Gray
                    foreach ($drive in $drives) {
                        Write-Host "      Location $($drive.ControllerLocation): $($drive.GetType().Name)" -ForegroundColor DarkGray
                    }
                }
                
                throw
            }
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
            disk_id    = $diskId
            disk_path  = $vhdxPath
            vm_id      = $vmId
            vm_name    = $vmName
            size_gb    = if ($imageName) { "from_image" } else { $diskSizeGb }
            image_name = $imageName
            status     = "created"
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
