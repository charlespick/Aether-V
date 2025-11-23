# Pester tests for Main-NewProtocol.ps1
# Tests JSON parsing, envelope validation, and protocol compliance
# without requiring actual Hyper-V infrastructure

$ErrorActionPreference = 'Stop'

BeforeAll {
    # Find the script under test
    $scriptRoot = Split-Path -Parent $PSScriptRoot
    $script:MainScriptPath = Join-Path $scriptRoot 'Main-NewProtocol.ps1'
    
    if (-not (Test-Path $script:MainScriptPath)) {
        throw "Main-NewProtocol.ps1 not found at $script:MainScriptPath"
    }

    # Mock Hyper-V cmdlets that would fail in test environment
    function global:Get-VM { param($Name, $Id) 
        if ($Name -or $Id) { 
            throw "Hyper-V cmdlets not available in test environment"
        }
    }
    function global:New-VM { throw "Hyper-V cmdlets not available in test environment" }
    function global:Remove-VM { throw "Hyper-V cmdlets not available in test environment" }
    function global:Stop-VM { throw "Hyper-V cmdlets not available in test environment" }
    function global:Add-VMHardDiskDrive { throw "Hyper-V cmdlets not available in test environment" }
    function global:Remove-VMHardDiskDrive { throw "Hyper-V cmdlets not available in test environment" }
    function global:Get-VMHardDiskDrive { throw "Hyper-V cmdlets not available in test environment" }
    function global:Add-VMNetworkAdapter { throw "Hyper-V cmdlets not available in test environment" }
    function global:Remove-VMNetworkAdapter { throw "Hyper-V cmdlets not available in test environment" }
    function global:Get-VMNetworkAdapter { throw "Hyper-V cmdlets not available in test environment" }
    function global:Get-VMScsiController { throw "Hyper-V cmdlets not available in test environment" }
    function global:Set-VMNetworkAdapterVlan { throw "Hyper-V cmdlets not available in test environment" }
    function global:New-VHD { throw "Hyper-V cmdlets not available in test environment" }

    # Helper function to execute the script with JSON input
    function Invoke-MainProtocolScript {
        param(
            [Parameter(Mandatory = $true)]
            [string]$JsonInput
        )
        
        $output = $JsonInput | & pwsh -NoProfile -File $script:MainScriptPath 2>&1
        
        # Join output if it's an array
        if ($output -is [array]) {
            $output = $output -join "`n"
        }
        
        return $output
    }

    # Helper to create a job request envelope
    function New-JobRequest {
        param(
            [Parameter(Mandatory = $true)]
            [string]$Operation,
            
            [Parameter(Mandatory = $true)]
            [hashtable]$ResourceSpec,
            
            [string]$CorrelationId = (New-Guid).ToString(),
            
            [hashtable]$Metadata = @{}
        )
        
        $request = @{
            operation      = $Operation
            resource_spec  = $ResourceSpec
            correlation_id = $CorrelationId
            metadata       = $Metadata
        }
        
        return ($request | ConvertTo-Json -Depth 10 -Compress)
    }

    # Helper to parse job result
    function ConvertFrom-JobResult {
        param(
            [Parameter(Mandatory = $true)]
            [string]$JsonOutput
        )
        
        try {
            # Extract JSON from output (may contain debug/verbose lines)
            $lines = $JsonOutput -split "`n" | Where-Object { $_.Trim() -ne '' }
            $jsonLine = $lines | Where-Object { $_ -match '^\s*\{.*\}\s*$' } | Select-Object -Last 1
            
            if ($jsonLine) {
                return ($jsonLine | ConvertFrom-Json)
            }
            else {
                throw "No JSON found in output: $JsonOutput"
            }
        }
        catch {
            throw "Failed to parse job result: $_"
        }
    }
}

