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

    # Source common provisioning functions
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    Get-ChildItem -Path (Join-Path $scriptRoot 'Provisioning.*.ps1') -File |
    Sort-Object Name |
    ForEach-Object { . $_.FullName }

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
        if ($null -ne $PipelinedInput -and $PipelinedInput.Count -gt 0) {
            if ($PipelinedInput.Count -eq 1) {
                $rawInput = $PipelinedInput[0]
            }
            else {
                $combined = -join $PipelinedInput
                try {
                    $rawInput = ConvertFrom-Json -InputObject $combined -AsHashtable -ErrorAction Stop
                }
                catch {
                    throw "Failed to parse stdin as JSON: $($_.Exception.Message)"
                }
            }
        }
        else {
            $stdinLines = @()
            while ($null -ne ($line = [Console]::In.ReadLine())) {
                $stdinLines += $line
            }
            if ($stdinLines.Count -gt 0) {
                $stdinText = $stdinLines -join "`n"
                try {
                    $rawInput = ConvertFrom-Json -InputObject $stdinText -AsHashtable -ErrorAction Stop
                }
                catch {
                    throw "Failed to parse stdin as JSON: $($_.Exception.Message)"
                }
            }
        }

        if ($null -eq $rawInput) {
            throw "No input provided via pipeline or stdin."
        }

        return ConvertTo-Hashtable -InputObject $rawInput
    }

    # Main script execution
    try {
        Write-Output "=== VM Initialization Job ==="
        Write-Output "Reading job definition from stdin..."
        
        $jobDef = Read-JobDefinition -PipelinedInput $script:CollectedInput.ToArray()
        
        $fields = $jobDef.fields
        if ($null -eq $fields) {
            throw "Job definition is missing 'fields' property."
        }

        # Extract required parameters
        $vmId = $fields.vm_id
        $vmName = $fields.vm_name
        
        if ([string]::IsNullOrWhiteSpace($vmId)) {
            throw "VM ID is required for initialization."
        }
        
        if ([string]::IsNullOrWhiteSpace($vmName)) {
            throw "VM name is required for initialization."
        }

        Write-Output "VM ID: $vmId"
        Write-Output "VM Name: $vmName"
        
        # Get the VM
        $vm = Get-VM -Id $vmId -ErrorAction SilentlyContinue
        if ($null -eq $vm) {
            throw "VM with ID '$vmId' not found."
        }
        
        Write-Output "Found VM: $($vm.Name)"
        
        # Build provisioning data structure
        $provisioningData = @{
            vm_name = $vmName
            guest_la_uid = $fields.guest_la_uid
            guest_la_pw = $fields.guest_la_pw
        }
        
        # Add optional domain join settings
        if (![string]::IsNullOrWhiteSpace($fields.guest_domain_jointarget)) {
            $provisioningData.guest_domain_jointarget = $fields.guest_domain_jointarget
            $provisioningData.guest_domain_joinuid = $fields.guest_domain_joinuid
            $provisioningData.guest_domain_joinpw = $fields.guest_domain_joinpw
            if (![string]::IsNullOrWhiteSpace($fields.guest_domain_joinou)) {
                $provisioningData.guest_domain_joinou = $fields.guest_domain_joinou
            }
        }
        
        # Add optional Ansible settings
        if (![string]::IsNullOrWhiteSpace($fields.cnf_ansible_ssh_user)) {
            $provisioningData.cnf_ansible_ssh_user = $fields.cnf_ansible_ssh_user
            $provisioningData.cnf_ansible_ssh_key = $fields.cnf_ansible_ssh_key
        }
        
        # Add optional network settings
        if (![string]::IsNullOrWhiteSpace($fields.guest_v4_ipaddr)) {
            $provisioningData.guest_v4_ipaddr = $fields.guest_v4_ipaddr
            $provisioningData.guest_v4_cidrprefix = $fields.guest_v4_cidrprefix
            $provisioningData.guest_v4_defaultgw = $fields.guest_v4_defaultgw
            
            if (![string]::IsNullOrWhiteSpace($fields.guest_v4_dns1)) {
                $provisioningData.guest_v4_dns1 = $fields.guest_v4_dns1
            }
            if (![string]::IsNullOrWhiteSpace($fields.guest_v4_dns2)) {
                $provisioningData.guest_v4_dns2 = $fields.guest_v4_dns2
            }
            if (![string]::IsNullOrWhiteSpace($fields.guest_net_dnssuffix)) {
                $provisioningData.guest_net_dnssuffix = $fields.guest_net_dnssuffix
            }
        }
        
        Write-Output ""
        Write-Output "Publishing provisioning data to VM..."
        
        # Create and attach provisioning ISO
        $tempDef = @{
            schema = @{ id = "internal"; version = 1 }
            fields = $provisioningData
        }
        
        Provisioning.PublishProvisioningData -VM $vm -JobDefinition $tempDef
        
        Write-Output "Provisioning data published successfully"
        Write-Output ""
        Write-Output "Waiting for VM to apply configuration..."
        
        # Wait for the VM to pick up and apply the provisioning data
        $provisioningKey = Provisioning.WaitForProvisioningKey -VM $vm -TimeoutSeconds 1800
        
        if ($null -eq $provisioningKey) {
            throw "VM did not complete provisioning within the timeout period."
        }
        
        Write-Output "VM initialization completed successfully"
        Write-Output "Provisioning key received: $provisioningKey"
        Write-Output ""
        
        # Clean up provisioning ISO
        Provisioning.CleanupISO -VM $vm
        
        Write-Output "Provisioning ISO cleaned up"
        
        # Output success result as JSON
        $result = @{
            success = $true
            vm_id = $vmId
            vm_name = $vmName
            provisioning_key = $provisioningKey
            message = "VM initialized successfully"
        }
        
        $jsonOutput = ConvertTo-Json -InputObject $result -Depth 10 -Compress
        Write-Output ""
        Write-Output "RESULT_JSON: $jsonOutput"
        
        exit 0
    }
    catch {
        Write-Error "VM initialization failed: $($_.Exception.Message)"
        Write-Error $_.ScriptStackTrace
        
        # Output failure result as JSON
        $result = @{
            success = $false
            error = $_.Exception.Message
            stack_trace = $_.ScriptStackTrace
        }
        
        $jsonOutput = ConvertTo-Json -InputObject $result -Depth 10 -Compress
        Write-Output "RESULT_JSON: $jsonOutput"
        
        exit 1
    }
}
