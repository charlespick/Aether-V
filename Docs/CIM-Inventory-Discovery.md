# CIM Inventory Collection - Property Discovery

## Overview

This document describes the process of discovering CIM classes and properties needed to extend the `Inventory.Collect.ps1` script with missing VM properties.

## Current Implementation Analysis

The `Inventory.Collect.ps1` script uses a highly optimized approach by querying CIM classes directly instead of using PowerShell cmdlets like `Get-VM`, `Get-VMNetworkAdapter`, etc. This provides significant performance improvements:

### Current CIM Query Strategy

1. **Batch Queries**: All VMs are queried at once, not individually
2. **Direct CIM Access**: Uses `Get-CimInstance` instead of Hyper-V cmdlets
3. **Indexed Lookups**: Results are indexed by VM GUID for O(1) lookup
4. **Minimal Property Selection**: Only needed properties are accessed
5. **Pre-filtered Queries**: Uses WMI filters to reduce result sets

### Classes Currently Used

| CIM Class | Purpose | Key Properties |
|-----------|---------|----------------|
| `Msvm_ComputerSystem` | VM basic info | Name, ElementName, EnabledState |
| `Msvm_VirtualSystemSettingData` | VM settings | CreationTime, Notes, Version, VirtualSystemSubType |
| `Msvm_MemorySettingData` | Memory config | VirtualQuantity, Reservation, Limit, DynamicMemoryEnabled |
| `Msvm_Memory` | Current memory | NumberOfBlocks (current allocation) |
| `Msvm_ProcessorSettingData` | CPU config | VirtualQuantity (core count) |
| `Msvm_SyntheticEthernetPortSettingData` | Network adapters | ElementName, Address, StaticMacAddress |
| `Msvm_EthernetPortAllocationSettingData` | Network connections | HostResource (switch) |
| `Msvm_GuestNetworkAdapterConfiguration` | IP addresses | IPAddresses |
| `Msvm_EthernetSwitchPortVlanSettingData` | VLAN config | AccessVlanId |
| `Msvm_StorageAllocationSettingData` | Disks | HostResource (VHD path) |
| `Msvm_KvpExchangeComponent` | Guest OS | GuestIntrinsicExchangeItems (OSName) |

## Missing Properties in Current Implementation

Based on the VM model in `server/app/core/models.py`, the following properties are **not** currently collected:

### 1. Dynamic Memory Buffer
- **Model Property**: `dynamic_memory_buffer: Optional[int]`
- **Description**: Memory buffer percentage for dynamic memory
- **Expected Source**: `Msvm_MemorySettingData`

### 2. Security Settings

#### Secure Boot
- **Model Properties**: 
  - `secure_boot_enabled: Optional[bool]`
  - `secure_boot_template: Optional[str]`
- **Expected Sources**: 
  - `Msvm_VirtualSystemSettingData` or `Msvm_SecuritySettingData`

#### TPM (Trusted Platform Module)
- **Model Properties**:
  - `trusted_platform_module_enabled: Optional[bool]`
  - `tpm_key_protector: Optional[str]`
- **Expected Sources**: 
  - `Msvm_SecuritySettingData` or `Msvm_KeyProtector`

### 3. Boot Settings
- **Model Property**: `primary_boot_device: Optional[str]`
- **Description**: Primary boot device or boot order
- **Expected Sources**: 
  - `Msvm_VirtualSystemSettingData` (BootOrder)
  - `Msvm_BootSourceSettingData`

### 4. Host Actions

#### Recovery Action
- **Model Property**: `host_recovery_action: Optional[HostRecoveryAction]`
- **Description**: Action when host recovers (none, resume, always-start)
- **Expected Source**: `Msvm_VirtualSystemSettingData`

#### Stop Action
- **Model Property**: `host_stop_action: Optional[HostStopAction]`
- **Description**: Action when host stops (save, stop, shut-down)
- **Expected Source**: `Msvm_VirtualSystemSettingData`

