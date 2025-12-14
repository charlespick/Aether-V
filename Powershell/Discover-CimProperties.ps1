<#
.SYNOPSIS
    Discovery script to identify CIM classes and properties needed for VM inventory collection.

.DESCRIPTION
    This script performs comprehensive CIM discovery to identify the precise classes,
    properties, and relationships needed to collect VM properties that are currently
    missing from Inventory.Collect.ps1.
    
    Missing properties to discover:
    - dynamic_memory_buffer (Memory buffer percentage)
    - secure_boot_enabled, secure_boot_template
    - trusted_platform_module_enabled, tpm_key_protector
    - primary_boot_device
    - host_recovery_action, host_stop_action
    - integration_services (shutdown, time, data_exchange, heartbeat, vss_backup, guest_services)
    
    The script will output detailed information about:
    - CIM class names and namespaces
    - Property names and types
    - Sample values from a test VM
    - Relationships between classes (via InstanceID patterns)
    - Performance metrics for each query
    
.PARAMETER VmName
    Name of a test VM to use for discovery. If not specified, uses the first available VM.

.PARAMETER OutputFormat
    Output format: Text, Json, or Csv. Default is Text.

.EXAMPLE
    .\Discover-CimProperties.ps1 -VmName "test-vm-01"
    
.EXAMPLE
    .\Discover-CimProperties.ps1 -OutputFormat Json | Out-File discovery-results.json
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$VmName,
    
    [Parameter(Mandatory = $false)]
    [ValidateSet('Text', 'Json', 'Csv')]
    [string]$OutputFormat = 'Text'
)

$ErrorActionPreference = 'Continue'
$namespace = 'root\virtualization\v2'

# Results collection
$results = @{
    Timestamp              = (Get-Date).ToUniversalTime().ToString('o')
    TestVM                 = $null
    Discoveries            = @()
    PerformanceMetrics     = @()
    Recommendations        = @()
}

#region Helper Functions

function Measure-CimQuery {
    param(
        [string]$Description,
        [scriptblock]$Query
    )
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $Query
        $stopwatch.Stop()
        
        $results.PerformanceMetrics += @{
            Description   = $Description
            DurationMs    = $stopwatch.ElapsedMilliseconds
            Success       = $true
            ResultCount   = if ($result -is [array]) { $result.Count } else { if ($result) { 1 } else { 0 } }
        }
        
        return $result
    }
    catch {
        $stopwatch.Stop()
        $results.PerformanceMetrics += @{
            Description   = $Description
            DurationMs    = $stopwatch.ElapsedMilliseconds
            Success       = $false
            Error         = $_.Exception.Message
        }
        return $null
    }
}

function Get-PropertyDetails {
    param(
        [object]$CimObject,
        [string[]]$PropertyNames
    )
    
    $details = @()
    foreach ($propName in $PropertyNames) {
        try {
            $value = $CimObject.$propName
            $type = if ($value -ne $null) { $value.GetType().Name } else { 'null' }
            
            $details += @{
                Name  = $propName
                Type  = $type
                Value = $value
            }
        }
        catch {
            $details += @{
                Name  = $propName
                Type  = 'Error'
                Value = $_.Exception.Message
            }
        }
    }
    
    return $details
}

function Add-Discovery {
    param(
        [string]$Category,
        [string]$PropertyName,
        [string]$CimClass,
        [string]$CimProperty,
        [object]$SampleValue,
        [string]$InstanceIdPattern,
        [string]$Notes,
        [hashtable]$RelatedClass = $null,
        [string[]]$AdditionalProperties = @()
    )
    
    $results.Discoveries += [PSCustomObject]@{
        Category              = $Category
        PropertyName          = $PropertyName
        CimClass              = $CimClass
        CimProperty           = $CimProperty
        SampleValue           = $SampleValue
        InstanceIdPattern     = $InstanceIdPattern
        Notes                 = $Notes
        RelatedClass          = $RelatedClass
        AdditionalProperties  = $AdditionalProperties
    }
}

#endregion

#region Select Test VM

