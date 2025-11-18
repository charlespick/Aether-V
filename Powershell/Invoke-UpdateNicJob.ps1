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
                $result[$key] = $InputObject[$key]
            }
            return $result
        }

        if ($InputObject -is [System.Management.Automation.PSObject]) {
            $result = @{}
            foreach ($property in $InputObject.PSObject.Properties) {
                $result[$property.Name] = $property.Value
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

    function Load-HostNetworkConfig {
        [CmdletBinding()]
        param()

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

        return ConvertTo-Hashtable -InputObject $hostConfig
    }

    function Invoke-UpdateNicWorkflow {
        [CmdletBinding()]
        param()

        $jobDefinition = Read-JobDefinition -PipelinedInput $script:CollectedInput

        $rawFields = $jobDefinition.fields
        if (-not $rawFields) {
            throw "Job definition missing 'fields' mapping."
        }

        $values = ConvertTo-Hashtable $rawFields

        if (-not ($values.ContainsKey('vm_id') -and $values['vm_id'])) {
            throw "Job definition missing required field 'vm_id'."
        }

        if (-not ($values.ContainsKey('resource_id') -and $values['resource_id'])) {
            throw "Job definition missing required field 'resource_id'."
        }

        if (-not ($values.ContainsKey('network') -and $values['network'])) {
            throw "Job definition missing required field 'network'."
        }

        $vmId = [string]$values['vm_id']
        $nicId = [string]$values['resource_id']
        $networkName = [string]$values['network']
        $adapterName = $null
        if ($values.ContainsKey('adapter_name') -and $values['adapter_name']) {
            $adapterName = [string]$values['adapter_name']
        }

        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Updating network adapter '$nicId' for VM '$vmName' (ID: $vmId)."

        $adapter = Get-VMNetworkAdapter -VM $vm | Where-Object { $_.Id.ToString() -eq $nicId }
        if (-not $adapter) {
            throw "Network adapter with ID '$nicId' not found on VM '$vmName'."
        }

        $hostConfig = Load-HostNetworkConfig
        $networks = $hostConfig['networks']
        if (-not $networks -or $networks.Count -eq 0) {
            throw "No networks defined in host configuration"
        }

        $networkConfig = $null
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

        if (-not [string]::IsNullOrWhiteSpace($virtualSwitch)) {
            Write-Host "Connecting adapter to virtual switch '$virtualSwitch'"
            Connect-VMNetworkAdapter -VMNetworkAdapter $adapter -SwitchName $virtualSwitch -ErrorAction Stop
        }

        if ($adapterName -and $adapter.Name -ne $adapterName) {
            Write-Host "Renaming adapter to '$adapterName'"
            Set-VMNetworkAdapter -VMNetworkAdapter $adapter -Name $adapterName -ErrorAction Stop
            $adapter = Get-VMNetworkAdapter -VM $vm | Where-Object { $_.Id.ToString() -eq $nicId }
        }

        if ($null -ne $vlanId) {
            Write-Host "Setting VLAN ID to $vlanId"
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $adapter -Access -VlanId $vlanId -ErrorAction Stop
        }
        else {
            Write-Host "Clearing VLAN configuration (untagged)"
            Set-VMNetworkAdapterVlan -VMNetworkAdapter $adapter -Untagged -ErrorAction Stop
        }

        $result = @{
            status = "updated"
            vm_id = $vmId
            vm_name = $vmName
            nic_id = $nicId
            adapter_name = $adapter.Name
            network = $networkName
            virtual_switch = $virtualSwitch
            vlan_id = $vlanId
            mac_address = $adapter.MacAddress
        }

        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-UpdateNicWorkflow
        exit 0
    }
    catch {
        Write-Error ("NIC update job failed: " + $_.Exception.Message)
        exit 1
    }
}
