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

try {
    try {
        $clusterNode = Get-ClusterNode -Name $ComputerName -ErrorAction Stop
        if ($clusterNode -and $clusterNode.Cluster) {
            $result.Host.ClusterName = $clusterNode.Cluster.Name
        }
    } catch {
        $result.Host.Warnings += "Cluster lookup failed: $($_.Exception.Message)"
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
