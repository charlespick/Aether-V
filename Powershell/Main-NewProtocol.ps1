# Main-NewProtocol.ps1
# Phase 2: New protocol stub entry point
#
# This script accepts a JSON job envelope via STDIN and returns a JSON job result.
# It is a placeholder implementation that echoes back a success result without
# performing any actual operations.
#
# Expected input envelope format:
# {
#   "operation": "vm.create",
#   "resource_spec": { ... },
#   "correlation_id": "uuid",
#   "metadata": { ... }
# }
#
# Output result format:
# {
#   "status": "success",
#   "message": "Operation completed (stub)",
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

        # Phase 2 stub: Just echo back success with the operation info
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
