param(
    [Parameter(Mandatory = $false)]
    [string]$ComputerName = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Management.Automation

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

    # Create a shared runspace pool (CIM sessions will be created inside each runspace)
    $maxThreads = [math]::Min([math]::Max([Environment]::ProcessorCount, 2), 16)
    $initial = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()

    $pool = [RunspaceFactory]::CreateRunspacePool(1, $maxThreads, $initial, $Host)
    $pool.ApartmentState = [System.Threading.ApartmentState]::MTA
    $pool.ThreadOptions = 'ReuseThread'
    $pool.Open()

    try {
        $tasks = foreach ($vm in $vmList) {
            $ps = [PowerShell]::Create()
            $ps.RunspacePool = $pool

            $scriptBlock = {
            param(
                [Parameter(Mandatory = $true)]
                [string]$VmName,

                [Parameter(Mandatory = $true)]
                [string]$Computer
            )

            $vmWarnings = @()

            try {
                $vm = Get-VM -Name $VmName -ErrorAction Stop
            } catch {
                return [pscustomobject]@{
                    Info     = $null
                    Warnings = @("VM $VmName could not be loaded: $($_.Exception.Message)")
                }
            }

            $creationTime = $null
            if ($vm.CreationTime) {
                $creationTime = $vm.CreationTime.ToUniversalTime().ToString('o')
            }

            $memoryGb = 0
            $memoryStartupGb = $null
            $memoryMinimumGb = $null
            $memoryMaximumGb = $null
            $dynamicMemoryEnabled = $null

            try {
                $memoryInfo = Get-VMMemory -VM $vm -ErrorAction Stop
                if ($memoryInfo) {
                    if ($memoryInfo.Startup) { $memoryStartupGb = [math]::Round(($memoryInfo.Startup / 1GB), 2) }
                    if ($memoryInfo.Minimum) { $memoryMinimumGb = [math]::Round(($memoryInfo.Minimum / 1GB), 2) }
                    if ($memoryInfo.Maximum) { $memoryMaximumGb = [math]::Round(($memoryInfo.Maximum / 1GB), 2) }
                    $dynamicMemoryEnabled = [bool]$memoryInfo.DynamicMemoryEnabled
                }
            } catch {
                $vmWarnings += "Memory inventory failed for VM $($vm.Name): $($_.Exception.Message)"
            }

            if ($vm.MemoryAssigned) {
                $memoryGb = [math]::Round(($vm.MemoryAssigned / 1GB), 2)
            }
            elseif ($memoryStartupGb -ne $null) {
                $memoryGb = $memoryStartupGb
            }

            $vmInfo = [ordered]@{
                Name                 = $vm.Name
                State                = $vm.State.ToString()
                ProcessorCount       = $vm.ProcessorCount
                MemoryGB             = $memoryGb
                StartupMemoryGB      = $memoryStartupGb
                MinimumMemoryGB      = $memoryMinimumGb
                MaximumMemoryGB      = $memoryMaximumGb
                DynamicMemoryEnabled = $dynamicMemoryEnabled
                CreationTime         = $creationTime
                Generation           = $vm.Generation
                Version              = $vm.Version
                Notes                = $vm.Notes
            }

            # Operating system lookup – NO remote CimSession, just local CIM
            $osName = $null
            try {
                $vmCim = Get-CimInstance -Namespace root\virtualization\v2 `
                                        -ClassName Msvm_ComputerSystem `
                                        -Filter "ElementName='$($vm.Name)'" `
                                        -ErrorAction Stop

                $info = Get-CimAssociatedInstance -InputObject $vmCim
                $osName = $info | Where-Object GuestOperatingSystem |
                        Select-Object -First 1 -ExpandProperty GuestOperatingSystem

                if (-not $osName) {
                    $vmWarnings += "OS lookup returned null/empty for VM $($vm.Name). GuestOperatingSystem property not found via CIM (KVP may not be working)."
                }
            } catch {
                $vmWarnings += "Failed to retrieve operating system for VM $($vm.Name): $($_.Exception.Message)"
            }

            $vmInfo.OperatingSystem = $osName

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
                $vmWarnings += "Network adapter query failed for VM $($vm.Name): $($_.Exception.Message)"
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

                    if ($disk.Path) {
                        try {
                            $vhd = Get-VHD -Path $disk.Path -ErrorAction Stop
                            $diskInfo.CapacityGB = [math]::Round(($vhd.Size / 1GB), 2)
                            $diskInfo.FileSizeGB = [math]::Round(($vhd.FileSize / 1GB), 2)
                            $diskInfo.DiskType = $vhd.VhdType.ToString()
                        } catch {
                            # Access to the VHD may fail; continue without size details
                        }
                    }

                    $disks += $diskInfo
                }
            } catch {
                $vmWarnings += "Disk query failed for VM $($vm.Name): $($_.Exception.Message)"
            }

            if ($disks.Count -gt 0) {
                $vmInfo.Disks = $disks
            }

            return [pscustomobject]@{
                Info     = $vmInfo
                Warnings = $vmWarnings
            }
        }

            $null = $ps.AddScript($scriptBlock).AddParameter('VmName', $vm.Name).AddParameter('Computer', $ComputerName)

            [pscustomobject]@{
                VM     = $vm.Name
                Handle = $ps.BeginInvoke()
                Pipe   = $ps
            }
        }

        $vmWarnings = @()
        foreach ($task in $tasks) {
            $taskResults = $task.Pipe.EndInvoke($task.Handle)
            $task.Pipe.Dispose()

            foreach ($taskResult in $taskResults) {
                if ($taskResult.Info) {
                    $vmDetails += $taskResult.Info
                }

                if ($taskResult.Warnings) {
                    $vmWarnings += $taskResult.Warnings
                }
            }
        }

        $result.VirtualMachines = $vmDetails
        $result.Warnings += $vmWarnings
    }
    finally {
        # Clean up the shared runspace pool
        if ($pool) {
            try { $pool.Close() } catch { }
            try { $pool.Dispose() } catch { }
        }
    }
} catch {
    $result.Host.Error = $_.Exception.Message
    $result.Host.ExceptionType = $_.Exception.GetType().FullName
    $result.Host.ScriptStackTrace = $_.ScriptStackTrace
    $result | ConvertTo-Json -Depth 8
    exit 1
}

$result | ConvertTo-Json -Depth 8