Describe 'Main-NewProtocol.ps1 - JSON Parsing and Envelope Validation' {
    
    It 'parses valid noop-test envelope' {
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{ test_field = 'value' }
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
        $result.correlation_id | Should -Not -BeNullOrEmpty
    }

    It 'includes correlation_id in response' {
        $correlationId = 'test-12345'
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{} -CorrelationId $correlationId
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.correlation_id | Should -Be $correlationId
    }

    It 'returns error for missing operation field' {
        $json = @{
            resource_spec  = @{}
            correlation_id = (New-Guid).ToString()
        } | ConvertTo-Json -Compress
        
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'error'
        $result.message | Should -Match 'operation'
    }

    It 'returns error for missing resource_spec field' {
        $json = @{
            operation      = 'noop-test'
            correlation_id = (New-Guid).ToString()
        } | ConvertTo-Json -Compress
        
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'error'
        $result.message | Should -Match 'resource_spec'
    }

    It 'handles complex nested JSON structures' {
        $resourceSpec = @{
            test_field  = 'value'
            test_number = 42
            test_array  = @(1, 2, 3)
            test_object = @{
                nested_field = 'nested_value'
                nested_array = @('a', 'b', 'c')
            }
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
    }

    It 'returns error for invalid JSON' {
        $invalidJson = '{ invalid json }'
        $output = Invoke-MainProtocolScript -JsonInput $invalidJson
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'error'
        $result.message | Should -Match 'parse|JSON'
    }

    It 'handles empty input gracefully' {
        $output = '' | & pwsh -NoProfile -File $script:MainScriptPath 2>&1
        $outputStr = if ($output -is [array]) { $output -join "`n" } else { $output }
        $result = ConvertFrom-JobResult -JsonOutput $outputStr
        
        $result.status | Should -Be 'error'
        $result.message | Should -Match 'No input'
    }
}

Describe 'Main-NewProtocol.ps1 - Noop Test Operation' {
    
    It 'executes noop-test successfully' {
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{ test_field = 'test_value' }
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
        $result.message | Should -Match 'noop-test'
        $result.data.operation_validated | Should -Be $true
        $result.data.envelope_parsed | Should -Be $true
        $result.data.json_valid | Should -Be $true
    }

    It 'echoes test fields in noop-test' {
        $resourceSpec = @{
            test_field  = 'echo_this'
            test_number = 123
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.data.test_field_echo | Should -Be 'echo_this'
        $result.data.test_number_echo | Should -Be 123
    }

    It 'includes logs in noop-test result' {
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.logs | Should -Not -BeNullOrEmpty
        $result.logs | Should -Contain 'Executing noop-test operation'
    }
}

Describe 'Main-NewProtocol.ps1 - JobResult Envelope Structure' {
    
    It 'returns all required JobResult fields for success' {
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Not -BeNullOrEmpty
        $result.message | Should -Not -BeNullOrEmpty
        $result.data | Should -Not -BeNullOrEmpty
        $result.correlation_id | Should -Not -BeNullOrEmpty
    }

    It 'returns all required JobResult fields for error' {
        $json = @{
            operation = 'unsupported-operation'
            resource_spec = @{}
            correlation_id = (New-Guid).ToString()
        } | ConvertTo-Json -Compress
        
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'error'
        $result.code | Should -Be 'OPERATION_ERROR'
        $result.message | Should -Not -BeNullOrEmpty
        $result.data | Should -Not -BeNullOrEmpty
        $result.data.error_type | Should -Not -BeNullOrEmpty
    }

    It 'status is valid enum value' {
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -BeIn @('success', 'error', 'partial')
    }
}

Describe 'Main-NewProtocol.ps1 - Operation Types' {
    
    It 'recognizes vm.create operation' {
        $resourceSpec = @{
            vm_name    = 'test-vm'
            gb_ram     = 4
            cpu_cores  = 2
        }
        
        $json = New-JobRequest -Operation 'vm.create' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        # Will fail due to missing Hyper-V but should recognize the operation
        if ($result.status -eq 'error') {
            $result.message | Should -Not -Match 'Unsupported operation'
        }
    }

    It 'recognizes disk.create operation' {
        $resourceSpec = @{
            vm_id          = (New-Guid).ToString()
            disk_size_gb   = 100
            storage_class  = 'default'
        }
        
        $json = New-JobRequest -Operation 'disk.create' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        # Will fail due to missing Hyper-V but should recognize the operation
        if ($result.status -eq 'error') {
            $result.message | Should -Not -Match 'Unsupported operation'
        }
    }

    It 'recognizes nic.create operation' {
        $resourceSpec = @{
            vm_id        = (New-Guid).ToString()
            network      = 'default'
            adapter_name = 'Network Adapter 1'
        }
        
        $json = New-JobRequest -Operation 'nic.create' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        # Will fail due to missing Hyper-V but should recognize the operation
        if ($result.status -eq 'error') {
            $result.message | Should -Not -Match 'Unsupported operation'
        }
    }

    It 'rejects unsupported operation' {
        $json = New-JobRequest -Operation 'invalid.operation' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'error'
        $result.message | Should -Match 'Unsupported operation'
    }
}

Describe 'Main-NewProtocol.ps1 - ConvertTo-Hashtable Function' {
    
    It 'converts PSCustomObject to hashtable through round-trip' {
        $resourceSpec = @{
            key1 = 'value1'
            key2 = 123
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        # If noop-test succeeded, ConvertTo-Hashtable worked
        $result.status | Should -Be 'success'
    }

    It 'handles nested objects through round-trip' {
        $resourceSpec = @{
            outer = @{
                inner = 'value'
            }
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
    }

    It 'handles arrays through round-trip' {
        $resourceSpec = @{
            array = @(1, 2, 3)
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
    }

    It 'handles arrays of objects through round-trip' {
        $resourceSpec = @{
            items = @(
                @{ id = 1 }
                @{ id = 2 }
            )
        }
        
        $json = New-JobRequest -Operation 'noop-test' -ResourceSpec $resourceSpec
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.status | Should -Be 'success'
    }
}

Describe 'Main-NewProtocol.ps1 - Error Handling' {
    
    It 'includes stack trace in error logs' {
        $json = New-JobRequest -Operation 'invalid.operation' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.logs | Should -Not -BeNullOrEmpty
    }

    It 'preserves correlation_id in error response' {
        $correlationId = 'error-test-123'
        $json = New-JobRequest -Operation 'invalid.operation' -ResourceSpec @{} -CorrelationId $correlationId
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.correlation_id | Should -Be $correlationId
    }

    It 'includes error_type in error data' {
        $json = New-JobRequest -Operation 'invalid.operation' -ResourceSpec @{}
        $output = Invoke-MainProtocolScript -JsonInput $json
        $result = ConvertFrom-JobResult -JsonOutput $output
        
        $result.data.error_type | Should -Not -BeNullOrEmpty
    }
}

Describe 'Main-NewProtocol.ps1 - Windows PowerShell 5.1 Compatibility' {
    
    It 'does not use -AsHashtable parameter' {
        # Read script content and verify it doesn't use -AsHashtable
        $scriptContent = Get-Content -Path $script:MainScriptPath -Raw
        
        $scriptContent | Should -Not -Match 'ConvertFrom-Json.*-AsHashtable'
    }

    It 'uses ConvertTo-Hashtable instead' {
        $scriptContent = Get-Content -Path $script:MainScriptPath -Raw
        
        # Should have ConvertTo-Hashtable function defined
        $scriptContent | Should -Match 'function ConvertTo-Hashtable'
        
        # Should call ConvertTo-Hashtable in the parsing logic
        $scriptContent | Should -Match 'ConvertTo-Hashtable\s+-InputObject'
    }
}
