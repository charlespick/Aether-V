function Invoke-ProvisioningCopyImage {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [Parameter(Mandatory = $true)]
        [string]$ImageName
    )

    $imageFilename = "$ImageName.vhdx"

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

    $targetVolume = Get-ClusterSharedVolume |
        Sort-Object { $_.SharedVolumeInfo.Partition.FreeSpace } -Descending |
        Select-Object -First 1

    if (-not $targetVolume) {
        throw "No cluster shared volumes were found on this host."
    }

    $destinationPath = Join-Path -Path (
        Join-Path -Path $targetVolume.SharedVolumeInfo.FriendlyVolumeName -ChildPath "Hyper-V"
    ) -ChildPath $VMName

    $imagePath = Join-Path -Path $staticImagesPath -ChildPath $imageFilename
    if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
        throw "Golden image '$ImageName' was not found at $imagePath."
    }

    $imageSize = (Get-Item -LiteralPath $imagePath).Length
    if ($targetVolume.SharedVolumeInfo.Partition.Freespace -lt $imageSize) {
        throw "Insufficient free space on $($targetVolume.Name) to clone image '$ImageName'."
    }

    try {
        New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
        Copy-Item -Path $imagePath -Destination $destinationPath -Force -ErrorAction Stop
    }
    catch {
        throw "Failed to copy golden image '$ImageName' to ${destinationPath}: $_"
    }

    return $destinationPath
}
