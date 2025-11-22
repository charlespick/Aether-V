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

    function Invoke-UpdateDiskWorkflow {
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

        if (-not ($values.ContainsKey('disk_size_gb') -and $values['disk_size_gb'])) {
            throw "Job definition missing required field 'disk_size_gb'."
        }

        $vmId = [string]$values['vm_id']
        $diskId = [string]$values['resource_id']
        $desiredSizeGb = [int]$values['disk_size_gb']

        $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
        if (-not $vm) {
            throw "VM with ID '$vmId' not found on this host."
        }

        $vmName = $vm.Name
        Write-Host "Updating disk '$diskId' on VM '$vmName' (ID: $vmId)."

        $disk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Id.ToString() -eq $diskId }
        if (-not $disk) {
            throw "Disk with ID '$diskId' not found on VM '$vmName'."
        }

        $vhdPath = $disk.Path
        if (-not $vhdPath) {
            throw "Unable to determine VHD path for disk '$diskId'."
        }

        $vhdInfo = Get-VHD -Path $vhdPath -ErrorAction Stop
        $currentSizeGb = [math]::Ceiling($vhdInfo.Size / 1GB)
        if ($desiredSizeGb -lt $currentSizeGb) {
            throw "Requested size ${desiredSizeGb}GB is smaller than current disk size ${currentSizeGb}GB. Shrinking is not supported."
        }

        if ($desiredSizeGb -eq $currentSizeGb) {
            Write-Host "Disk is already ${desiredSizeGb}GB. No resize required." -ForegroundColor Yellow
        }
        else {
            Write-Host "Resizing disk from ${currentSizeGb}GB to ${desiredSizeGb}GB at '$vhdPath'."
            $desiredBytes = $desiredSizeGb * 1GB
            Resize-VHD -Path $vhdPath -SizeBytes $desiredBytes -ErrorAction Stop
            Write-Host "Disk resized successfully." -ForegroundColor Green
        }

        $result = @{
            status = "updated"
            vm_id = $vmId
            vm_name = $vmName
            disk_id = $diskId
            disk_path = $vhdPath
            size_gb = $desiredSizeGb
        }

        $result | ConvertTo-Json -Depth 2
    }

    try {
        Invoke-UpdateDiskWorkflow
        exit 0
    }
    catch {
        Write-Error ("Disk update job failed: " + $_.Exception.Message)
        exit 1
    }
}
