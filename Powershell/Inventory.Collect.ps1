param(
    [Parameter(Mandatory = $false)]
    [string]$ComputerName = $env:COMPUTERNAME,

    [Parameter(Mandatory = $false)]
    [int]$MaxConcurrentJobs = [Math]::Max([Environment]::ProcessorCount, 4)
)

$ErrorActionPreference = 'Stop'

function Get-VMOperatingSystem {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ComputerName,

        [Parameter(Mandatory = $true)]
        [string]$VMName
    )

    $session = $null

    try {
        $sessionOptions = New-CimSessionOption -Protocol WSMan -Culture 'en-US' -UICulture 'en-US'
        $session = New-CimSession -ComputerName $ComputerName -Authentication Kerberos -SessionOption $sessionOptions -ErrorAction Stop
    } catch {
        Write-Warning "Failed to establish delegated CIM session to ${ComputerName}: $($_.Exception.Message)"
    }

    try {
        $vm = if ($session) {
            Get-CimInstance -CimSession $session -Namespace root\virtualization\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'" -ErrorAction Stop
        } else {
            Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'" -ErrorAction Stop
        }

        $info = Get-CimAssociatedInstance -InputObject $vm
        $osName = $info | Where-Object GuestOperatingSystem | Select-Object -First 1 -ExpandProperty GuestOperatingSystem
        return $osName
    }
    catch {
        Write-Warning "Could not retrieve OS information for $VMName on $ComputerName. Error: $_"
        return $null
    }
    finally {
        if ($session) {
            try {
                Remove-CimSession -CimSession $session -ErrorAction SilentlyContinue
            } catch {
                # Ignore cleanup failures
            }
        }
    }
}

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

    $MaxConcurrentJobs = [Math]::Max($MaxConcurrentJobs, 1)
    $vmJobs = @()

    $jobScript = {
        param(
            [string]$VmName,
            [string]$TargetComputer
        )

        $ErrorActionPreference = 'Stop'
        $vmWarnings = @()

        function Get-VMOperatingSystem {
            param (
                [Parameter(Mandatory = $true)]
                [string]$ComputerName,

                [Parameter(Mandatory = $true)]
                [string]$VMName
            )

            $session = $null

            try {
                $sessionOptions = New-CimSessionOption -Protocol WSMan -Culture 'en-US' -UICulture 'en-US'
                $session = New-CimSession -ComputerName $ComputerName -Authentication Kerberos -SessionOption $sessionOptions -ErrorAction Stop
            } catch {
                Write-Warning "Failed to establish delegated CIM session to ${ComputerName}: $($_.Exception.Message)"
            }

            try {
                $vm = if ($session) {
                    Get-CimInstance -CimSession $session -Namespace root\\virtualization\\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'" -ErrorAction Stop
                } else {
                    Get-CimInstance -Namespace root\\virtualization\\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'" -ErrorAction Stop
                }

                $info = Get-CimAssociatedInstance -InputObject $vm
                $osName = $info | Where-Object GuestOperatingSystem | Select-Object -First 1 -ExpandProperty GuestOperatingSystem
                return $osName
            }
            catch {
                Write-Warning "Could not retrieve OS information for $VMName on $ComputerName. Error: $_"
                return $null
            }
            finally {
                if ($session) {
                    try {
                        Remove-CimSession -CimSession $session -ErrorAction SilentlyContinue
                    } catch {
                        # Ignore cleanup failures
                    }
                }
            }
        }

        try {
            $vm = Get-VM -Name $VmName -ErrorAction Stop
        } catch {
            return [PSCustomObject]@{
                VmName   = $VmName
                VmInfo   = $null
                Warnings = $vmWarnings
                Error    = "VM lookup failed: $($_.Exception.Message)"
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

        $osName = $null
        $osName = Get-VMOperatingSystem -ComputerName $TargetComputer -VMName $vm.Name

        if (-not $osName) {
            try {
                $guestInfo = Get-VMGuest -VM $vm -ErrorAction Stop
                if ($guestInfo -and $guestInfo.OSName) {
                    $osName = $guestInfo.OSName
                }
            } catch {
                # Guest information may be unavailable; ignore errors
            }
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
            $vmWarnings += "Disk query failed for VM $($vm.Name): $($_.Exception.Message)"
        }

        if ($disks.Count -gt 0) {
            $vmInfo.Disks = $disks
        }

        return [PSCustomObject]@{
            VmName   = $vm.Name
            VmInfo   = $vmInfo
            Warnings = $vmWarnings
            Error    = $null
        }
    }

    foreach ($vm in $vmList) {
        $vmJobs += Start-Job -Name "Inventory_$($vm.Name)" -ScriptBlock $jobScript -ArgumentList $vm.Name, $ComputerName

        while (($vmJobs | Where-Object { $_.State -eq 'Running' -or $_.State -eq 'NotStarted' }).Count -ge $MaxConcurrentJobs) {
            Wait-Job -Job $vmJobs -Any -Timeout 5 | Out-Null
        }
    }

    Wait-Job -Job $vmJobs | Out-Null

    foreach ($job in $vmJobs) {
        try {
            $jobResult = Receive-Job -Job $job -ErrorAction Stop
        } catch {
            $result.Warnings += "VM inventory job $($job.Name) failed: $($_.Exception.Message)"
            continue
        } finally {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }

        if (-not $jobResult) {
            $result.Warnings += "VM inventory job $($job.Name) returned no data."
            continue
        }

        if ($jobResult -is [System.Array]) {
            $jobResult = $jobResult | Select-Object -Last 1
        }

        if ($jobResult.Error) {
            $result.Warnings += $jobResult.Error
        }

        if ($jobResult.Warnings) {
            $result.Warnings += $jobResult.Warnings
        }

        if ($jobResult.VmInfo) {
            $vmDetails += $jobResult.VmInfo
        }
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
