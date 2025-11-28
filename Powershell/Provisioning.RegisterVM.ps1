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
        [string]$VhdxPath
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

    # Remove the default network adapter that PowerShell creates automatically
    # Network adapters will be added via the NIC create operation
    $defaultAdapter = Get-VMNetworkAdapter -VM $vm | Select-Object -First 1
    if ($defaultAdapter) {
        try {
            Remove-VMNetworkAdapter -VMNetworkAdapter $defaultAdapter -ErrorAction Stop
            Write-Host "Removed default network adapter (will be added via NIC create operation)" -ForegroundColor Green
        }
        catch {
            Write-Warning "Failed to remove default network adapter: $_"
        }
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
    # Network adapters and provisioning ISO are added during the initialization phase
    Write-Host "VM '$vmName' created successfully (not started - will be started during initialization)" -ForegroundColor Green

    return $vm
}
