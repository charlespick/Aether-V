$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptRoot = Split-Path -Parent $here
$scriptPath = Join-Path $scriptRoot 'Inventory.Collect.ps1'

Describe 'Inventory.Collect.ps1' {
    It 'captures cluster name and VM statistics when commands succeed' {
        Mock Get-ClusterNode -ParameterFilter { $Name -eq 'HOST1' } {
            [pscustomobject]@{ Cluster = [pscustomobject]@{ Name = 'ClusterA' } }
        }

        $creationTime = [datetime]'2024-01-01T00:00:00Z'
        Mock Get-VM {
            @(
                [pscustomobject]@{
                    Name = 'vm-01'
                    State = 'Running'
                    ProcessorCount = 4
                    MemoryAssigned = 2147483648
                    CreationTime = $creationTime
                    Generation = 2
                    Version = '10.0'
                    OperatingSystem = 'Windows Server'
                }
            )
        }

        $json = & $scriptPath -ComputerName 'HOST1'
        $result = $json | ConvertFrom-Json

        $result.Host.ComputerName | Should -Be 'HOST1'
        $result.Host.ClusterName | Should -Be 'ClusterA'
        $result.VirtualMachines.Count | Should -Be 1
        $vm = $result.VirtualMachines[0]
        $vm.Name | Should -Be 'vm-01'
        $vm.State | Should -Be 'Running'
        $vm.MemoryGB | Should -Be 2
        $vm.ProcessorCount | Should -Be 4
        $vm.Generation | Should -Be 2
        $vm.OperatingSystem | Should -Be 'Windows Server'
    }

    It 'records a warning when cluster lookup fails but continues processing' {
        Mock Get-ClusterNode { throw [System.Exception]::new('boom') }
        Mock Get-VM { @() }

        $json = & $scriptPath -ComputerName 'HOST1'
        $result = $json | ConvertFrom-Json

        $result.Host.Warnings | Should -Not -BeNullOrEmpty
        $result.VirtualMachines.Count | Should -Be 0
    }
}