### 5. Integration Services (6 properties)
- **Model Properties**:
  - `integration_services_shutdown: Optional[bool]`
  - `integration_services_time: Optional[bool]`
  - `integration_services_data_exchange: Optional[bool]`
  - `integration_services_heartbeat: Optional[bool]`
  - `integration_services_vss_backup: Optional[bool]`
  - `integration_services_guest_services: Optional[bool]`
- **Expected Sources**: Individual component classes:
  - `Msvm_ShutdownComponent`
  - `Msvm_TimeSyncComponent`
  - `Msvm_KvpExchangeComponent`
  - `Msvm_HeartbeatComponent`
  - `Msvm_VssIntegrationComponent`
  - `Msvm_GuestServiceInterfaceComponent`

## Discovery Script Usage

The `Discover-CimProperties.ps1` script performs automated discovery of these missing properties.

### Running the Discovery Script

```powershell
# Run on a Hyper-V host with VMs

# Automatic VM selection (uses first running VM)
.\Discover-CimProperties.ps1

# Specify a test VM
.\Discover-CimProperties.ps1 -VmName "test-vm-01"

# Export to JSON for programmatic processing
.\Discover-CimProperties.ps1 -OutputFormat Json | Out-File discovery-results.json

# Export to CSV for analysis in Excel
.\Discover-CimProperties.ps1 -OutputFormat Csv
```

### What the Script Does

1. **Selects a Test VM**: Either specified or automatically selects first available
2. **Queries CIM Classes**: Tests multiple candidate classes for each property
3. **Extracts Properties**: Lists all available properties on each class
4. **Records Mappings**: Documents the exact property names and sample values
5. **Measures Performance**: Times each query to identify bottlenecks
6. **Generates Recommendations**: Provides implementation guidance

### Expected Output Structure

```json
{
  "Timestamp": "2025-12-14T10:30:00.000Z",
  "TestVM": {
    "Name": "test-vm-01",
    "Id": "12345678-1234-1234-1234-123456789ABC",
    "State": "Running",
    "Generation": 2
  },
  "Discoveries": [
    {
      "Category": "Dynamic Memory",
      "PropertyName": "dynamic_memory_buffer",
      "CimClass": "Msvm_MemorySettingData",
      "CimProperty": "TargetMemoryBuffer",
      "SampleValue": 20,
      "InstanceIdPattern": "Microsoft:{VM_GUID}\\...",
      "Notes": "Memory buffer percentage for dynamic memory"
    }
    // ... more discoveries
  ],
  "PerformanceMetrics": [
    {
      "Description": "Msvm_MemorySettingData query",
      "DurationMs": 45,
      "Success": true,
      "ResultCount": 1
    }
    // ... more metrics
  ]
}
```

## Implementation Pattern

Once the discovery script identifies the correct CIM classes and properties, implement collection using this pattern:

### 1. Batch Query for All VMs

```powershell
# Query once for all VMs
$settings = Get-CimInstance -Namespace root\virtualization\v2 `
    -ClassName Msvm_VirtualSystemSettingData `
    -ErrorAction SilentlyContinue |
    Where-Object { $_.VirtualSystemType -eq 'Microsoft:Hyper-V:System:Realized' }
```

### 2. Index by VM GUID

```powershell
$settingsByVmGuid = @{}
foreach ($setting in $settings) {
    $vmGuid = $setting.VirtualSystemIdentifier.ToUpper()
    $settingsByVmGuid[$vmGuid] = $setting
}
```

### 3. Extract Properties During Merge Phase

```powershell
foreach ($vmGuid in $vmDataByGuid.Keys) {
    $vmData = $vmDataByGuid[$vmGuid]
    
    # Get pre-indexed settings
    $settings = $settingsByVmGuid[$vmGuid]
    
    if ($settings) {
        # Extract and store properties
        $vmData.AutomaticRecoveryAction = $settings.AutomaticRecoveryAction
        $vmData.AutomaticShutdownAction = $settings.AutomaticShutdownAction
    }
}
```

