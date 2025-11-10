param(
    [Parameter(Mandatory = $false)]
    [string]$ComputerName = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'

$result = @{
    Host = @{
        ComputerName = $ComputerName
        Timestamp    = (Get-Date).ToUniversalTime().ToString('o')
        ClusterName  = $null
        Warnings     = @()
    }
    VirtualMachines = @()
    Warnings        = @()
}

$highAvailabilityLookup = $null
$haLookupReliable = $false

try {
    try {
        $clusterNode = Get-ClusterNode -Name $ComputerName -ErrorAction Stop
        if ($clusterNode -and $clusterNode.Cluster) {
            $result.Host.ClusterName = $clusterNode.Cluster.Name
        }
    } catch {
        $result.Host.Warnings += "Cluster lookup failed: $($_.Exception.Message)"
    }

    if ($result.Host.ClusterName) {
        try {
            $highAvailabilityLookup = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
            $vmResources = Get-ClusterResource -Cluster $result.Host.ClusterName -ErrorAction Stop |
                Where-Object { $_ -and $_.ResourceType -eq 'Virtual Machine' }

            foreach ($resource in $vmResources) {
                if (-not $resource) { continue }
                $resourceName = $resource.Name
                if ([string]::IsNullOrWhiteSpace($resourceName)) { continue }

                $candidates = @()
                $trimmed = $resourceName.Trim()
                if ($trimmed) {
                    $candidates += $trimmed
                }

                if ($trimmed -match '^(?i)Virtual\s+Machine\s+(.+)$') {
                    $vmName = $Matches[1].Trim()
                    if ($vmName) {
                        $vmName = $vmName.Trim([char[]]@('"', "'"))
                    }
                    if (-not [string]::IsNullOrWhiteSpace($vmName)) {
                        $candidates += $vmName
                    }
                }

                foreach ($candidate in $candidates) {
                    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                        [void]$highAvailabilityLookup.Add($candidate)
                    }
                }
            }

            $haLookupReliable = $true
        } catch {
            $result.Host.Warnings += "Cluster resource lookup failed: $($_.Exception.Message)"
            $highAvailabilityLookup = $null
            $haLookupReliable = $false
        }
    } else {
        $highAvailabilityLookup = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        $haLookupReliable = $true
    }

    $vmProjection = Get-VM | Select-Object `
        Name, `
        @{Name='State';Expression={$_.State.ToString()}}, `
        ProcessorCount, `
        @{Name='MemoryGB';Expression={[math]::Round(($_.MemoryAssigned/1GB), 2)}}, `
        @{Name='CreationTime';Expression={
            if ($_.CreationTime) {
                $_.CreationTime.ToUniversalTime().ToString('o')
            } else {
                $null
            }
        }}, `
        @{Name='Generation';Expression={$_.Generation}}, `
        @{Name='Version';Expression={$_.Version}}, `
        @{Name='OperatingSystem';Expression={
            if ($_.OperatingSystem) {
                $_.OperatingSystem.ToString()
            } else {
                $null
            }
        }}, `
        @{Name='HighAvailability';Expression={
            if ($haLookupReliable -and $highAvailabilityLookup) {
                return $highAvailabilityLookup.Contains($_.Name)
            }
            if (-not $result.Host.ClusterName -and $haLookupReliable) {
                return $false
            }
            return $null
        }}

    $result.VirtualMachines = $vmProjection
} catch {
    $result.Host.Error = $_.Exception.Message
    $result.Host.ExceptionType = $_.Exception.GetType().FullName
    $result.Host.ScriptStackTrace = $_.ScriptStackTrace
    $result | ConvertTo-Json -Depth 6
    exit 1
}

$result | ConvertTo-Json -Depth 6
