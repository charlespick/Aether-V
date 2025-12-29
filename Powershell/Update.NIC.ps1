function Invoke-ProvisioningUpdateNic {
    <#
    .SYNOPSIS
        Update network adapter properties.
    
    .DESCRIPTION
        Accepts a partial resource_spec with only fields to update.
        Queries current NIC state and applies only provided changes.
        Implements Terraform-compatible mutable properties.
    
    .PARAMETER ResourceSpec
        Hashtable containing vm_id, resource_id (NIC ID), and optional:
        - network: string (network name - changes virtual switch and VLAN)
        - dhcp_guard: bool
        - router_guard: bool
        - mac_spoof_guard: bool (True = guard enabled = spoofing blocked)
        - mac_address: string ("Dynamic" or specific MAC address)
        - min_bandwidth_mbps: int
        - max_bandwidth_mbps: int
    
    .OUTPUTS
        Hashtable with update results
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$ResourceSpec
    )

    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    # Extract identifiers
    $vmId = $ResourceSpec['vm_id']
    $resourceId = $ResourceSpec['resource_id']
    
    if (-not $vmId -or -not $resourceId) {
        throw "vm_id and resource_id are required for NIC update"
    }

    # Get VM
    $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
    if (-not $vm) {
        throw "VM with ID '$vmId' not found"
    }

    # Get NIC
    $nic = Get-VMNetworkAdapter -VM $vm | Where-Object { $_.Id -eq $resourceId }
    if (-not $nic) {
        throw "Network adapter with ID '$resourceId' not found on VM"
    }

    $updates = @()
    $warnings = @()

    # Network change (switch and VLAN)
    if ($ResourceSpec.ContainsKey('network')) {
        $networkName = $ResourceSpec['network']
        
        # Load host configuration to resolve network
        $configPath = "C:\ProgramData\Aether-V\hostresources.json"
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            $configPath = "C:\ProgramData\Aether-V\hostresources.yaml"
            if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
                throw "Host resources configuration file not found"
            }
        }

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

        # Find network configuration
        $networkConfig = $null
        foreach ($network in $hostConfig.networks) {
            if ($network.name -eq $networkName) {
                $networkConfig = $network
                break
            }
        }
        
        if (-not $networkConfig) {
            throw "Network '$networkName' not found in host configuration"
        }
        
        $virtualSwitch = $networkConfig.configuration.virtual_switch
        $vlanId = $null
        if ($networkConfig.configuration.PSObject.Properties['vlan_id'] -and $null -ne $networkConfig.configuration.vlan_id) {
            $vlanId = [int]$networkConfig.configuration.vlan_id
        }
        
        # Check if switch or VLAN needs to change
        $currentSwitch = $nic.SwitchName
        $currentVlanSetting = Get-VMNetworkAdapterVlan -VMNetworkAdapter $nic
        $currentVlanId = $null
        if ($currentVlanSetting.OperationMode -eq 'Access') {
            $currentVlanId = $currentVlanSetting.AccessVlanId
        }
        
        $switchChanged = $false
        $vlanChanged = $false
        
        if ($currentSwitch -ne $virtualSwitch) {
            Connect-VMNetworkAdapter -VMNetworkAdapter $nic -SwitchName $virtualSwitch
            $updates += "Virtual switch: $currentSwitch -> $virtualSwitch"
            $switchChanged = $true
        }
        
        if ($null -ne $vlanId -and $currentVlanId -ne $vlanId) {
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $nic -Access -VlanId $vlanId
            $updates += "VLAN: $currentVlanId -> $vlanId"
            $vlanChanged = $true
        }
        elseif ($null -eq $vlanId -and $null -ne $currentVlanId) {
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $nic -Untagged
            $updates += "VLAN removed (untagged)"
            $vlanChanged = $true
        }
    }

    # Security settings (guards)
    if ($ResourceSpec.ContainsKey('dhcp_guard')) {
        $dhcpGuard = [bool]$ResourceSpec['dhcp_guard']
        $currentDhcpGuard = $nic.DhcpGuard
        
        if ($dhcpGuard -ne $currentDhcpGuard) {
            Set-VMNetworkAdapter -VMNetworkAdapter $nic -DhcpGuard $dhcpGuard
            $updates += "DHCP guard: $currentDhcpGuard -> $dhcpGuard"
        }
    }

    if ($ResourceSpec.ContainsKey('router_guard')) {
        $routerGuard = [bool]$ResourceSpec['router_guard']
        $currentRouterGuard = $nic.RouterGuard
        
        if ($routerGuard -ne $currentRouterGuard) {
            Set-VMNetworkAdapter -VMNetworkAdapter $nic -RouterGuard $routerGuard
            $updates += "Router guard: $currentRouterGuard -> $routerGuard"
        }
    }

    if ($ResourceSpec.ContainsKey('mac_spoof_guard')) {
        # mac_spoof_guard: True = guard enabled = spoofing blocked (MacAddressSpoofing = Off)
        # mac_spoof_guard: False = guard disabled = spoofing allowed (MacAddressSpoofing = On)
        $macSpoofGuard = [bool]$ResourceSpec['mac_spoof_guard']
        $macSpoofingAllowed = -not $macSpoofGuard
        
        $currentMacSpoofing = $nic.MacAddressSpoofing
        $currentMacSpoofingBool = $currentMacSpoofing -eq 'On'
        
        if ($macSpoofingAllowed -ne $currentMacSpoofingBool) {
            if ($macSpoofingAllowed) {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -MacAddressSpoofing On
                $updates += "MAC spoofing: Blocked -> Allowed (guard disabled)"
            }
            else {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -MacAddressSpoofing Off
                $updates += "MAC spoofing: Allowed -> Blocked (guard enabled)"
            }
        }
    }

    # MAC address
    if ($ResourceSpec.ContainsKey('mac_address')) {
        $macAddress = $ResourceSpec['mac_address']
        $currentMacType = $nic.DynamicMacAddressEnabled
        $currentMac = $nic.MacAddress
        
        if ($macAddress -eq 'Dynamic') {
            if (-not $currentMacType) {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -DynamicMacAddress
                $updates += "MAC address: Static ($currentMac) -> Dynamic"
            }
        }
        else {
            # Static MAC address
            $macAddress = $macAddress -replace '[^0-9A-Fa-f]', ''  # Remove separators
            if ($currentMacType -or $currentMac -ne $macAddress) {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -StaticMacAddress $macAddress
                $updates += "MAC address: $currentMac -> $macAddress (Static)"
            }
        }
    }

    # Bandwidth settings
    if ($ResourceSpec.ContainsKey('min_bandwidth_mbps') -or $ResourceSpec.ContainsKey('max_bandwidth_mbps')) {
        $bandwidthSetting = Get-VMNetworkAdapterBandwidthSetting -VMNetworkAdapter $nic -ErrorAction SilentlyContinue
        
        if ($ResourceSpec.ContainsKey('min_bandwidth_mbps')) {
            $minBandwidthMbps = [int64]$ResourceSpec['min_bandwidth_mbps']
            $currentMin = if ($bandwidthSetting) { $bandwidthSetting.MinimumBandwidthAbsolute / 1MB } else { 0 }
            
            if ($minBandwidthMbps -ne $currentMin) {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -MinimumBandwidthAbsolute ($minBandwidthMbps * 1MB)
                $updates += "Min bandwidth: ${currentMin}Mbps -> ${minBandwidthMbps}Mbps"
            }
        }
        
        if ($ResourceSpec.ContainsKey('max_bandwidth_mbps')) {
            $maxBandwidthMbps = [int64]$ResourceSpec['max_bandwidth_mbps']
            $currentMax = if ($bandwidthSetting) { $bandwidthSetting.MaximumBandwidth / 1MB } else { 0 }
            
            if ($maxBandwidthMbps -ne $currentMax) {
                Set-VMNetworkAdapter -VMNetworkAdapter $nic -MaximumBandwidth ($maxBandwidthMbps * 1MB)
                $updates += "Max bandwidth: ${currentMax}Mbps -> ${maxBandwidthMbps}Mbps"
            }
        }
    }

    # Build result
    $result = @{
        vm_id = $vmId
        resource_id = $resourceId
        adapter_name = $nic.Name
        updates_applied = $updates
        warnings = $warnings
    }

    if ($updates.Count -eq 0 -and $warnings.Count -eq 0) {
        $result['message'] = 'No changes needed - all properties already match requested values'
    }
    elseif ($updates.Count -gt 0) {
        $result['message'] = "Applied $($updates.Count) update(s)"
    }

    return $result
}
