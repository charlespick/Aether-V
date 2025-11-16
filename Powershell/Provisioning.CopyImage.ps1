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
    
    if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
        throw "Golden image '$ImageName' was not found at $imagePath."
    }

    # Generate unique ID for the VHDX to avoid collisions
    $uniqueId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $uniqueVhdxName = "${ImageName}-${uniqueId}.vhdx"

    # VMs will be placed directly in the VM base path
    # Hyper-V will automatically create its own subdirectories when needed
    
    # Use -LiteralPath to handle paths with spaces correctly
    $basePathExists = Test-Path -LiteralPath $VMBasePath -PathType Container
    
    if (-not $basePathExists) {
        try {
            # Use .NET method instead of New-Item to avoid PowerShell path parsing issues with spaces
            $createdPath = [System.IO.Directory]::CreateDirectory($VMBasePath)
        }
        catch {
            throw "Failed to create VM base path '$VMBasePath': $_"
        }
    }

    # Copy VHDX to storage path with unique name
    $destinationVhdxPath = Join-Path -Path $StoragePath -ChildPath $uniqueVhdxName

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

    # Return object with VM base path (VMs created directly here) and VHDX path
    return [PSCustomObject]@{
        VMConfigPath = $VMBasePath
        VhdxPath = $destinationVhdxPath
    }
}