Write-Host "=== Selecting Test VM ===" -ForegroundColor Cyan

if (-not $VmName) {
    $testVm = Get-VM | Where-Object { $_.State -eq 'Running' } | Select-Object -First 1
    if (-not $testVm) {
        $testVm = Get-VM | Select-Object -First 1
    }
    if (-not $testVm) {
        Write-Error "No VMs found on this host. Please create a test VM first."
        exit 1
    }
    $VmName = $testVm.Name
}
else {
    $testVm = Get-VM -Name $VmName -ErrorAction Stop
}

$results.TestVM = @{
    Name       = $testVm.Name
    Id         = $testVm.Id.Guid
    State      = $testVm.State.ToString()
    Generation = $testVm.Generation
}

$vmGuid = $testVm.Id.Guid.ToUpper()
Write-Host "Using test VM: $VmName (ID: $vmGuid)" -ForegroundColor Green
Write-Host ""

#endregion

#region Dynamic Memory Buffer Discovery

Write-Host "=== Discovering Dynamic Memory Buffer ===" -ForegroundColor Cyan

$memSettings = Measure-CimQuery -Description "Msvm_MemorySettingData query" -Query {
    Get-CimInstance -Namespace $namespace `
        -ClassName Msvm_MemorySettingData `
        -ErrorAction Stop |
    Where-Object { $_.InstanceID -like "Microsoft:$vmGuid*" -and $_.InstanceID -notlike '*Definition*' }
}

if ($memSettings) {
    Write-Host "Found Msvm_MemorySettingData for VM" -ForegroundColor Green
    
    # List all properties
    $allProps = $memSettings | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
    Write-Host "Available properties: $($allProps -join ', ')"
    
    # Key properties for dynamic memory
    $keyProps = @(
        'VirtualQuantity',      # Startup memory (MB)
        'Reservation',          # Minimum memory (MB)
        'Limit',                # Maximum memory (MB)
        'DynamicMemoryEnabled',
        'TargetMemoryBuffer'    # POTENTIAL: Memory buffer percentage
    )
    
    $propDetails = Get-PropertyDetails -CimObject $memSettings -PropertyNames $keyProps
    foreach ($prop in $propDetails) {
        Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
    }
    
    # Check for buffer-related properties
    $bufferProps = $allProps | Where-Object { $_ -match 'buffer|target|weight|priority' }
    if ($bufferProps) {
        Write-Host "`nBuffer-related properties found:" -ForegroundColor Yellow
        $bufferDetails = Get-PropertyDetails -CimObject $memSettings -PropertyNames $bufferProps
        foreach ($prop in $bufferDetails) {
            Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
        }
    }
    
    Add-Discovery `
        -Category "Dynamic Memory" `
        -PropertyName "dynamic_memory_buffer" `
        -CimClass "Msvm_MemorySettingData" `
        -CimProperty "TargetMemoryBuffer" `
        -SampleValue $memSettings.TargetMemoryBuffer `
        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
        -Notes "Memory buffer percentage for dynamic memory. TargetMemoryBuffer is the most likely property. Verify if this maps to the PowerShell Get-VM's MemoryMaximum calculation or is a separate buffer setting."
}
else {
    Write-Host "No memory settings found" -ForegroundColor Red
}

Write-Host ""

#endregion

#region Secure Boot Discovery

Write-Host "=== Discovering Secure Boot Settings ===" -ForegroundColor Cyan

# Try multiple potential classes
$securityClasses = @(
    'Msvm_VirtualSystemSettingData',
    'Msvm_SecuritySettingData',
    'Msvm_SecurityElement'
)

