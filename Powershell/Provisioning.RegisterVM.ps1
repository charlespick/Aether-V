function Invoke-ProvisioningRegisterVm {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$OSFamily,

        [Parameter(Mandatory = $true)]
        [int]$GBRam,

        [Parameter(Mandatory = $true)]
        [int]$CPUcores,

        [Parameter(Mandatory = $true)]
        [string]$VMDataFolder,

        [Nullable[int]]$VLANId
    )

    $vmName = Split-Path -Path $VMDataFolder -Leaf
    if (-not $vmName) {
        throw "Unable to derive VM name from data folder '$VMDataFolder'."
    }

    try {
        $vm = New-VM -Name $vmName -MemoryStartupBytes ($GBRam * 1GB) -Generation 2 -BootDevice VHD -Path (Split-Path -Path $VMDataFolder -Parent)
    }
    catch {
        throw "Failed to create VM '$vmName': $_"
    }

    $normalizedFamily = $OSFamily.ToLowerInvariant()
    if ($normalizedFamily -eq "linux") {
        try {
            Set-VMFirmware -VM $vm -SecureBootTemplate "MicrosoftUEFICertificateAuthority"
        }
        catch {
            throw "Failed to set secure boot template for VM '$vmName': $_"
        }
    }

    try {
        Set-VMProcessor -VM $vm -Count $CPUcores
    }
    catch {
        throw "Failed to configure CPU cores for VM '$vmName': $_"
    }

    $vhdxPath = Get-ChildItem -LiteralPath $VMDataFolder -Filter *.vhdx -File | Select-Object -First 1
    if (-not $vhdxPath) {
        throw "No VHDX found in $VMDataFolder for VM '$vmName'."
    }

    try {
        Add-VMHardDiskDrive -VM $vm -Path $vhdxPath.FullName
    }
    catch {
        throw "Failed to attach VHDX '$($vhdxPath.FullName)' to VM '$vmName': $_"
    }

    $networkSwitch = Get-VMSwitch | Select-Object -First 1
    if (-not $networkSwitch) {
        throw "No virtual switch is available to attach VM '$vmName'."
    }

    $adapter = Get-VMNetworkAdapter -VM $vm | Select-Object -First 1
    if (-not $adapter) {
        throw "No network adapter found on VM '$vmName'."
    }

    try {
        Connect-VMNetworkAdapter -VMNetworkAdapter $adapter -VMSwitch $networkSwitch
    }
    catch {
        throw "Failed to connect VM '$vmName' to switch '$($networkSwitch.Name)': $_"
    }

    if ($VLANId -ne $null) {
        try {
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $adapter -Access -VlanId $VLANId
        }
        catch {
            throw "Failed to assign VLAN $VLANId to VM '$vmName': $_"
        }
    }

    $isoFile = Get-ChildItem -LiteralPath $VMDataFolder -Filter *.iso -File | Select-Object -First 1
    if ($isoFile) {
        try {
            Add-VMDvdDrive -VM $vm -Path $isoFile.FullName
        }
        catch {
            throw "Failed to mount provisioning ISO '$($isoFile.FullName)' to VM '$vmName': $_"
        }
    }

    try {
        Set-VMFirmware -VM $vm -FirstBootDevice (Get-VMHardDiskDrive -VM $vm | Select-Object -First 1)
    }
    catch {
        throw "Failed to set boot order for VM '$vmName': $_"
    }

    try {
        Start-VM -VM $vm | Out-Null
    }
    catch {
        throw "Failed to start VM '$vmName': $_"
    }

    return $vm
}
