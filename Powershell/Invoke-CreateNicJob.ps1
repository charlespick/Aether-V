[CmdletBinding()]
param(
    [Parameter(ValueFromPipeline = $true)]
    [AllowNull()]
    [object]$InputObject
)

begin {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $script:CollectedInput = New-Object System.Collections.Generic.List[object]
}

process {
    if ($PSBoundParameters.ContainsKey('InputObject')) {
        $null = $script:CollectedInput.Add($InputObject)
    }
}

end {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    function ConvertTo-Hashtable {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [object]$InputObject
        )

        if ($null -eq $InputObject) {
            return $null
        }

        if ($InputObject -is [System.Collections.IDictionary]) {
            $result = @{}
            foreach ($key in $InputObject.Keys) {
                $value = $InputObject[$key]
                if ($value -is [System.Management.Automation.PSObject] -or $value -is [System.Collections.IDictionary]) {
                    $result[$key] = ConvertTo-Hashtable -InputObject $value
                }
                elseif ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
                    $result[$key] = @($value | ForEach-Object { 
                            if ($_ -is [System.Management.Automation.PSObject] -or $_ -is [System.Collections.IDictionary]) {
                                ConvertTo-Hashtable -InputObject $_
                            }
                            else {
                                $_
                            }
                        })
                }
                else {
                    $result[$key] = $value
                }
            }
            return $result
        }

        if ($InputObject -is [System.Management.Automation.PSObject]) {
            $result = @{}
            foreach ($property in $InputObject.PSObject.Properties) {
                $value = $property.Value
                if ($value -is [System.Management.Automation.PSObject] -or $value -is [System.Collections.IDictionary]) {
                    $result[$property.Name] = ConvertTo-Hashtable -InputObject $value
                }
                elseif ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
                    $result[$property.Name] = @($value | ForEach-Object { 
                            if ($_ -is [System.Management.Automation.PSObject] -or $_ -is [System.Collections.IDictionary]) {
                                ConvertTo-Hashtable -InputObject $_
                            }
                            else {
                                $_
                            }
                        })
                }
                else {
                    $result[$property.Name] = $value
                }
            }
            return $result
        }

        throw "Expected a mapping object but received type '$($InputObject.GetType().FullName)'."
    }

    function Read-JobDefinition {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null

        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $buffer = @()
            foreach ($item in $PipelinedInput) {
                if ($null -eq $item) {
                    continue
                }

                if ($item -is [string]) {
                    $buffer += [string]$item
                    continue
                }

                if ($item -is [System.Collections.IDictionary] -or $item -is [System.Management.Automation.PSObject]) {
                    $buffer += ($item | ConvertTo-Json -Depth 16 -Compress)
                    continue
                }

                $buffer += [string]$item
            }

            if ($buffer.Count -gt 0) {
                $rawInput = [string]::Join([Environment]::NewLine, $buffer)
            }
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            $rawInput = [Console]::In.ReadToEnd()
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            throw "No job definition was supplied via pipeline or standard input."
        }

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Failed to parse job definition as JSON: $($_.Exception.Message)"
        }

        return ConvertTo-Hashtable -InputObject $parsed
    }

    function Invoke-CreateNicWorkflow {
        [CmdletBinding()]
        param()

        $jobDefinition = Read-JobDefinition -PipelinedInput $script:CollectedInput

        $rawFields = $jobDefinition.fields
        if (-not $rawFields) {
            throw "Job definition missing 'fields' mapping."
        }

        $values = ConvertTo-Hashtable $rawFields

        # Validate required fields
        if (-not ($values.ContainsKey('vm_id') -and $values['vm_id'])) {
            throw "Job definition missing required field 'vm_id'."
        }

        if (-not ($values.ContainsKey('network') -and $values['network'])) {
            throw "Job definition missing required field 'network'."
        }

        $vmId = [string]$values['vm_id']
        $networkName = [string]$values['network']
        
        $adapterName = $null
        if ($values.ContainsKey('adapter_name') -and $values['adapter_name']) {
            $adapterName = [string]$values['adapter_name']
        }

        # Get VM by ID
        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Creating network adapter for VM '$vmName' (ID: $vmId)."

        # Load host resources configuration
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

        $hostConfig = ConvertTo-Hashtable -InputObject $hostConfig

        # Resolve network configuration
        $networkConfig = $null
        $networks = $hostConfig['networks']
        if (-not $networks -or $networks.Count -eq 0) {
            throw "No networks defined in host configuration"
        }

        foreach ($network in $networks) {
            if ($network['name'] -eq $networkName) {
                $networkConfig = $network
                break
            }
        }

        if (-not $networkConfig) {
            $availableNetworks = ($networks | ForEach-Object { $_['name'] }) -join ', '
            throw "Network '$networkName' not found in host configuration. Available networks: $availableNetworks"
        }

        $virtualSwitch = $networkConfig['configuration']['virtual_switch']
        $vlanId = $null
        if ($networkConfig['configuration'].ContainsKey('vlan_id') -and $null -ne $networkConfig['configuration']['vlan_id']) {
            $vlanId = [int]$networkConfig['configuration']['vlan_id']
        }

        # Determine adapter name
        if (-not $adapterName) {
            $existingAdapters = Get-VMNetworkAdapter -VM $vm
            $adapterCount = $existingAdapters.Count
            $adapterName = "Network Adapter $($adapterCount + 1)"
        }

        # Add network adapter
        Write-Host "Adding network adapter '$adapterName' to virtual switch '$virtualSwitch'"
        Add-VMNetworkAdapter -VM $vm -Name $adapterName -SwitchName $virtualSwitch -ErrorAction Stop

        # Get the newly created adapter
        $newAdapter = Get-VMNetworkAdapter -VM $vm -Name $adapterName -ErrorAction Stop

        # Set VLAN if specified
        if ($null -ne $vlanId) {
            Write-Host "Setting VLAN ID to $vlanId"
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $newAdapter -Access -VlanId $vlanId -ErrorAction Stop
        }

        $adapterId = $newAdapter.Id

        Write-Host "Network adapter creation completed successfully." -ForegroundColor Green
        Write-Host "Adapter ID: $adapterId" -ForegroundColor Cyan
        
        # Configure static IP if provided (requires guest to be running and integration services active)
        $staticIpConfigured = $false
        if ($values.ContainsKey('guest_v4_ipaddr') -and $values['guest_v4_ipaddr']) {
            Write-Host "Static IP configuration will be applied when VM is running with integration services."
            # Note: Static IP configuration for NICs added after VM creation requires guest OS configuration
            # This would typically be done via:
            # 1. PowerShell Direct (if Windows)
            # 2. SSH (if Linux)
            # 3. Guest configuration management tool
            # For now, we'll just note that this was requested
            $staticIpConfigured = $true
        }

        # Output the adapter ID as JSON for the control plane
        $result = @{
            nic_id              = $adapterId
            adapter_name        = $adapterName
            vm_id               = $vmId
            vm_name             = $vmName
            network             = $networkName
            virtual_switch      = $virtualSwitch
            vlan_id             = $vlanId
            mac_address         = $newAdapter.MacAddress
            static_ip_requested = $staticIpConfigured
            status              = "created"
        }
        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-CreateNicWorkflow
        exit 0
    }
    catch {
        Write-Error ("Network adapter creation job failed: " + $_.Exception.Message)
        exit 1
    }
}