foreach ($className in $securityClasses) {
    Write-Host "`nTrying class: $className" -ForegroundColor Yellow
    
    $securitySettings = Measure-CimQuery -Description "$className query" -Query {
        Get-CimInstance -Namespace $namespace `
            -ClassName $className `
            -ErrorAction Stop |
        Where-Object { $_.InstanceID -like "Microsoft:$vmGuid*" -or $_.SystemName -eq $vmGuid }
    }
    
    if ($securitySettings) {
        Write-Host "Found $className" -ForegroundColor Green
        
        $allProps = $securitySettings | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
        
        # Security-related properties
        $securityProps = $allProps | Where-Object { $_ -match 'secure|boot|uefi|tpm|template|shielded|encryption|key' }
        
        if ($securityProps) {
            Write-Host "Security-related properties:" -ForegroundColor Green
            $secDetails = Get-PropertyDetails -CimObject $securitySettings -PropertyNames $securityProps
            foreach ($prop in $secDetails) {
                Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
                
                # Record discoveries
                if ($prop.Name -match 'SecureBoot' -and $prop.Name -notmatch 'Template') {
                    Add-Discovery `
                        -Category "Security" `
                        -PropertyName "secure_boot_enabled" `
                        -CimClass $className `
                        -CimProperty $prop.Name `
                        -SampleValue $prop.Value `
                        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                        -Notes "Secure boot enabled/disabled flag"
                }
                
                if ($prop.Name -match 'SecureBootTemplate|BootSourceDescription') {
                    Add-Discovery `
                        -Category "Security" `
                        -PropertyName "secure_boot_template" `
                        -CimClass $className `
                        -CimProperty $prop.Name `
                        -SampleValue $prop.Value `
                        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                        -Notes "Secure boot template name (e.g., 'MicrosoftWindows', 'MicrosoftUEFICertificateAuthority')"
                }
            }
        }
    }
}

Write-Host ""

#endregion

#region TPM Discovery

Write-Host "=== Discovering TPM Settings ===" -ForegroundColor Cyan

$tpmClasses = @(
    'Msvm_SecuritySettingData',
    'Msvm_KeyProtector'
)

foreach ($className in $tpmClasses) {
    Write-Host "`nTrying class: $className" -ForegroundColor Yellow
    
    $tpmSettings = Measure-CimQuery -Description "$className query" -Query {
        Get-CimInstance -Namespace $namespace `
            -ClassName $className `
            -ErrorAction Stop |
        Where-Object { $_.InstanceID -like "Microsoft:$vmGuid*" -or $_.SystemName -eq $vmGuid }
    }
    
    if ($tpmSettings) {
        Write-Host "Found $className" -ForegroundColor Green
        
        $allProps = $tpmSettings | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
        
        # TPM-related properties
        $tpmProps = $allProps | Where-Object { $_ -match 'tpm|trusted|platform|module|vtpm|key|protector' }
        
        if ($tpmProps) {
            Write-Host "TPM-related properties:" -ForegroundColor Green
            $tpmDetails = Get-PropertyDetails -CimObject $tpmSettings -PropertyNames $tpmProps
            foreach ($prop in $tpmDetails) {
                Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
                
                if ($prop.Name -match 'TpmEnabled|VirtualizationBasedSecurityOptOut') {
                    Add-Discovery `
                        -Category "Security" `
                        -PropertyName "trusted_platform_module_enabled" `
                        -CimClass $className `
                        -CimProperty $prop.Name `
                        -SampleValue $prop.Value `
                        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                        -Notes "TPM enabled/disabled flag. May be inverted (OptOut)"
                }
                
                if ($prop.Name -match 'KeyProtector|EncryptionKey') {
                    Add-Discovery `
                        -Category "Security" `
                        -PropertyName "tpm_key_protector" `
                        -CimClass $className `
                        -CimProperty $prop.Name `
                        -SampleValue "(redacted)" `
                        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                        -Notes "TPM key protector data (base64 or hex encoded)"
                }
            }
        }
    }
}

Write-Host ""

#endregion

#region Boot Device Discovery

Write-Host "=== Discovering Boot Device Settings ===" -ForegroundColor Cyan

$bootClasses = @(
    'Msvm_VirtualSystemSettingData',
    'Msvm_BootSourceSettingData'
)

