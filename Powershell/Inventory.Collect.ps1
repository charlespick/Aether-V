param(
    [Parameter(Mandatory = $false)]
    [string]$ComputerName = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'

$result = @{
    Host            = @{
        ComputerName = $ComputerName
        Timestamp    = (Get-Date).ToUniversalTime().ToString('o')
        ClusterName  = $null
        Warnings     = @()
    }
    VirtualMachines = @()
    Warnings        = @()
}

try {
    # Host-level information
    try {
        $clusterNode = Get-ClusterNode -Name $ComputerName -ErrorAction Stop
        if ($clusterNode -and $clusterNode.Cluster) {
            $result.Host.ClusterName = $clusterNode.Cluster.Name
        }
    }
    catch {
        $result.Host.Warnings += "Cluster lookup failed: $($_.Exception.Message)"
    }

    try {
        # Select only required properties to speed up query
        $processorInfo = Get-CimInstance -ClassName Win32_Processor -Property NumberOfLogicalProcessors, NumberOfCores -ErrorAction Stop
        $totalCpu = ($processorInfo | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        if (-not $totalCpu) {
            $totalCpu = ($processorInfo | Measure-Object -Property NumberOfCores -Sum).Sum
        }
        $result.Host.TotalCpuCores = [int]$totalCpu
    }
    catch {
        $result.Host.Warnings += "CPU inventory failed: $($_.Exception.Message)"
    }

    try {
        $systemInfo = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        $result.Host.TotalMemoryGB = [math]::Round(($systemInfo.TotalPhysicalMemory / 1GB), 2)
    }
    catch {
        $result.Host.Warnings += "Memory inventory failed: $($_.Exception.Message)"
    }

    # === BATCH FETCH ALL VM DATA VIA CIM (bypasses slow Get-VM cmdlet) ===
    
    # Get VM basic info (GUID, Name, State)
    $vmDataByGuid = @{}
    $vmGuidToName = @{}
    try {
        $vmSystems = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_ComputerSystem `
            -Filter "Caption='Virtual Machine'" `
            -ErrorAction SilentlyContinue
        foreach ($vm in $vmSystems) {
            $vmGuid = $vm.Name.ToUpper()
            $vmName = $vm.ElementName
            $vmGuidToName[$vmGuid] = $vmName
                
            # Map EnabledState to PowerShell VM state names
            $stateMap = @{
                2     = 'Running'
                3     = 'Off'
                6     = 'Saved'
                9     = 'Paused'
                10    = 'Starting'
                32768 = 'Pausing'
                32769 = 'Resuming'
                32770 = 'Saving'
                32773 = 'Starting'
                32774 = 'Stopping'
                32776 = 'Saving'
                32777 = 'Stopping'
            }
            $state = if ($stateMap.ContainsKey([int]$vm.EnabledState)) { 
                $stateMap[[int]$vm.EnabledState] 
            }
            else { 
                'Unknown' 
            }
                
            $vmDataByGuid[$vmGuid] = @{
                Id    = [Guid]$vmGuid
                Name  = $vmName
                State = $state
            }
        }
    }
    catch {
        $result.Warnings += "CIM VM query failed: $($_.Exception.Message)"
    }

    if ($vmDataByGuid.Count -eq 0) {
        $result.VirtualMachines = @()
        $result | ConvertTo-Json -Depth 8
        exit 0
    }

    # Get VM settings (CreationTime, Notes, Version, Generation)
    try {
        $vsSettings = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_VirtualSystemSettingData `
            -ErrorAction SilentlyContinue |
        Where-Object { $_.VirtualSystemType -eq 'Microsoft:Hyper-V:System:Realized' }
            
        foreach ($vs in $vsSettings) {
            $vmGuid = $vs.VirtualSystemIdentifier.ToUpper()
            if ($vmDataByGuid.ContainsKey($vmGuid)) {
                # Generation: SubType:1 = Gen1, SubType:2 = Gen2
                $generation = if ($vs.VirtualSystemSubType -match 'SubType:(\d+)') { [int]$Matches[1] } else { 1 }
                    
                # Notes is an array in CIM, join to plain string for schema compatibility
                $notes = if ($vs.Notes -is [array]) { $vs.Notes -join "`n" } else { $vs.Notes }
                    
                $vmDataByGuid[$vmGuid].CreationTime = $vs.CreationTime
                $vmDataByGuid[$vmGuid].Notes = $notes
                $vmDataByGuid[$vmGuid].Version = $vs.Version
                $vmDataByGuid[$vmGuid].Generation = $generation
            }
        }
    }
    catch {
        $result.Warnings += "CIM VS settings query failed: $($_.Exception.Message)"
    }

    # Get memory settings
    try {
        $memSettings = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_MemorySettingData `
            -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceID -notlike '*Definition*' }
            
        foreach ($mem in $memSettings) {
            # InstanceID format: Microsoft:{VM_GUID}\...
            if ($mem.InstanceID -match 'Microsoft:([A-F0-9-]+)\\') {
                $vmGuid = $Matches[1].ToUpper()
                if ($vmDataByGuid.ContainsKey($vmGuid)) {
                    # Values are in MB, convert to bytes for compatibility
                    $vmDataByGuid[$vmGuid].MemoryStartup = $mem.VirtualQuantity * 1MB
                    $vmDataByGuid[$vmGuid].MemoryMinimum = $mem.Reservation * 1MB
                    $vmDataByGuid[$vmGuid].MemoryMaximum = $mem.Limit * 1MB
                    $vmDataByGuid[$vmGuid].DynamicMemoryEnabled = $mem.DynamicMemoryEnabled
                }
            }
        }
    }
    catch {
        $result.Warnings += "CIM memory settings query failed: $($_.Exception.Message)"
    }

    # Get current memory allocation for running VMs (MemoryAssigned equivalent)
    try {
        $memoryItems = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_Memory `
            -ErrorAction SilentlyContinue |
        Where-Object { $_.SystemName -ne $env:COMPUTERNAME }
            
        foreach ($mem in $memoryItems) {
            $vmGuid = $mem.SystemName.ToUpper()
            if ($vmDataByGuid.ContainsKey($vmGuid)) {
                # NumberOfBlocks is the current memory in MB
                if ($mem.NumberOfBlocks) {
                    $vmDataByGuid[$vmGuid].MemoryAssigned = $mem.NumberOfBlocks * 1MB
                }
            }
        }
    }
    catch {
        $result.Warnings += "CIM memory query failed: $($_.Exception.Message)"
    }

    # Get processor settings
    try {
        $procSettings = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_ProcessorSettingData `
            -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceID -notlike '*Definition*' }
            
        foreach ($proc in $procSettings) {
            # InstanceID format: Microsoft:{VM_GUID}\...
            if ($proc.InstanceID -match 'Microsoft:([A-F0-9-]+)\\') {
                $vmGuid = $Matches[1].ToUpper()
                if ($vmDataByGuid.ContainsKey($vmGuid)) {
                    $vmDataByGuid[$vmGuid].ProcessorCount = $proc.VirtualQuantity
                }
            }
        }
    }
    catch {
        $result.Warnings += "CIM processor settings query failed: $($_.Exception.Message)"
    }

    # Build vmDataByName for merge phase
    $vmDataByName = @{}
    foreach ($vmGuid in $vmDataByGuid.Keys) {
        $vmData = $vmDataByGuid[$vmGuid]
        $vmDataByName[$vmData.Name] = $vmData
    }

    # Batch: Network adapters via CIM (bypasses slow Get-VMNetworkAdapter cmdlet)
    $adaptersByVm = @{}
    $allAdapterIds = [System.Collections.Generic.List[string]]::new()
    $adapterSettingsByVmGuid = @{}
    
    # Batch: Get all synthetic ethernet port settings (contains adapter name, MAC, etc.)
    try {
        $syntheticPorts = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_SyntheticEthernetPortSettingData `
            -ErrorAction SilentlyContinue
        foreach ($port in $syntheticPorts) {
            # InstanceID format: Microsoft:{VM_GUID}\{ADAPTER_GUID}\...
            if ($port.InstanceID -match 'Microsoft:([A-F0-9-]+)\\([A-F0-9-]+)') {
                $vmGuid = $Matches[1].ToUpper()
                $adapterGuid = $Matches[2].ToUpper()
                $psAdapterId = "Microsoft:$vmGuid\$adapterGuid"
                    
                if (-not $adapterSettingsByVmGuid.ContainsKey($vmGuid)) {
                    $adapterSettingsByVmGuid[$vmGuid] = [System.Collections.Generic.List[object]]::new()
                }
                $adapterSettingsByVmGuid[$vmGuid].Add(@{
                        Id          = $psAdapterId
                        AdapterGuid = $adapterGuid
                        VmGuid      = $vmGuid
                        Name        = $port.ElementName
                        MacAddress  = $port.Address
                        StaticMac   = $port.StaticMacAddress
                    })
                $allAdapterIds.Add($psAdapterId)
            }
        }
    }
    catch {
        $result.Warnings += "CIM synthetic port query failed: $($_.Exception.Message)"
    }
    
    # Batch: Get ethernet port allocation settings (contains switch connection info)
    $switchByAdapterId = @{}
    try {
        $portAllocations = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_EthernetPortAllocationSettingData `
            -ErrorAction SilentlyContinue
        # Also get switch names
        $switches = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_VirtualEthernetSwitch `
            -ErrorAction SilentlyContinue
        $switchNameByPath = @{}
        foreach ($sw in $switches) {
            # Build a lookup by the WMI path pattern
            $switchNameByPath[$sw.Name] = $sw.ElementName
        }
            
        foreach ($alloc in $portAllocations) {
            # InstanceID format: Microsoft:{VM_GUID}\{ADAPTER_GUID}\C
            if ($alloc.InstanceID -match 'Microsoft:([A-F0-9-]+)\\([A-F0-9-]+)\\') {
                $vmGuid = $Matches[1].ToUpper()
                $adapterGuid = $Matches[2].ToUpper()
                $psAdapterId = "Microsoft:$vmGuid\$adapterGuid"
                    
                # Extract switch name from HostResource
                $switchName = $null
                if ($alloc.HostResource) {
                    foreach ($hr in $alloc.HostResource) {
                        if ($hr -match 'Name="([A-F0-9-]+)"') {
                            $switchGuid = $Matches[1]
                            if ($switchNameByPath.ContainsKey($switchGuid)) {
                                $switchName = $switchNameByPath[$switchGuid]
                            }
                        }
                    }
                }
                $switchByAdapterId[$psAdapterId] = $switchName
            }
        }
    }
    catch {
        $result.Warnings += "CIM ethernet allocation query failed: $($_.Exception.Message)"
    }
    
    # Batch: IP addresses via CIM (much faster than accessing IPAddresses property on each adapter)
    $ipsByAdapterId = @{}
    try {
        $guestNetConfigs = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_GuestNetworkAdapterConfiguration `
            -ErrorAction SilentlyContinue
        foreach ($config in $guestNetConfigs) {
            # InstanceID format: Microsoft:GuestNetwork\{VM_GUID}\{ADAPTER_GUID}
            # PowerShell ID format: Microsoft:{VM_GUID}\{ADAPTER_GUID}
            if ($config.InstanceID -match 'Microsoft:GuestNetwork\\([^\\]+)\\(.+)$') {
                $vmGuid = $Matches[1].ToUpper()
                $adapterGuid = $Matches[2].ToUpper()
                $psAdapterId = "Microsoft:$vmGuid\$adapterGuid"
                if ($config.IPAddresses) {
                    $ipsByAdapterId[$psAdapterId] = @($config.IPAddresses)
                }
            }
        }
    }
    catch {
        $result.Warnings += "Batch IP address query failed: $($_.Exception.Message)"
    }
    
    # Build final adapter index by VM name
    foreach ($vmGuid in $adapterSettingsByVmGuid.Keys) {
        $vmName = $vmGuidToName[$vmGuid]
        if (-not $vmName) { continue }
            
        foreach ($adapterSetting in $adapterSettingsByVmGuid[$vmGuid]) {
            $adapterId = $adapterSetting.Id
            $adapterIps = if ($ipsByAdapterId.ContainsKey($adapterId)) { $ipsByAdapterId[$adapterId] } else { @() }
            $switchName = $switchByAdapterId[$adapterId]
                
            $adapterData = @{
                Id          = $adapterId
                VMName      = $vmName
                Name        = $adapterSetting.Name
                SwitchName  = $switchName
                MacAddress  = $adapterSetting.MacAddress
                IPAddresses = $adapterIps
            }
                
            if (-not $adaptersByVm.ContainsKey($vmName)) {
                $adaptersByVm[$vmName] = [System.Collections.Generic.List[object]]::new()
            }
            $adaptersByVm[$vmName].Add($adapterData)
        }
    }

    # Batch: VLAN settings via CIM
    $vlanById = @{}
    try {
        $vlanSettings = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_EthernetSwitchPortVlanSettingData `
            -ErrorAction SilentlyContinue
        foreach ($vlan in $vlanSettings) {
            # InstanceID format: Microsoft:{VM_GUID}\{ADAPTER_GUID}\...
            if ($vlan.InstanceID -match 'Microsoft:([A-F0-9-]+)\\([A-F0-9-]+)\\') {
                $vmGuid = $Matches[1].ToUpper()
                $adapterGuid = $Matches[2].ToUpper()
                $psAdapterId = "Microsoft:$vmGuid\$adapterGuid"
                if ($vlan.AccessVlanId) {
                    $vlanById[$psAdapterId] = $vlan.AccessVlanId
                }
            }
        }
    }
    catch {
        $result.Warnings += "CIM VLAN query failed: $($_.Exception.Message)"
    }

    # Batch: Hard disk drives via CIM (bypasses slow Get-VMHardDiskDrive cmdlet)
    $disksByVm = @{}
    $allDiskPaths = [System.Collections.Generic.List[string]]::new()
    try {
        $storageAllocs = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_StorageAllocationSettingData `
            -ErrorAction SilentlyContinue
            
        foreach ($alloc in $storageAllocs) {
            # Filter for VHDs (not Definition templates) with actual paths
            if ($alloc.ResourceSubType -eq 'Microsoft:Hyper-V:Virtual Hard Disk' -and
                $alloc.InstanceID -notlike '*Definition*' -and
                $alloc.HostResource) {
                    
                # Extract VM GUID from InstanceID: Microsoft:{VM_GUID}\...
                if ($alloc.InstanceID -match 'Microsoft:([A-F0-9-]+)\\') {
                    $vmGuid = $Matches[1].ToUpper()
                    $vmName = $vmGuidToName[$vmGuid]
                    if (-not $vmName) { continue }
                        
                    $vhdPath = $alloc.HostResource[0]
                    if ($vhdPath) {
                        # Convert \L suffix to \D for schema compatibility with Get-VMHardDiskDrive
                        # CIM uses \L (Logical disk), PS cmdlet uses \D (Drive)
                        $diskId = $alloc.InstanceID -replace '\\L$', '\D'
                            
                        $diskData = @{
                            Id     = $diskId
                            Path   = $vhdPath
                            VMName = $vmName
                        }
                            
                        if (-not $disksByVm.ContainsKey($vmName)) {
                            $disksByVm[$vmName] = [System.Collections.Generic.List[object]]::new()
                        }
                        $disksByVm[$vmName].Add($diskData)
                        $allDiskPaths.Add($vhdPath)
                    }
                }
            }
        }
    }
    catch {
        $result.Warnings += "CIM storage allocation query failed: $($_.Exception.Message)"
    }

    # Batch: VHD info (collect unique paths, query once per unique path)
    $vhdByPath = @{}
    $uniquePaths = @($allDiskPaths | Select-Object -Unique)
    foreach ($path in $uniquePaths) {
        try {
            $vhdByPath[$path] = Get-VHD -Path $path -ErrorAction Stop
        }
        catch {
            # VHD may be inaccessible; continue without size details
        }
    }

    # Batch: Guest OS via KVP exchange (single CIM query for all VMs)
    # Note: We reuse $vmGuidToName from CIM-ComputerSystem query at the start
    $guestOsByVmName = @{}
    try {
        # Query all KVP exchange components at once
        $kvpComponents = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName Msvm_KvpExchangeComponent `
            -ErrorAction SilentlyContinue

        foreach ($kvp in $kvpComponents) {
            if ($kvp.GuestIntrinsicExchangeItems) {
                $osName = $null
                foreach ($item in $kvp.GuestIntrinsicExchangeItems) {
                    try {
                        $xml = [xml]$item
                        # XML structure: <PROPERTY NAME="Name"><VALUE>OSName</VALUE></PROPERTY>
                        $nameNode = $xml.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Name' }
                        if ($nameNode.VALUE -eq 'OSName') {
                            $dataNode = $xml.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Data' }
                            $osName = $dataNode.VALUE
                            break
                        }
                    }
                    catch { }
                }
                # Normalize GUID to uppercase for lookup
                $kvpVmGuid = $kvp.SystemName.ToUpper()
                if ($osName -and $vmGuidToName.ContainsKey($kvpVmGuid)) {
                    $guestOsByVmName[$vmGuidToName[$kvpVmGuid]] = $osName
                }
            }
        }
    }
    catch {
        $result.Warnings += "Batch guest OS query failed: $($_.Exception.Message)"
    }

    # === MERGE ALL DATA ===
    $vmDetails = foreach ($vmName in $vmDataByName.Keys) {
        # Use pre-extracted VM data (avoids slow WMI property access)
        $vm = $vmDataByName[$vmName]

        # Creation time
        $creationTime = $null
        if ($vm.CreationTime) {
            $creationTime = $vm.CreationTime.ToUniversalTime().ToString('o')
        }

        # Memory - use pre-extracted properties
        $memoryGb = 0
        $memoryStartupGb = $null
        $memoryMinimumGb = $null
        $memoryMaximumGb = $null
        $dynamicMemoryEnabled = $null

        if ($vm.MemoryStartup) { $memoryStartupGb = [math]::Round(($vm.MemoryStartup / 1GB), 2) }
        if ($vm.MemoryMinimum) { $memoryMinimumGb = [math]::Round(($vm.MemoryMinimum / 1GB), 2) }
        if ($vm.MemoryMaximum) { $memoryMaximumGb = [math]::Round(($vm.MemoryMaximum / 1GB), 2) }
        $dynamicMemoryEnabled = [bool]$vm.DynamicMemoryEnabled

        if ($vm.MemoryAssigned) {
            $memoryGb = [math]::Round(($vm.MemoryAssigned / 1GB), 2)
        }
        elseif ($memoryStartupGb -ne $null) {
            $memoryGb = $memoryStartupGb
        }

        # Guest OS
        $osName = $guestOsByVmName[$vmName]

        # Build VM info (preserving exact schema)
        $vmInfo = [ordered]@{
            Name                 = $vm.Name
            Id                   = $vm.Id
            State                = $vm.State
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
            OperatingSystem      = $osName
        }

        # Networks - use HashSet for O(1) IP deduplication
        $vmAdapters = $adaptersByVm[$vmName]
        if ($vmAdapters -and $vmAdapters.Count -gt 0) {
            $networks = [System.Collections.Generic.List[object]]::new($vmAdapters.Count)
            $allIpsSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
                
            foreach ($adapter in $vmAdapters) {
                # $adapter is now a pre-extracted hashtable, not a live WMI object
                $adapterIps = [System.Collections.Generic.List[string]]::new()
                if ($adapter.IPAddresses) {
                    foreach ($ip in $adapter.IPAddresses) {
                        if ($ip -and -not $ip.StartsWith('fe80')) {
                            $adapterIps.Add($ip)
                            $null = $allIpsSet.Add($ip)
                        }
                    }
                }

                # VLAN is now stored directly as the ID value
                $vlanId = $vlanById[$adapter.Id]

                $networks.Add(@{
                        Id            = $adapter.Id
                        AdapterName   = $adapter.Name
                        Network       = $adapter.SwitchName
                        VirtualSwitch = $adapter.SwitchName
                        VlanId        = $vlanId
                        IPAddresses   = [string[]]$adapterIps.ToArray()
                        MacAddress    = $adapter.MacAddress
                    })
            }

            $vmInfo.Networks = [object[]]$networks.ToArray()
            if ($allIpsSet.Count -gt 0) {
                $vmInfo.IPAddresses = [string[]]@($allIpsSet)
            }
        }

        # Disks - use List for efficient adding
        $vmDisks = $disksByVm[$vmName]
        if ($vmDisks -and $vmDisks.Count -gt 0) {
            $disks = [System.Collections.Generic.List[object]]::new($vmDisks.Count)
                
            foreach ($disk in $vmDisks) {
                # $disk is now a pre-extracted hashtable from CIM
                $diskPath = $disk.Path
                $diskInfo = @{
                    Id       = $disk.Id
                    Name     = if ($diskPath) { [System.IO.Path]::GetFileName($diskPath) } else { 'Unknown' }
                    Path     = $diskPath
                    DiskType = $null
                }

                if ($diskPath -and $vhdByPath.ContainsKey($diskPath)) {
                    $vhd = $vhdByPath[$diskPath]
                    $diskInfo.CapacityGB = [math]::Round(($vhd.Size / 1GB), 2)
                    $diskInfo.FileSizeGB = [math]::Round(($vhd.FileSize / 1GB), 2)
                    $diskInfo.DiskType = $vhd.VhdType.ToString()
                }

                $disks.Add($diskInfo)
            }

            $vmInfo.Disks = [object[]]$disks.ToArray()
        }

        # Output the VM info
        $vmInfo
    }

    $result.VirtualMachines = @($vmDetails)

    # Load host resources configuration and convert VLAN numbers to network names
    try {
        $configPath = "C:\ProgramData\Aether-V\hostresources.json"
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            $configPath = "C:\ProgramData\Aether-V\hostresources.yaml"
        }

        if (Test-Path -LiteralPath $configPath -PathType Leaf) {
            $rawConfig = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop
                
            $hostConfig = $null
            if ($configPath.EndsWith('.json')) {
                $hostConfig = $rawConfig | ConvertFrom-Json -ErrorAction Stop
            }
            elseif ($configPath.EndsWith('.yaml') -or $configPath.EndsWith('.yml')) {
                if (-not (Get-Command -Name ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
                    Import-Module -Name powershell-yaml -ErrorAction Stop | Out-Null
                }
                $hostConfig = ConvertFrom-Yaml -Yaml $rawConfig -ErrorAction Stop
            }

            if ($hostConfig -and $hostConfig.networks) {
                # Build mapping for network name resolution
                # Match by both switch + vlan and vlan-only for flexibility
                $switchVlanToNetworkMap = @{}
                $vlanToNetworkMap = @{}
                    
                foreach ($network in $hostConfig.networks) {
                    if ($network.model -eq 'vlan' -and $network.configuration) {
                        $switchName = $network.configuration.virtual_switch
                        $vlanId = $network.configuration.vlan_id
                            
                        if ($switchName -and $vlanId) {
                            # Create compound key for switch + vlan
                            $compoundKey = "${switchName}::${vlanId}"
                            $switchVlanToNetworkMap[$compoundKey] = $network.name
                        }
                            
                        if ($vlanId) {
                            # Also track vlan-only mapping as fallback
                            $vlanToNetworkMap[[int]$vlanId] = $network.name
                        }
                    }
                }

                # Update each VM's network adapters with network names
                foreach ($vm in $result.VirtualMachines) {
                    if ($vm.Networks) {
                        foreach ($adapter in $vm.Networks) {
                            $networkName = $null
                                
                            # Try to match by switch + vlan first (most specific)
                            if ($adapter.VirtualSwitch -and $adapter.VlanId) {
                                $compoundKey = "$($adapter.VirtualSwitch)::$($adapter.VlanId)"
                                if ($switchVlanToNetworkMap.ContainsKey($compoundKey)) {
                                    $networkName = $switchVlanToNetworkMap[$compoundKey]
                                }
                            }
                                
                            # Fall back to vlan-only match if no switch+vlan match
                            if (-not $networkName -and $adapter.VlanId) {
                                if ($vlanToNetworkMap.ContainsKey([int]$adapter.VlanId)) {
                                    $networkName = $vlanToNetworkMap[[int]$adapter.VlanId]
                                }
                            }
                                
                            # Assign the resolved network name (overwrites switch name with logical network name)
                            if ($networkName) {
                                $adapter.Network = $networkName
                            }
                        }
                    }
                }
            }
        }
    }
    catch {
        $result.Warnings += "Failed to load host resources configuration for network name resolution: $($_.Exception.Message)"
    }
}
catch {
    $result.Host.Error = $_.Exception.Message
    $result.Host.ExceptionType = $_.Exception.GetType().FullName
    $result.Host.ScriptStackTrace = $_.ScriptStackTrace
    $result | ConvertTo-Json -Depth 8
    exit 1
}

$result | ConvertTo-Json -Depth 8
