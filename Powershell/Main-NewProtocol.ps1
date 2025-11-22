# Main-NewProtocol.ps1
# Phase 3: New protocol entry point with noop-test implementation
#
# This script accepts a JSON job envelope via STDIN and returns a JSON job result.
# Phase 3 implements the "noop-test" operation as the first real operation.
# All other operations remain as stubs that echo back success.
#
# Expected input envelope format:
# {
#   "operation": "vm.create" | "noop-test",
#   "resource_spec": { ... },
#   "correlation_id": "uuid",
#   "metadata": { ... }
# }
#
# Output result format:
# {
#   "status": "success",
#   "message": "Operation completed",
#   "data": { ... },
#   "correlation_id": "uuid",
#   "logs": []
# }

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

    function Write-JobResult {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [ValidateSet('success', 'error', 'partial')]
            [string]$Status,

            [Parameter(Mandatory = $true)]
            [string]$Message,

            [Parameter()]
            [hashtable]$Data = @{},

            [Parameter()]
            [string]$Code = $null,

            [Parameter()]
            [string[]]$Logs = @(),

            [Parameter()]
            [string]$CorrelationId = $null
        )

        $result = @{
            status  = $Status
            message = $Message
            data    = $Data
        }

        if ($Code) {
            $result['code'] = $Code
        }

        if ($Logs) {
            $result['logs'] = $Logs
        }

        if ($CorrelationId) {
            $result['correlation_id'] = $CorrelationId
        }

        $json = $result | ConvertTo-Json -Depth 10 -Compress
        Write-Output $json
    }

    function Read-JobEnvelope {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null
        
        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $rawInput = $PipelinedInput -join "`n"
        }
        else {
            # Read from STDIN if no piped input
            $stdinLines = @()
            try {
                while ($null -ne ($line = [Console]::In.ReadLine())) {
                    $stdinLines += $line
                }
            }
            catch {
                # End of input
            }
            
            if ($stdinLines.Count -gt 0) {
                $rawInput = $stdinLines -join "`n"
            }
        }

        if (-not $rawInput -or $rawInput.Trim() -eq '') {
            throw 'No input received. Expected JSON job envelope via STDIN.'
        }

        try {
            $envelope = $rawInput | ConvertFrom-Json -AsHashtable -ErrorAction Stop
            return $envelope
        }
        catch {
            throw "Failed to parse JSON envelope: $_"
        }
    }

    # Main execution
    try {
        # Read and parse the job envelope
        $envelope = Read-JobEnvelope -PipelinedInput $script:CollectedInput

        # Validate required fields
        if (-not $envelope.ContainsKey('operation')) {
            throw 'Job envelope missing required field: operation'
        }

        if (-not $envelope.ContainsKey('resource_spec')) {
            throw 'Job envelope missing required field: resource_spec'
        }

        $operation = $envelope['operation']
        $resourceSpec = $envelope['resource_spec']
        $correlationId = $envelope['correlation_id']
        
        $logs = @()

        # Phase 3: Implement noop-test operation
        if ($operation -eq 'noop-test') {
            # Noop-test: Validate JSON parsing and envelope structure
            $logs += 'Executing noop-test operation'
            $logs += "Correlation ID: $correlationId"
            $logs += "Resource spec validated: $($resourceSpec.Keys.Count) fields"
            
            # Validate STDIN parsing worked correctly
            if ($null -eq $resourceSpec) {
                throw 'Resource spec is null - STDIN parsing failed'
            }
            
            # Validate JSON correctness
            if (-not ($resourceSpec -is [hashtable])) {
                throw 'Resource spec is not a hashtable - JSON parsing failed'
            }
            
            # Echo back some of the resource spec to verify round-trip
            $resultData = @{
                operation_validated = $true
                envelope_parsed     = $true
                json_valid          = $true
                correlation_id      = $correlationId
            }
            
            # Include any test fields from the resource spec
            if ($resourceSpec.ContainsKey('test_field')) {
                $resultData['test_field_echo'] = $resourceSpec['test_field']
            }
            if ($resourceSpec.ContainsKey('test_number')) {
                $resultData['test_number_echo'] = $resourceSpec['test_number']
            }
            
            $logs += 'Noop-test completed successfully'
            
            Write-JobResult `
                -Status 'success' `
                -Message 'Noop-test operation completed successfully' `
                -Data $resultData `
                -CorrelationId $correlationId `
                -Logs $logs
        }
        else {
            # All other operations remain as Phase 2 stubs
            $stubData = @{
                stub_operation   = $operation
                stub_received    = $true
                resource_spec_keys = @($resourceSpec.Keys)
            }

            # If it's a creation operation, add a fake ID
            if ($operation -match '\.(create|clone)$') {
                $stubData['created_id'] = [guid]::NewGuid().ToString()
            }

            # Return success result
            Write-JobResult `
                -Status 'success' `
                -Message "New protocol stub: $operation operation received and acknowledged" `
                -Data $stubData `
                -CorrelationId $correlationId `
                -Logs @(
                    "Received operation: $operation",
                    "Resource spec contains $($resourceSpec.Keys.Count) fields"
                )
        }
    }
    catch {
        # Return error result
        $errorMessage = $_.Exception.Message
        $errorData = @{
            error_type = $_.Exception.GetType().Name
        }

        Write-JobResult `
            -Status 'error' `
            -Message "Stub protocol error: $errorMessage" `
            -Data $errorData `
            -Code 'STUB_ERROR' `
            -Logs @($_.ScriptStackTrace)
    }
}