foreach ($className in $bootClasses) {
    Write-Host "`nTrying class: $className" -ForegroundColor Yellow
    
    $bootSettings = Measure-CimQuery -Description "$className query" -Query {
        Get-CimInstance -Namespace $namespace `
            -ClassName $className `
            -ErrorAction Stop |
        Where-Object { $_.InstanceID -like "Microsoft:$vmGuid*" }
    }
    
    if ($bootSettings) {
        Write-Host "Found $className" -ForegroundColor Green
        
        $allProps = $bootSettings | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
        
        # Boot-related properties
        $bootProps = $allProps | Where-Object { $_ -match 'boot|order|source|device|firmware' }
        
        if ($bootProps) {
            Write-Host "Boot-related properties:" -ForegroundColor Green
            $bootDetails = Get-PropertyDetails -CimObject $bootSettings -PropertyNames $bootProps
            foreach ($prop in $bootDetails) {
                $displayValue = $prop.Value
                if ($prop.Value -is [array]) {
                    $displayValue = "Array[$($prop.Value.Count)]"
                }
                Write-Host "  $($prop.Name): $displayValue ($($prop.Type))"
                
                if ($prop.Name -match 'BootOrder|BootSourceOrder') {
                    Add-Discovery `
                        -Category "Boot" `
                        -PropertyName "primary_boot_device" `
                        -CimClass $className `
                        -CimProperty $prop.Name `
                        -SampleValue "Array reference" `
                        -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                        -Notes "Boot order array. First element is primary boot device. May need to resolve references to get device names."
                }
            }
        }
    }
}

Write-Host ""

#endregion

#region Host Actions Discovery

Write-Host "=== Discovering Host Recovery and Stop Actions ===" -ForegroundColor Cyan

$vsData = Measure-CimQuery -Description "Msvm_VirtualSystemSettingData query" -Query {
    Get-CimInstance -Namespace $namespace `
        -ClassName Msvm_VirtualSystemSettingData `
        -ErrorAction Stop |
    Where-Object { $_.VirtualSystemIdentifier -eq $vmGuid }
}

