function Invoke-ProvisioningUpdateVm {
    <#
    .SYNOPSIS
        Update VM hardware and configuration properties.
    
    .DESCRIPTION
        Accepts a partial resource_spec with only fields to update.
        Queries current VM state and applies only provided changes.
        Implements Terraform-compatible mutable properties.
    
    .PARAMETER ResourceSpec
        Hashtable containing vm_id (required), vm_name (required), and optional update fields:
        - cpu_cores: int
        - startup_memory_gb: double
        - memory_gb_min, memory_gb_max, memory_prcnt_buffer: dynamic memory settings
        - secure_boot: string (template name or "Disabled")
        - tpm_enabled: bool
        - host_recovery_action: string ("none", "resume", "always-start")
        - host_stop_action: string ("save", "stop", "shut-down")
        - integration_services_*: bool flags
    
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
    $vmName = $ResourceSpec['vm_name']
    
    if (-not $vmId -or -not $vmName) {
        throw "vm_id and vm_name are required for VM update"
    }

    # Get VM
    $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
    if (-not $vm) {
        throw "VM with ID '$vmId' not found"
    }

    if ($vm.Name -ne $vmName) {
        throw "VM ID '$vmId' exists but name mismatch (expected: $vmName, actual: $($vm.Name))"
    }

    $updates = @()
    $warnings = @()

    # Core hardware updates
    if ($ResourceSpec.ContainsKey('cpu_cores')) {
        $newCpuCores = [int]$ResourceSpec['cpu_cores']
        $currentCpuCores = $vm.ProcessorCount
        
        if ($newCpuCores -ne $currentCpuCores) {
            Set-VMProcessor -VM $vm -Count $newCpuCores
            $updates += "CPU cores: $currentCpuCores -> $newCpuCores"
        }
    }

    # Memory updates
    $memoryChanged = $false
    $dynamicMemoryEnabled = $vm.DynamicMemoryEnabled
    
    if ($ResourceSpec.ContainsKey('startup_memory_gb')) {
        $newStartupBytes = [int64]($ResourceSpec['startup_memory_gb'] * 1GB)
        $currentStartupBytes = $vm.MemoryStartup
        
        if ($newStartupBytes -ne $currentStartupBytes) {
            Set-VMMemory -VM $vm -StartupBytes $newStartupBytes
            $memoryChanged = $true
            $updates += "Startup memory: $([math]::Round($currentStartupBytes / 1GB, 2))GB -> $([math]::Round($newStartupBytes / 1GB, 2))GB"
        }
    }

    # Dynamic memory settings
    $hasDynamicMemoryFields = $ResourceSpec.ContainsKey('memory_gb_min') -or 
                               $ResourceSpec.ContainsKey('memory_gb_max') -or 
                               $ResourceSpec.ContainsKey('memory_prcnt_buffer')
    
    if ($hasDynamicMemoryFields) {
        # Enable dynamic memory if not already enabled
        if (-not $dynamicMemoryEnabled) {
            $memoryParams = @{
                VM = $vm
                DynamicMemoryEnabled = $true
            }
            
            # Set provided values or use current/defaults
            if ($ResourceSpec.ContainsKey('memory_gb_min')) {
                $memoryParams['MinimumBytes'] = [int64]($ResourceSpec['memory_gb_min'] * 1GB)
            }
            if ($ResourceSpec.ContainsKey('memory_gb_max')) {
                $memoryParams['MaximumBytes'] = [int64]($ResourceSpec['memory_gb_max'] * 1GB)
            }
            if ($ResourceSpec.ContainsKey('memory_prcnt_buffer')) {
                $memoryParams['Buffer'] = [int]$ResourceSpec['memory_prcnt_buffer']
            }
            
            Set-VMMemory @memoryParams
            $updates += "Dynamic memory enabled"
            $memoryChanged = $true
        }
        else {
            # Update individual dynamic memory settings
            if ($ResourceSpec.ContainsKey('memory_gb_min')) {
                $newMinBytes = [int64]($ResourceSpec['memory_gb_min'] * 1GB)
                $currentMinBytes = $vm.MemoryMinimum
                if ($newMinBytes -ne $currentMinBytes) {
                    Set-VMMemory -VM $vm -MinimumBytes $newMinBytes
                    $updates += "Min memory: $([math]::Round($currentMinBytes / 1GB, 2))GB -> $([math]::Round($newMinBytes / 1GB, 2))GB"
                    $memoryChanged = $true
                }
            }
            
            if ($ResourceSpec.ContainsKey('memory_gb_max')) {
                $newMaxBytes = [int64]($ResourceSpec['memory_gb_max'] * 1GB)
                $currentMaxBytes = $vm.MemoryMaximum
                if ($newMaxBytes -ne $currentMaxBytes) {
                    Set-VMMemory -VM $vm -MaximumBytes $newMaxBytes
                    $updates += "Max memory: $([math]::Round($currentMaxBytes / 1GB, 2))GB -> $([math]::Round($newMaxBytes / 1GB, 2))GB"
                    $memoryChanged = $true
                }
            }
            
            if ($ResourceSpec.ContainsKey('memory_prcnt_buffer')) {
                $newBuffer = [int]$ResourceSpec['memory_prcnt_buffer']
                # Get current buffer (not directly exposed, skip if not critical)
                Set-VMMemory -VM $vm -Buffer $newBuffer
                $updates += "Memory buffer: $newBuffer%"
                $memoryChanged = $true
            }
        }
    }

    # Security settings - require VM to be off
    $securityChanged = $false
    $needsVmOff = $ResourceSpec.ContainsKey('secure_boot') -or $ResourceSpec.ContainsKey('tpm_enabled')
    
    if ($needsVmOff -and $vm.State -ne 'Off') {
        $warnings += "VM must be powered off to change security settings (secure boot, TPM). Current state: $($vm.State)"
    }
    elseif ($needsVmOff -and $vm.State -eq 'Off') {
        $firmware = Get-VMFirmware -VM $vm
        
        if ($ResourceSpec.ContainsKey('secure_boot')) {
            $secureBootValue = $ResourceSpec['secure_boot']
            
            if ($secureBootValue -eq 'Disabled') {
                if ($firmware.SecureBoot -eq 'On') {
                    Set-VMFirmware -VM $vm -EnableSecureBoot Off
                    $updates += "Secure boot disabled"
                    $securityChanged = $true
                }
            }
            else {
                # Enable secure boot with template
                $currentTemplate = $firmware.SecureBootTemplate
                if ($firmware.SecureBoot -ne 'On' -or $currentTemplate -ne $secureBootValue) {
                    Set-VMFirmware -VM $vm -EnableSecureBoot On -SecureBootTemplate $secureBootValue
                    $updates += "Secure boot enabled: $secureBootValue"
                    $securityChanged = $true
                }
            }
        }
        
        if ($ResourceSpec.ContainsKey('tpm_enabled')) {
            $tpmEnabled = [bool]$ResourceSpec['tpm_enabled']
            $currentTpmState = $null -ne (Get-VMKeyProtector -VM $vm -ErrorAction SilentlyContinue)
            
            if ($tpmEnabled -and -not $currentTpmState) {
                # Enable TPM
                Enable-VMTPM -VM $vm
                $updates += "TPM enabled"
                $securityChanged = $true
            }
            elseif (-not $tpmEnabled -and $currentTpmState) {
                # Disable TPM
                Disable-VMTPM -VM $vm
                $updates += "TPM disabled"
                $securityChanged = $true
            }
        }
    }

    # Host action settings
    if ($ResourceSpec.ContainsKey('host_recovery_action')) {
        $actionValue = $ResourceSpec['host_recovery_action']
        $hypervAction = switch ($actionValue) {
            'none' { 'Nothing' }
            'resume' { 'StartIfPreviouslyRunning' }
            'always-start' { 'Start' }
            default { throw "Invalid host_recovery_action: $actionValue" }
        }
        
        $currentAction = $vm.AutomaticStartAction
        if ($currentAction -ne $hypervAction) {
            Set-VM -VM $vm -AutomaticStartAction $hypervAction
            $updates += "Host recovery action: $currentAction -> $hypervAction"
        }
    }

    if ($ResourceSpec.ContainsKey('host_stop_action')) {
        $actionValue = $ResourceSpec['host_stop_action']
        $hypervAction = switch ($actionValue) {
            'save' { 'Save' }
            'stop' { 'TurnOff' }
            'shut-down' { 'ShutDown' }
            default { throw "Invalid host_stop_action: $actionValue" }
        }
        
        $currentAction = $vm.AutomaticStopAction
        if ($currentAction -ne $hypervAction) {
            Set-VM -VM $vm -AutomaticStopAction $hypervAction
            $updates += "Host stop action: $currentAction -> $hypervAction"
        }
    }

    # Integration services
    $integrationServices = Get-VMIntegrationService -VM $vm
    
    $integrationServiceMap = @{
        'integration_services_shutdown' = 'Shutdown'
        'integration_services_time' = 'Time Synchronization'
        'integration_services_data_exchange' = 'Key-Value Pair Exchange'
        'integration_services_heartbeat' = 'Heartbeat'
        'integration_services_vss_backup' = 'VSS'
        'integration_services_guest_services' = 'Guest Service Interface'
    }
    
    foreach ($key in $integrationServiceMap.Keys) {
        if ($ResourceSpec.ContainsKey($key)) {
            $serviceName = $integrationServiceMap[$key]
            $desiredEnabled = [bool]$ResourceSpec[$key]
            
            $service = $integrationServices | Where-Object { $_.Name -eq $serviceName }
            if ($service) {
                $currentEnabled = $service.Enabled
                if ($desiredEnabled -ne $currentEnabled) {
                    if ($desiredEnabled) {
                        Enable-VMIntegrationService -VM $vm -Name $serviceName
                        $updates += "Enabled integration service: $serviceName"
                    }
                    else {
                        Disable-VMIntegrationService -VM $vm -Name $serviceName
                        $updates += "Disabled integration service: $serviceName"
                    }
                }
            }
        }
    }

    # Build result
    $result = @{
        vm_id = $vmId
        vm_name = $vmName
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
