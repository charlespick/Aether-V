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

    function Read-DeletionPayload {
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
            throw "No deletion payload was supplied via pipeline or standard input."
        }

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Failed to parse deletion payload as JSON: $($_.Exception.Message)"
        }

        return ConvertTo-Hashtable -InputObject $parsed
    }

    function Invoke-DeleteNicWorkflow {
        [CmdletBinding()]
        param()

        $values = Read-DeletionPayload -PipelinedInput $script:CollectedInput

        if (-not ($values.ContainsKey('vm_id') -and $values['vm_id'])) {
            throw "Deletion payload missing required field 'vm_id'."
        }

        if (-not ($values.ContainsKey('resource_id') -and $values['resource_id'])) {
            throw "Deletion payload missing required field 'resource_id'."
        }

        $vmId = [string]$values['vm_id']
        $nicId = [string]$values['resource_id']

        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Deleting network adapter '$nicId' from VM '$vmName' (ID: $vmId)."

        $adapter = Get-VMNetworkAdapter -VM $vm | Where-Object { $_.Id.ToString() -eq $nicId }
        if (-not $adapter) {
            throw "Network adapter with ID '$nicId' not found on VM '$vmName'."
        }

        Remove-VMNetworkAdapter -VMNetworkAdapter $adapter -ErrorAction Stop
        Write-Host "Network adapter removed." -ForegroundColor Green

        $result = @{
            status = "deleted"
            vm_id = $vmId
            vm_name = $vmName
            nic_id = $nicId
        }

        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-DeleteNicWorkflow
        exit 0
    }
    catch {
        Write-Error ("NIC deletion job failed: " + $_.Exception.Message)
        exit 1
    }
}