### 4. Map Enum Values

```powershell
# Create enum mapping tables
$recoveryActionMap = @{
    2 = 'none'           # None
    3 = 'resume'         # Restart
    4 = 'always-start'   # AlwaysStartup
}

$shutdownActionMap = @{
    2 = 'stop'           # TurnOff
    3 = 'save'           # Save
    4 = 'shut-down'      # ShutDown
}

# Apply mapping
$vmInfo.HostRecoveryAction = $recoveryActionMap[[int]$settings.AutomaticRecoveryAction]
$vmInfo.HostStopAction = $shutdownActionMap[[int]$settings.AutomaticShutdownAction]
```

## Integration Services Implementation Pattern

Integration services require a different pattern since each service is a separate component class:

```powershell
# Define the component mapping
$integrationComponents = @{
    'Msvm_ShutdownComponent'              = 'Shutdown'
    'Msvm_TimeSyncComponent'              = 'Time'
    'Msvm_KvpExchangeComponent'           = 'DataExchange'
    'Msvm_HeartbeatComponent'             = 'Heartbeat'
    'Msvm_VssIntegrationComponent'        = 'VssBackup'
    'Msvm_GuestServiceInterfaceComponent' = 'GuestServices'
}

# Batch query each component type
$integrationServicesByVm = @{}
foreach ($className in $integrationComponents.Keys) {
    try {
        $components = Get-CimInstance -Namespace root\virtualization\v2 `
            -ClassName $className `
            -ErrorAction SilentlyContinue
        
        foreach ($component in $components) {
            $vmGuid = $component.SystemName.ToUpper()
            if (-not $integrationServicesByVm.ContainsKey($vmGuid)) {
                $integrationServicesByVm[$vmGuid] = @{}
            }
            
            $serviceName = $integrationComponents[$className]
            # EnabledState: 2=Enabled, 3=Disabled, 6=Enabled but Offline
            $enabled = $component.EnabledState -eq 2
            $integrationServicesByVm[$vmGuid][$serviceName] = $enabled
        }
    }
    catch {
        $result.Warnings += "Integration service query failed for $className"
    }
}

# Apply to VM data during merge
foreach ($vmGuid in $vmDataByGuid.Keys) {
    $vmData = $vmDataByGuid[$vmGuid]
    
    if ($integrationServicesByVm.ContainsKey($vmGuid)) {
        $services = $integrationServicesByVm[$vmGuid]
        $vmData.IntegrationServicesShutdown = $services['Shutdown']
        $vmData.IntegrationServicesTime = $services['Time']
        $vmData.IntegrationServicesDataExchange = $services['DataExchange']
        $vmData.IntegrationServicesHeartbeat = $services['Heartbeat']
        $vmData.IntegrationServicesVssBackup = $services['VssBackup']
        $vmData.IntegrationServicesGuestServices = $services['GuestServices']
    }
}
```

## Performance Considerations

1. **Batch Everything**: Query each class once for all VMs
2. **Index Results**: Store in hashtables by VM GUID for O(1) lookup
3. **Parallel Queries**: Integration service queries can run in parallel if needed
4. **Error Handling**: Some properties may not exist on all VMs (Gen1 vs Gen2, etc.)
5. **Property Access**: Access properties only once and cache the value

## Testing Strategy

1. **Run Discovery Script**: On multiple hosts with different VM configurations
2. **Compare Results**: Test with Gen1, Gen2, clustered, non-clustered VMs
3. **Validate Mappings**: Compare discovered values with `Get-VM` output
4. **Performance Test**: Measure query times with 10, 50, 100+ VMs
5. **Edge Cases**: Test VMs with missing/disabled features

## Next Steps

1. Run `Discover-CimProperties.ps1` on test hosts
2. Document exact property names and enum values
3. Implement batch queries in `Inventory.Collect.ps1`
4. Add enum mapping tables
5. Update output schema with new properties
6. Test performance with large VM counts
7. Update Python API models to match new schema
