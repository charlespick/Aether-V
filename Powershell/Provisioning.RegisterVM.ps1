function Invoke-ProvisioningRegisterVm {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [Parameter(Mandatory = $true)]
        [string]$OSFamily,

        [Parameter(Mandatory = $true)]
        [int]$GBRam,

        [Parameter(Mandatory = $true)]
        [int]$CPUcores,

        [Parameter(Mandatory = $true)]
        [string]$VMDataFolder,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$VhdxPath,

        [Parameter(Mandatory = $true)]
        [string]$IsoPath,

        [Parameter()]
        [string]$VirtualSwitch,

        [Nullable[int]]$VLANId
    )

    # VMDataFolder is now the base path where all VMs are created
    # Hyper-V will automatically create VM-specific subdirectories
    
    # Ensure the VM base path exists - create it if it doesn't
    if (-not (Test-Path -LiteralPath $VMDataFolder -PathType Container)) {
        try {
            # Use .NET method to handle paths with spaces correctly
            $null = [System.IO.Directory]::CreateDirectory($VMDataFolder)
            Write-Host "Created VM base path: $VMDataFolder" -ForegroundColor Green
        }
        catch {
            throw "Failed to create VM base path '$VMDataFolder': $_"
        }
    }

    try {
        $vm = New-VM -Name $VMName -MemoryStartupBytes ($GBRam * 1GB) -Generation 2 -BootDevice VHD -Path $VMDataFolder
    }
    catch {
        throw "Failed to create VM '$VMName': $_"
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

    # Attach boot disk if provided (in split component model, disk is attached separately)
    if (-not [string]::IsNullOrWhiteSpace($VhdxPath)) {
        if (-not (Test-Path -LiteralPath $VhdxPath -PathType Leaf)) {
            throw "VHDX not found at '$VhdxPath' for VM '$vmName'."
        }

        try {
            Add-VMHardDiskDrive -VM $vm -Path $VhdxPath
        }
        catch {
            throw "Failed to attach VHDX '$VhdxPath' to VM '$vmName': $_"
        }
    }

    # Use specified virtual switch or fallback to first available
    $networkSwitch = $null
    if (-not [string]::IsNullOrWhiteSpace($VirtualSwitch)) {
        $networkSwitch = Get-VMSwitch -Name $VirtualSwitch -ErrorAction SilentlyContinue
        if (-not $networkSwitch) {
            throw "Virtual switch '$VirtualSwitch' not found on this host."
        }
    }
    else {
        $networkSwitch = Get-VMSwitch | Select-Object -First 1
        if (-not $networkSwitch) {
            throw "No virtual switch is available to attach VM '$vmName'."
        }
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

    # Mount the provisioning ISO from the storage path
    if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) {
        throw "Provisioning ISO not found at '$IsoPath'."
    }

    try {
        Add-VMDvdDrive -VM $vm -Path $IsoPath
        Write-Host "Mounted provisioning ISO: $IsoPath" -ForegroundColor Green
    }
    catch {
        throw "Failed to mount provisioning ISO '$IsoPath' to VM '$vmName': $_"
    }

    # Set boot order to boot from the first hard disk (if one is attached)
    # In split component model, disk may be attached later, so this is optional
    $bootDisk = Get-VMHardDiskDrive -VM $vm | Select-Object -First 1
    if ($bootDisk) {
        try {
            Set-VMFirmware -VM $vm -FirstBootDevice $bootDisk
        }
        catch {
            throw "Failed to set boot order for VM '$vmName': $_"
        }
    }

    # Note: In split component model, VM is created but NOT started
    # The initialization job will start the VM after disk and NIC are attached
    Write-Host "VM '$vmName' created successfully (not started - will be started during initialization)" -ForegroundColor Green

    return $vm
}
