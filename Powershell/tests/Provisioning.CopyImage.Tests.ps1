$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptRoot = Split-Path -Parent $here
. (Join-Path $scriptRoot 'Provisioning.CopyImage.ps1')

Describe 'Invoke-ProvisioningCopyImage' {
    BeforeAll {
        $script:removeClusterVolumeStub = $false
        if (-not (Get-Command -Name Get-ClusterSharedVolume -ErrorAction SilentlyContinue)) {
            function global:Get-ClusterSharedVolume { throw 'Get-ClusterSharedVolume should be mocked in tests.' }
            $script:removeClusterVolumeStub = $true
        }
    }

    AfterAll {
        if ($script:removeClusterVolumeStub) {
            Remove-Item Function:\Get-ClusterSharedVolume -ErrorAction SilentlyContinue
        }
    }

    It 'copies the image to the destination volume when prerequisites are met' {
        $diskImages = @(
            [pscustomobject]@{ FullName = 'C:\\ClusterStorage\\Volume1' },
            [pscustomobject]@{ FullName = 'C:\\ClusterStorage\\Volume2' }
        )

        Mock Get-ChildItem -ParameterFilter { $Path -eq 'C:\\ClusterStorage' } {
            $diskImages
        }

        Mock Test-Path -ParameterFilter { $Path -and $Path -like '*DiskImages' } {
            $true
        }

        $volume = [pscustomobject]@{
            Name = 'CSV01'
            SharedVolumeInfo = [pscustomobject]@{
                FriendlyVolumeName = 'C:\\ClusterStorage\\Volume1'
                Partition = [pscustomobject]@{ FreeSpace = 10GB }
            }
        }

        Mock Get-ClusterSharedVolume { @($volume) }

        Mock Test-Path -ParameterFilter { $LiteralPath -like '*golden.vhdx' -and $PathType -eq 'Leaf' } {
            $true
        }

        Mock Get-Item -ParameterFilter { $LiteralPath -like '*golden.vhdx' } {
            [pscustomobject]@{ Length = 5GB }
        }

        Mock New-Item { @{} }
        Mock Copy-Item {}

        $destination = Invoke-ProvisioningCopyImage -VMName 'vm-test' -ImageName 'golden'

        $expected = 'C:\\ClusterStorage\\Volume1\\Hyper-V\\vm-test'
        $destination | Should -Be $expected
        Assert-MockCalled Copy-Item -Exactly 1
        Assert-MockCalled New-Item -Exactly 1
    }

    It 'throws a helpful error when the golden image does not exist' {
        Mock Get-ChildItem -ParameterFilter { $Path -eq 'C:\\ClusterStorage' } {
            @([pscustomobject]@{ FullName = 'C:\\ClusterStorage\\Volume1' })
        }

        Mock Test-Path -ParameterFilter { $Path -and $Path -like '*DiskImages' } {
            $true
        }

        Mock Get-ClusterSharedVolume {
            @([pscustomobject]@{
                Name = 'CSV01'
                SharedVolumeInfo = [pscustomobject]@{
                    FriendlyVolumeName = 'C:\\ClusterStorage\\Volume1'
                    Partition = [pscustomobject]@{ FreeSpace = 10GB }
                }
            })
        }

        Mock Test-Path -ParameterFilter { $LiteralPath -like '*missing.vhdx' -and $PathType -eq 'Leaf' } {
            $false
        }

        { Invoke-ProvisioningCopyImage -VMName 'vm-test' -ImageName 'missing' } |
            Should -Throw "Golden image 'missing' was not found"
    }
}
