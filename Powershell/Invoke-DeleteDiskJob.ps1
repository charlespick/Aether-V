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

    function Invoke-DeleteDiskWorkflow {
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
        $diskId = [string]$values['resource_id']

        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Deleting disk '$diskId' from VM '$vmName' (ID: $vmId)."

        $disk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Id.ToString() -eq $diskId }
        if (-not $disk) {
            throw "Disk with ID '$diskId' not found on VM '$vmName'."
        }

        $vhdPath = $disk.Path

        Remove-VMHardDiskDrive -VMHardDiskDrive $disk -ErrorAction Stop
        Write-Host "Disk detached from VM." -ForegroundColor Green

        if ($vhdPath) {
            Write-Host "Deleting VHD at '$vhdPath'."
            if (Test-Path -LiteralPath $vhdPath -PathType Leaf) {
                Remove-Item -LiteralPath $vhdPath -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $vhdPath) {
                    throw "Failed to delete VHD file at '$vhdPath'."
                }
                Write-Host "VHD file removed." -ForegroundColor Green
            }
            else {
                Write-Host "VHD file '$vhdPath' not found; skipping deletion." -ForegroundColor Yellow
            }
        }

        $result = @{
            status = "deleted"
            vm_id = $vmId
            vm_name = $vmName
            disk_id = $diskId
            disk_path = $vhdPath
        }

        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-DeleteDiskWorkflow
        exit 0
    }
    catch {
        Write-Error ("Disk deletion job failed: " + $_.Exception.Message)
        exit 1
    }
}