if ($vsData) {
    Write-Host "Found Msvm_VirtualSystemSettingData" -ForegroundColor Green
    
    $allProps = $vsData | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
    
    # Action-related properties
    $actionProps = $allProps | Where-Object { $_ -match 'automatic|recovery|action|stop|start|shutdown' }
    
    if ($actionProps) {
        Write-Host "Action-related properties:" -ForegroundColor Green
        $actionDetails = Get-PropertyDetails -CimObject $vsData -PropertyNames $actionProps
        foreach ($prop in $actionDetails) {
            Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
            
            if ($prop.Name -match 'AutomaticRecoveryAction|OnAutomaticRecovery') {
                Add-Discovery `
                    -Category "Host Actions" `
                    -PropertyName "host_recovery_action" `
                    -CimClass "Msvm_VirtualSystemSettingData" `
                    -CimProperty $prop.Name `
                    -SampleValue $prop.Value `
                    -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                    -Notes "Action to take when host recovers. Enum: 2=None, 3=Restart, 4=AlwaysStartup"
                    -AdditionalProperties @('AutomaticStartupAction', 'AutomaticStartupActionDelay')
            }
            
            if ($prop.Name -match 'AutomaticShutdownAction') {
                Add-Discovery `
                    -Category "Host Actions" `
                    -PropertyName "host_stop_action" `
                    -CimClass "Msvm_VirtualSystemSettingData" `
                    -CimProperty $prop.Name `
                    -SampleValue $prop.Value `
                    -InstanceIdPattern "Microsoft:{VM_GUID}\..." `
                    -Notes "Action to take when host stops. Enum: 2=TurnOff, 3=Save, 4=ShutDown"
            }
        }
    }
}

Write-Host ""

#endregion

#region Integration Services Discovery

Write-Host "=== Discovering Integration Services ===" -ForegroundColor Cyan

# Integration services are exposed via multiple classes
$integrationClasses = @(
    'Msvm_ShutdownComponent',
    'Msvm_TimeSyncComponent',
    'Msvm_KvpExchangeComponent',
    'Msvm_HeartbeatComponent',
    'Msvm_VssIntegrationComponent',
    'Msvm_GuestServiceInterfaceComponent'
)

$integrationServiceMap = @{
    'Msvm_ShutdownComponent'              = @{
        PropertyName = 'integration_services_shutdown'
        Description  = 'Guest shutdown integration service'
    }
    'Msvm_TimeSyncComponent'              = @{
        PropertyName = 'integration_services_time'
        Description  = 'Time synchronization integration service'
    }
    'Msvm_KvpExchangeComponent'           = @{
        PropertyName = 'integration_services_data_exchange'
        Description  = 'Data exchange (KVP) integration service'
    }
    'Msvm_HeartbeatComponent'             = @{
        PropertyName = 'integration_services_heartbeat'
        Description  = 'Heartbeat integration service'
    }
    'Msvm_VssIntegrationComponent'        = @{
        PropertyName = 'integration_services_vss_backup'
        Description  = 'VSS backup integration service'
    }
    'Msvm_GuestServiceInterfaceComponent' = @{
        PropertyName = 'integration_services_guest_services'
        Description  = 'Guest service interface'
    }
}

foreach ($className in $integrationClasses) {
    Write-Host "`nTrying class: $className" -ForegroundColor Yellow
    
    $component = Measure-CimQuery -Description "$className query" -Query {
        Get-CimInstance -Namespace $namespace `
            -ClassName $className `
            -ErrorAction Stop |
        Where-Object { $_.SystemName -eq $vmGuid }
    }
    
    if ($component) {
        Write-Host "Found $className" -ForegroundColor Green
        
        $allProps = $component | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
        
        # Look for enabled/status properties
        $statusProps = $allProps | Where-Object { $_ -match 'enabled|operational|status|state' }
        
        if ($statusProps) {
            Write-Host "Status properties:" -ForegroundColor Green
            $statusDetails = Get-PropertyDetails -CimObject $component -PropertyNames $statusProps
            foreach ($prop in $statusDetails) {
                Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
            }
            
            # The EnabledState property is typically used (2=Enabled, 3=Disabled, 6=Enabled but Offline)
            if ('EnabledState' -in $statusProps) {
                $mapping = $integrationServiceMap[$className]
                Add-Discovery `
                    -Category "Integration Services" `
                    -PropertyName $mapping.PropertyName `
                    -CimClass $className `
                    -CimProperty "EnabledState" `
                    -SampleValue $component.EnabledState `
                    -InstanceIdPattern "SystemName={VM_GUID}" `
                    -Notes "$($mapping.Description). EnabledState: 2=Enabled, 3=Disabled, 6=Enabled but Offline"
            }
        }
    }
    else {
        Write-Host "Not found or not applicable" -ForegroundColor Gray
    }
}

Write-Host ""

#endregion

#region Additional Useful Properties Discovery

Write-Host "=== Discovering Additional Useful Properties ===" -ForegroundColor Cyan

# Check for properties that might be useful but aren't in the current model
Write-Host "`nChecking Msvm_ComputerSystem for additional properties..." -ForegroundColor Yellow
$vmSystem = Measure-CimQuery -Description "Msvm_ComputerSystem query" -Query {
    Get-CimInstance -Namespace $namespace `
        -ClassName Msvm_ComputerSystem `
        -Filter "Name='$vmGuid'" `
        -ErrorAction Stop
}

if ($vmSystem) {
    $allProps = $vmSystem | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
    $interestingProps = $allProps | Where-Object { 
        $_ -match 'replication|checkpoint|snapshot|numa|failover|migration|resource|priority|limit|reservation'
    }
    
    if ($interestingProps) {
        Write-Host "Potentially useful properties:" -ForegroundColor Green
        $details = Get-PropertyDetails -CimObject $vmSystem -PropertyNames $interestingProps
        foreach ($prop in $details) {
            Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
        }
    }
}

# Check processor settings for advanced properties
Write-Host "`nChecking Msvm_ProcessorSettingData for additional properties..." -ForegroundColor Yellow
$procSettings = Measure-CimQuery -Description "Msvm_ProcessorSettingData query" -Query {
    Get-CimInstance -Namespace $namespace `
        -ClassName Msvm_ProcessorSettingData `
        -ErrorAction Stop |
    Where-Object { $_.InstanceID -like "Microsoft:$vmGuid*" -and $_.InstanceID -notlike '*Definition*' }
}

if ($procSettings) {
    $allProps = $procSettings | Get-Member -MemberType Property | Select-Object -ExpandProperty Name
    $interestingProps = $allProps | Where-Object { 
        $_ -match 'limit|reservation|weight|cap|numa|nested|compatibility|expose'
    }
    
    if ($interestingProps) {
        Write-Host "Potentially useful processor properties:" -ForegroundColor Green
        $details = Get-PropertyDetails -CimObject $procSettings -PropertyNames $interestingProps
        foreach ($prop in $details) {
            Write-Host "  $($prop.Name): $($prop.Value) ($($prop.Type))"
        }
    }
}

Write-Host ""

#endregion

#region Performance Summary

Write-Host "=== Performance Summary ===" -ForegroundColor Cyan
Write-Host ""

$totalDuration = ($results.PerformanceMetrics | Measure-Object -Property DurationMs -Sum).Sum
$successCount = ($results.PerformanceMetrics | Where-Object { $_.Success }).Count
$failCount = ($results.PerformanceMetrics | Where-Object { -not $_.Success }).Count

Write-Host "Total queries: $($results.PerformanceMetrics.Count)"
Write-Host "Successful: $successCount"
Write-Host "Failed: $failCount"
Write-Host "Total duration: ${totalDuration}ms"
Write-Host ""

$results.PerformanceMetrics | Sort-Object DurationMs -Descending | Select-Object -First 5 | ForEach-Object {
    $status = if ($_.Success) { "✓" } else { "✗" }
    Write-Host "$status $($_.Description): $($_.DurationMs)ms"
}

Write-Host ""

#endregion

#region Generate Recommendations

Write-Host "=== Implementation Recommendations ===" -ForegroundColor Cyan
Write-Host ""

$results.Recommendations = @(
    "1. Batch Query Strategy: Query each CIM class once for all VMs to minimize WMI overhead"
    "2. Use InstanceID/SystemName filtering: Filter results by VM GUID to map to specific VMs"
    "3. Integration Services: Query all 6 component classes in parallel or sequence"
    "4. Security Settings: Msvm_VirtualSystemSettingData and Msvm_SecuritySettingData contain most security properties"
    "5. Enum Mapping: Create lookup tables for EnabledState and Action enums to match PowerShell values"
    "6. Error Handling: Not all VMs have all components (e.g., Gen1 VMs don't have TPM)"
)

foreach ($rec in $results.Recommendations) {
    Write-Host $rec
}

Write-Host ""

#endregion

#region Output Results

if ($OutputFormat -eq 'Json') {
    $results | ConvertTo-Json -Depth 10
}
elseif ($OutputFormat -eq 'Csv') {
    # Flatten discoveries for CSV
    $results.Discoveries | Export-Csv -Path "discovery-results.csv" -NoTypeInformation
    Write-Host "CSV exported to: discovery-results.csv"
}
else {
    # Text format summary
    Write-Host "=== Discovery Summary ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Discovered $($results.Discoveries.Count) property mappings:"
    Write-Host ""
    
    $results.Discoveries | Group-Object -Property Category | ForEach-Object {
        Write-Host "$($_.Name):" -ForegroundColor Yellow
        $_.Group | ForEach-Object {
            Write-Host "  ✓ $($_.PropertyName)" -ForegroundColor Green
            Write-Host "    Class: $($_.CimClass)"
            Write-Host "    Property: $($_.CimProperty)"
            Write-Host "    Sample: $($_.SampleValue)"
            if ($_.Notes) {
                Write-Host "    Notes: $($_.Notes)" -ForegroundColor Gray
            }
            Write-Host ""
        }
    }
}

#endregion

Write-Host "Discovery complete!" -ForegroundColor Green
