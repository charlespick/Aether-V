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

    if (-not $vm) {
        throw "VM creation for '$vmName' returned no object."
    }

    $vm = Get-VM -Name $vmName -ErrorAction SilentlyContinue
    if (-not $vm) {
        throw "VM '$vmName' was not found immediately after creation."
    }

    $normalizedFamily = $OSFamily.ToLowerInvariant()
    if ($normalizedFamily -eq "linux") {
        try {
            Set-VMFirmware -VM $vm -SecureBootTemplate "MicrosoftUEFICertificateAuthority"
        }
        catch {
            throw "Failed to set secure boot template for VM '$vmName': $_"
        }

        $firmware = Get-VMFirmware -VM $vm
        if ($firmware.SecureBootTemplate -ne "MicrosoftUEFICertificateAuthority") {
            throw "Secure Boot template verification failed for VM '$vmName'. Expected 'MicrosoftUEFICertificateAuthority', found '${($firmware.SecureBootTemplate)}'."
        }
    }

    try {
        Set-VMProcessor -VM $vm -Count $CPUcores
    }
    catch {
        throw "Failed to configure CPU cores for VM '$vmName': $_"
    }

    $processorSettings = Get-VMProcessor -VM $vm
    if ($processorSettings.Count -ne $CPUcores) {
        throw "CPU core verification failed for VM '$vmName'. Expected $CPUcores cores, found $($processorSettings.Count)."
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

    $attachedDisk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Path -eq $vhdxPath.FullName }
    if (-not $attachedDisk) {
        throw "Disk attachment verification failed for VM '$vmName'. '$($vhdxPath.FullName)' is not attached."
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

    $adapter = Get-VMNetworkAdapter -VM $vm | Select-Object -First 1
    if ($adapter.SwitchName -ne $networkSwitch.Name) {
        throw "Network adapter verification failed for VM '$vmName'. Expected switch '$($networkSwitch.Name)', found '${($adapter.SwitchName)}'."
    }

    if ($VLANId -ne $null) {
        try {
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $adapter -Access -VlanId $VLANId
        }
        catch {
            throw "Failed to assign VLAN $VLANId to VM '$vmName': $_"
        }

        $adapterVlan = Get-VMNetworkAdapterVlan -VMNetworkAdapter $adapter
        if ($adapterVlan.AccessVlanId -ne $VLANId) {
            throw "VLAN verification failed for VM '$vmName'. Expected VLAN $VLANId, found $($adapterVlan.AccessVlanId)."
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

        $dvdDrive = Get-VMDvdDrive -VM $vm | Where-Object { $_.Path -eq $isoFile.FullName }
        if (-not $dvdDrive) {
            throw "Provisioning ISO verification failed for VM '$vmName'. '$($isoFile.FullName)' is not mounted."
        }
    }

    try {
        Set-VMFirmware -VM $vm -FirstBootDevice (Get-VMHardDiskDrive -VM $vm | Select-Object -First 1)
    }
    catch {
        throw "Failed to set boot order for VM '$vmName': $_"
    }

    $firmware = Get-VMFirmware -VM $vm
    $firstBootDevice = $firmware.BootOrder | Select-Object -First 1
    if (-not $firstBootDevice -or $firstBootDevice -notlike '*HardDrive*') {
        throw "Boot order verification failed for VM '$vmName'. Expected virtual hard disk as first boot device."
    }

    try {
        Start-VM -VM $vm | Out-Null
    }
    catch {
        throw "Failed to start VM '$vmName': $_"
    }

    Start-Sleep -Seconds 2

    $stateCheckTimeoutSeconds = 120
    $pollIntervalSeconds = 3
    $elapsedSeconds = 0

    while ($elapsedSeconds -le $stateCheckTimeoutSeconds) {
        $currentVm = Get-VM -Name $vmName -ErrorAction SilentlyContinue
        if ($currentVm -and $currentVm.State -eq 'Running') {
            return $currentVm
        }

        Start-Sleep -Seconds $pollIntervalSeconds
        $elapsedSeconds += $pollIntervalSeconds
    }

    $finalVm = Get-VM -Name $vmName -ErrorAction SilentlyContinue
    $finalState = if ($finalVm) { $finalVm.State } else { 'NotFound' }
    throw "VM '$vmName' failed to reach the 'Running' state within $stateCheckTimeoutSeconds seconds after start. Final state: '${finalState}'."
}
