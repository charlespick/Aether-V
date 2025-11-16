function Invoke-ProvisioningCopyProvisioningIso {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [ValidateSet("linux", "windows")]
        [string]$OSFamily,

        [Parameter(Mandatory = $true)]
        [string]$StoragePath,

        [Parameter(Mandatory = $true)]
        [string]$VMName
    )

    function Invoke-ValidateFolder {
        param([string]$Path)
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            throw "The folder '$Path' does not exist."
        }
    }

    function Invoke-CopyIso {
        param(
            [string]$SourcePath,
            [string]$DestinationFolder,
            [string]$UniqueFileName
        )

        try {
            $destinationPath = Join-Path -Path $DestinationFolder -ChildPath $UniqueFileName
            Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force -ErrorAction Stop
            Write-Host "Copied provisioning ISO to $destinationPath" -ForegroundColor Green
            return $destinationPath
        }
        catch {
            throw "Failed to copy provisioning ISO from $SourcePath to ${DestinationFolder}: $_"
        }
    }

    Invoke-ValidateFolder -Path $StoragePath

    # Ensure storage path exists
    if (-not (Test-Path -LiteralPath $StoragePath)) {
        New-Item -ItemType Directory -Path $StoragePath -Force | Out-Null
    }

    # Generate unique ID for the ISO to avoid collisions
    $uniqueId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    
    $scriptDirectory = $PSScriptRoot
    $linuxIsoPath = Join-Path -Path $scriptDirectory -ChildPath "LinuxProvisioning.iso"
    $windowsIsoPath = Join-Path -Path $scriptDirectory -ChildPath "WindowsProvisioning.iso"

    switch ($OSFamily.ToLowerInvariant()) {
        "linux" {
            if (-not (Test-Path -LiteralPath $linuxIsoPath -PathType Leaf)) {
                throw "The Linux provisioning ISO file does not exist at '$linuxIsoPath'."
            }
            $uniqueIsoName = "LinuxProvisioning-${VMName}-${uniqueId}.iso"
            $isoPath = Invoke-CopyIso -SourcePath $linuxIsoPath -DestinationFolder $StoragePath -UniqueFileName $uniqueIsoName
            return $isoPath
        }
        "windows" {
            if (-not (Test-Path -LiteralPath $windowsIsoPath -PathType Leaf)) {
                throw "The Windows provisioning ISO file does not exist at '$windowsIsoPath'."
            }
            $uniqueIsoName = "WindowsProvisioning-${VMName}-${uniqueId}.iso"
            $isoPath = Invoke-CopyIso -SourcePath $windowsIsoPath -DestinationFolder $StoragePath -UniqueFileName $uniqueIsoName
            return $isoPath
        }
        default {
            throw "Unsupported OS family '$OSFamily' provided to Invoke-ProvisioningCopyProvisioningIso."
        }
    }
}
