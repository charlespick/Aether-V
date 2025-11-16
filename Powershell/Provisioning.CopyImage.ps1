function Invoke-ProvisioningCopyImage {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [Parameter(Mandatory = $true)]
        [string]$ImageName,

        [Parameter(Mandatory = $true)]
        [string]$StoragePath,

        [Parameter(Mandatory = $true)]
        [string]$VMBasePath
    )

    Write-Host "[VERBOSE] CopyImage: Starting image copy process"
    Write-Host "[VERBOSE] CopyImage: VM Name: $VMName"
    Write-Host "[VERBOSE] CopyImage: Image Name: $ImageName"
    Write-Host "[VERBOSE] CopyImage: Storage Path: $StoragePath"
    Write-Host "[VERBOSE] CopyImage: VM Base Path: $VMBasePath"

    $imageFilename = "$ImageName.vhdx"

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

    $imagePath = Join-Path -Path $staticImagesPath -ChildPath $imageFilename
    Write-Host "[VERBOSE] CopyImage: Looking for golden image at: $imagePath"
    
    if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
        Write-Host "[ERROR] CopyImage: Golden image not found at: $imagePath"
        throw "Golden image '$ImageName' was not found at $imagePath."
    }
    
    Write-Host "[VERBOSE] CopyImage: Golden image found"

    # Generate unique ID for the VHDX to avoid collisions
    $uniqueId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $uniqueVhdxName = "${ImageName}-${uniqueId}.vhdx"
    Write-Host "[VERBOSE] CopyImage: Generated unique VHDX name: $uniqueVhdxName"

    # Create VM configuration directory in the VMs path
    $vmConfigPath = Join-Path -Path $VMBasePath -ChildPath $VMName
    Write-Host "[VERBOSE] CopyImage: VM config path will be: $vmConfigPath"
    
    if (-not (Test-Path -LiteralPath $vmConfigPath)) {
        Write-Host "[VERBOSE] CopyImage: Creating VM config directory..."
        New-Item -ItemType Directory -Path $vmConfigPath -Force | Out-Null
        Write-Host "[VERBOSE] CopyImage: VM config directory created"
    }
    else {
        Write-Host "[VERBOSE] CopyImage: VM config directory already exists"
    }

    # Copy VHDX to storage path with unique name
    $destinationVhdxPath = Join-Path -Path $StoragePath -ChildPath $uniqueVhdxName
    Write-Host "[VERBOSE] CopyImage: Destination VHDX path: $destinationVhdxPath"

    $imageSize = (Get-Item -LiteralPath $imagePath).Length
    
    # Check if storage path has enough space (basic check)
    $storageDrive = Split-Path -Path $StoragePath -Qualifier
    if ($storageDrive) {
        try {
            $drive = Get-PSDrive -Name $storageDrive.TrimEnd(':') -ErrorAction Stop
            if ($drive.Free -lt $imageSize) {
                throw "Insufficient free space on $storageDrive to clone image '$ImageName'."
            }
        }
        catch {
            Write-Warning "Unable to verify free space on $storageDrive : $_"
        }
    }

    # Ensure storage path exists
    if (-not (Test-Path -LiteralPath $StoragePath)) {
        New-Item -ItemType Directory -Path $StoragePath -Force | Out-Null
    }

    try {
        Copy-Item -Path $imagePath -Destination $destinationVhdxPath -Force -ErrorAction Stop
    }
    catch {
        throw "Failed to copy golden image '$ImageName' to ${destinationVhdxPath}: $_"
    }

    # Return object with both paths
    return [PSCustomObject]@{
        VMConfigPath = $vmConfigPath
        VhdxPath = $destinationVhdxPath
    }
}
