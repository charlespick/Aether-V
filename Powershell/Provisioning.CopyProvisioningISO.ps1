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

    function Test-ProvisioningFileExistsAndNonZero {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$Description
        )

        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "$Description was expected at '$Path' but was not found."
        }

        $fileInfo = Get-Item -LiteralPath $Path
        if ($fileInfo.Length -le 0) {
            throw "$Description at '$Path' is zero bytes."
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
            throw "Failed to copy provisioning ISO from $SourcePath to ${DestinationFolder}: $_"
        }

        Test-ProvisioningFileExistsAndNonZero -Path $destinationPath -Description "Copied provisioning ISO"
    }

    Invoke-ValidateFolder -Path $VMDataFolder

    $scriptDirectory = $PSScriptRoot
    $linuxIsoPath = Join-Path -Path $scriptDirectory -ChildPath "LinuxProvisioning.iso"
    $windowsIsoPath = Join-Path -Path $scriptDirectory -ChildPath "WindowsProvisioning.iso"

    switch ($OSFamily.ToLowerInvariant()) {
        "linux" {
            Test-ProvisioningFileExistsAndNonZero -Path $linuxIsoPath -Description "Linux provisioning ISO"
            Invoke-CopyIso -SourcePath $linuxIsoPath -DestinationFolder $VMDataFolder
        }
        "windows" {
            Test-ProvisioningFileExistsAndNonZero -Path $windowsIsoPath -Description "Windows provisioning ISO"
            Invoke-CopyIso -SourcePath $windowsIsoPath -DestinationFolder $VMDataFolder
        }
        default {
            throw "Unsupported OS family '$OSFamily' provided to Invoke-ProvisioningCopyProvisioningIso."
        }
    }
}
