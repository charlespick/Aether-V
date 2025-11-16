param(
    [Parameter(Mandatory = $false)]
    [string]$ComputerName = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'

$result = @{
    Host = @{
        ComputerName = $ComputerName
        Timestamp    = (Get-Date).ToUniversalTime().ToString('o')
        ClusterName  = $null
        Warnings     = @()
    }
    VirtualMachines = @()
    Warnings        = @()
}

try {
    try {
        $clusterNode = Get-ClusterNode -Name $ComputerName -ErrorAction Stop
        if ($clusterNode -and $clusterNode.Cluster) {
            $result.Host.ClusterName = $clusterNode.Cluster.Name
        }
    } catch {
        $result.Host.Warnings += "Cluster lookup failed: $($_.Exception.Message)"
    }

    try {
        $processorInfo = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop
        $totalCpu = ($processorInfo | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        if (-not $totalCpu) {
            $totalCpu = ($processorInfo | Measure-Object -Property NumberOfCores -Sum).Sum
        }
        $result.Host.TotalCpuCores = [int]$totalCpu
    } catch {
        $result.Host.Warnings += "CPU inventory failed: $($_.Exception.Message)"
    }

    try {
        $systemInfo = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        $result.Host.TotalMemoryGB = [math]::Round(($systemInfo.TotalPhysicalMemory / 1GB), 2)
    } catch {
        $result.Host.Warnings += "Memory inventory failed: $($_.Exception.Message)"
    }

    $vmDetails = @()
    $vmList = Get-VM

    foreach ($vm in $vmList) {
        $creationTime = $null
        if ($vm.CreationTime) {
            $creationTime = $vm.CreationTime.ToUniversalTime().ToString('o')
        }

        $memoryGb = 0
        if ($vm.MemoryAssigned) {
            $memoryGb = [math]::Round(($vm.MemoryAssigned / 1GB), 2)
        }

        $vmInfo = [ordered]@{
            Name            = $vm.Name
            State           = $vm.State.ToString()
            ProcessorCount  = $vm.ProcessorCount
            MemoryGB        = $memoryGb
            CreationTime    = $creationTime
            Generation      = $vm.Generation
            Version         = $vm.Version
            Notes           = $vm.Notes
        }

        $osName = $null
        try {
            $guestInfo = Get-VMGuest -VM $vm -ErrorAction Stop
            if ($guestInfo -and $guestInfo.OSName) {
                $osName = $guestInfo.OSName
            }
        } catch {
            # Guest information may be unavailable; ignore errors
        }

        if (-not $osName -and $vm.OperatingSystem) {
            $osName = $vm.OperatingSystem.ToString()
        }

        if ($osName) {
            $vmInfo.OperatingSystem = $osName
        }

        $networks = @()
        try {
            $adapters = Get-VMNetworkAdapter -VM $vm -ErrorAction Stop
            foreach ($adapter in $adapters) {
                $adapterIps = @()
                if ($adapter.IPAddresses) {
                    $adapterIps = $adapter.IPAddresses | Where-Object { $_ -and ($_ -notmatch '^fe80') }
                }

                $vlanId = $null
                try {
                    $vlanSetting = Get-VMNetworkAdapterVlan -VMNetworkAdapter $adapter -ErrorAction Stop
                    if ($vlanSetting.AccessVlanId) {
                        $vlanId = $vlanSetting.AccessVlanId
                    }
                } catch {
                    # VLAN configuration may not be set
                }

                $networks += @{
                    Name          = $adapter.Name
                    AdapterName   = $adapter.Name
                    Network       = $adapter.SwitchName
                    VirtualSwitch = $adapter.SwitchName
                    Vlan          = $vlanId
                    IPAddresses   = $adapterIps
                    MacAddress    = $adapter.MacAddress
                }
            }
        } catch {
            $result.Warnings += "Network adapter query failed for VM $($vm.Name): $($_.Exception.Message)"
        }

        if ($networks.Count -gt 0) {
            $vmInfo.Networks = $networks
            $vmInfo.IPAddresses = $networks.IPAddresses | Where-Object { $_ } | Select-Object -Unique
        }

        $disks = @()
        try {
            $vmDisks = Get-VMHardDiskDrive -VM $vm -ErrorAction Stop
            foreach ($disk in $vmDisks) {
                $diskInfo = @{
                    Name     = if ($disk.Path) { Split-Path -Path $disk.Path -Leaf } else { $disk.ControllerLocation }
                    Path     = $disk.Path
                    Location = $disk.Path
                    DiskType = $disk.VhdType
                }

                try {
                    $vhd = Get-VHD -Path $disk.Path -ErrorAction Stop
                    $diskInfo.CapacityGB = [math]::Round(($vhd.Size / 1GB), 2)
                    $diskInfo.FileSizeGB = [math]::Round(($vhd.FileSize / 1GB), 2)
                    $diskInfo.DiskType = $vhd.VhdType.ToString()
                } catch {
                    # Access to the VHD may fail; continue without size details
                }

                $disks += $diskInfo
            }
        } catch {
            $result.Warnings += "Disk query failed for VM $($vm.Name): $($_.Exception.Message)"
        }

        if ($disks.Count -gt 0) {
            $vmInfo.Disks = $disks
        }

        $vmDetails += $vmInfo
    }

    $result.VirtualMachines = $vmDetails
} catch {
    $result.Host.Error = $_.Exception.Message
    $result.Host.ExceptionType = $_.Exception.GetType().FullName
    $result.Host.ScriptStackTrace = $_.ScriptStackTrace
    $result | ConvertTo-Json -Depth 8
    exit 1
}

$result | ConvertTo-Json -Depth 8
