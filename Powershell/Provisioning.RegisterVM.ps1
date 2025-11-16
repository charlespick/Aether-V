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

        [Parameter(Mandatory = $true)]
        [string]$VhdxPath,

        [Parameter()]
        [string]$VirtualSwitch,

        [Nullable[int]]$VLANId
    )

    Write-Host "[VERBOSE] RegisterVM: VM Name: $VMName"
    Write-Host "[VERBOSE] RegisterVM: VM Data Folder (base path): $VMDataFolder"
    
    # VMDataFolder is now the base path where all VMs are created
    # Hyper-V will automatically create VM-specific subdirectories
    Write-Host "[VERBOSE] RegisterVM: Checking if VM base path exists..."
    
    if (-not (Test-Path -LiteralPath $VMDataFolder -PathType Container)) {
        Write-Host "[ERROR] RegisterVM: VM base path does not exist: $VMDataFolder"
        throw "VM base path '$VMDataFolder' does not exist. Cannot create VM."
    }
    
    Write-Host "[VERBOSE] RegisterVM: VM base path exists and is accessible"
    Write-Host "[VERBOSE] RegisterVM: Attempting to create VM with New-VM cmdlet..."
    Write-Host "[VERBOSE] RegisterVM: Parameters:"
    Write-Host "[VERBOSE]   - Name: $VMName"
    Write-Host "[VERBOSE]   - MemoryStartupBytes: $($GBRam * 1GB)"
    Write-Host "[VERBOSE]   - Generation: 2"
    Write-Host "[VERBOSE]   - BootDevice: VHD"
    Write-Host "[VERBOSE]   - Path: $VMDataFolder"

    try {
        $vm = New-VM -Name $VMName -MemoryStartupBytes ($GBRam * 1GB) -Generation 2 -BootDevice VHD -Path $VMDataFolder
        Write-Host "[VERBOSE] RegisterVM: VM created successfully"
    }
    catch {
        Write-Host "[ERROR] RegisterVM: Failed to create VM '$VMName'"
        Write-Host "[ERROR] RegisterVM: Error message: $_"
        Write-Host "[ERROR] RegisterVM: Exception type: $($_.Exception.GetType().FullName)"
        if ($_.Exception.InnerException) {
            Write-Host "[ERROR] RegisterVM: Inner exception: $($_.Exception.InnerException.Message)"
        }
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

    if (-not (Test-Path -LiteralPath $VhdxPath -PathType Leaf)) {
        throw "VHDX not found at '$VhdxPath' for VM '$vmName'."
    }

    try {
        Add-VMHardDiskDrive -VM $vm -Path $VhdxPath
    }
    catch {
        throw "Failed to attach VHDX '$VhdxPath' to VM '$vmName': $_"
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
