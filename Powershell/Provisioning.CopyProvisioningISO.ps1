function Invoke-ProvisioningCopyProvisioningIso {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [ValidateSet("linux", "windows")]
        [string]$OSFamily,

        [Parameter(Mandatory = $true)]
        [string]$VMDataFolder
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
            [string]$DestinationFolder
        )

        try {
            $destinationPath = Join-Path -Path $DestinationFolder -ChildPath (Split-Path -Path $SourcePath -Leaf)
            Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force -ErrorAction Stop
            Write-Host "Copied provisioning ISO to $destinationPath" -ForegroundColor Green
        }
        catch {
            throw "Failed to copy provisioning ISO from $SourcePath to $DestinationFolder: $_"
        }
    }

    Invoke-ValidateFolder -Path $VMDataFolder

    $scriptDirectory = $PSScriptRoot
    $linuxIsoPath = Join-Path -Path $scriptDirectory -ChildPath "LinuxProvisioning.iso"
    $windowsIsoPath = Join-Path -Path $scriptDirectory -ChildPath "WindowsProvisioning.iso"

    switch ($OSFamily.ToLowerInvariant()) {
        "linux" {
            if (-not (Test-Path -LiteralPath $linuxIsoPath -PathType Leaf)) {
                throw "The Linux provisioning ISO file does not exist at '$linuxIsoPath'."
            }
            Invoke-CopyIso -SourcePath $linuxIsoPath -DestinationFolder $VMDataFolder
        }
        "windows" {
            if (-not (Test-Path -LiteralPath $windowsIsoPath -PathType Leaf)) {
                throw "The Windows provisioning ISO file does not exist at '$windowsIsoPath'."
            }
            Invoke-CopyIso -SourcePath $windowsIsoPath -DestinationFolder $VMDataFolder
        }
        default {
            throw "Unsupported OS family '$OSFamily' provided to Invoke-ProvisioningCopyProvisioningIso."
        }
    }
}
