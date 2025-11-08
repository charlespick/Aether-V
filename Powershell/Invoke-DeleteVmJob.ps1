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

    function ConvertTo-Hashtable {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)]
            [object]$InputObject
        )

        if ($InputObject -is [System.Collections.IDictionary]) {
            $result = @{}
            foreach ($key in $InputObject.Keys) {
                $result[$key] = $InputObject[$key]
            }
            return $result
        }

        if ($InputObject -is [System.Management.Automation.PSObject]) {
            $result = @{}
            foreach ($property in $InputObject.PSObject.Properties) {
                $result[$property.Name] = $property.Value
            }
            return $result
        }

        throw "Expected a mapping object but received type '$($InputObject.GetType().FullName)'."
    }

    function Read-DeletionJobDefinition {
        [CmdletBinding()]
        param(
            [Parameter()]
            [AllowNull()]
            [object[]]$PipelinedInput
        )

        $rawInput = $null

        if ($PipelinedInput -and $PipelinedInput.Count -gt 0) {
            $buffer = @()
            foreach ($item in $PipelinedInput) {
                if ($null -eq $item) {
                    continue
                }

                if ($item -is [string]) {
                    $buffer += [string]$item
                    continue
                }

                if ($item -is [System.Collections.IDictionary] -or $item -is [System.Management.Automation.PSObject]) {
                    $buffer += ($item | ConvertTo-Json -Depth 16 -Compress)
                    continue
                }

                $buffer += [string]$item
            }

            if ($buffer.Count -gt 0) {
                $rawInput = [string]::Join([Environment]::NewLine, $buffer)
            }
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            $rawInput = [Console]::In.ReadToEnd()
        }

        if ([string]::IsNullOrWhiteSpace($rawInput)) {
            throw "No deletion job definition was supplied via pipeline or standard input."
        }

        try {
            $parsed = $rawInput | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Failed to parse deletion job definition as JSON: $($_.Exception.Message)"
        }

        return ConvertTo-Hashtable -InputObject $parsed
    }

    function Wait-ForVmState {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$VMName,
            [Parameter(Mandatory = $true)][string]$DesiredState,
            [int]$TimeoutSeconds = 60
        )

        $deadline = (Get-Date).AddSeconds([math]::Max(1, $TimeoutSeconds))
        while ((Get-Date) -lt $deadline) {
            try {
                $vm = Get-VM -Name $VMName -ErrorAction Stop
                if ($vm.State.ToString().Equals($DesiredState, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            catch {
                return $false
            }
            Start-Sleep -Seconds 1
        }
        return $false
    }

    function Remove-ClusterRoleIfPresent {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$VMName
        )

        if (-not (Get-Command -Name Get-ClusterGroup -ErrorAction SilentlyContinue)) {
            Write-Host "Failover clustering tools not available; skipping cluster cleanup." -ForegroundColor Yellow
            return
        }

        try {
            Import-Module -Name FailoverClusters -ErrorAction Stop | Out-Null
        }
        catch {
            Write-Host "Unable to import FailoverClusters module: $($_.Exception.Message)" -ForegroundColor Yellow
            return
        }

        try {
            $group = Get-ClusterGroup -Name $VMName -ErrorAction Stop
        }
        catch {
            return
        }

        if ($null -eq $group -or $group.GroupType -ne 'VirtualMachine') {
            return
        }

        Write-Host "Removing VM '$VMName' from failover cluster role '$($group.Name)'."
        Remove-ClusterGroup -Name $group.Name -Force -ErrorAction Stop

        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            try {
                Get-ClusterGroup -Name $group.Name -ErrorAction Stop | Out-Null
                Start-Sleep -Seconds 1
            }
            catch {
                Write-Host "Cluster role '$($group.Name)' removed successfully." -ForegroundColor Green
                return
            }
        }

        throw "Cluster role '$($group.Name)' is still present after removal request."
    }

    function Remove-FileWithVerification {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter()][string]$Description = 'file'
        )

        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Write-Host "$Description at '$Path' not found; skipping." -ForegroundColor Yellow
            return
        }

        Write-Host "Deleting $Description '$Path'."
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $Path) {
            throw "Failed to delete $Description at '$Path'."
        }
    }

    function Remove-EmptyDirectory {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$Path
        )

        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            return
        }

        $items = Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop
        if ($items.Count -gt 0) {
            return
        }

        Write-Host "Removing empty directory '$Path'."
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    }

    function Remove-ProvisioningIsos {
        [CmdletBinding()]
        param(
            [Parameter()][string]$Folder
        )

        if ([string]::IsNullOrWhiteSpace($Folder)) {
            return
        }

        if (-not (Test-Path -LiteralPath $Folder -PathType Container)) {
            return
        }

        $patterns = @('WindowsProvisioning*.iso', 'LinuxProvisioning*.iso', '*Provisioning*.iso')
        foreach ($pattern in $patterns) {
            Get-ChildItem -LiteralPath $Folder -Filter $pattern -File -ErrorAction SilentlyContinue |
                ForEach-Object {
                    Remove-FileWithVerification -Path $_.FullName -Description 'provisioning ISO'
                }
        }
    }

    function Invoke-DeleteVmWorkflow {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$VMName,
            [Parameter()][bool]$Force = $false
        )

        Write-Host "Beginning deletion workflow for VM '$VMName'."

        try {
            $vm = Get-VM -Name $VMName -ErrorAction Stop
        }
        catch {
            throw "Virtual machine '$VMName' was not found on this host."
        }

        if ($vm.State -eq 'Running' -and -not $Force) {
            throw "Virtual machine '$VMName' is running. Shut it down before deletion or enable force deletion."
        }

        if ($vm.State -eq 'Running' -and $Force) {
            Write-Host "Force deletion enabled. Turning off running VM '$VMName'."
            Stop-VM -VM $vm -Force -TurnOff -Confirm:$false -ErrorAction Stop
            if (-not (Wait-ForVmState -VMName $VMName -DesiredState 'Off' -TimeoutSeconds 120)) {
                throw "Timed out waiting for VM '$VMName' to power off."
            }
        }

        Remove-ClusterRoleIfPresent -VMName $VMName

        $hardDisks = @(Get-VMHardDiskDrive -VMName $VMName -ErrorAction SilentlyContinue)
        $diskPaths = @()
        foreach ($disk in $hardDisks) {
            if ($disk.Path) {
                $diskPaths += $disk.Path
            }
        }

        foreach ($disk in $hardDisks) {
            Write-Host "Detaching virtual hard disk '$($disk.Path)' from VM '$VMName'."
            Remove-VMHardDiskDrive -VMHardDiskDrive $disk -Confirm:$false -ErrorAction Stop
            Start-Sleep -Milliseconds 500
            $stillAttached = Get-VMHardDiskDrive -VMName $VMName -ErrorAction SilentlyContinue |
                Where-Object { $_.Path -eq $disk.Path }
            if ($stillAttached) {
                throw "Failed to detach VHD '$($disk.Path)' from VM '$VMName'."
            }
        }

        foreach ($path in $diskPaths) {
            Remove-FileWithVerification -Path $path -Description 'virtual hard disk'
        }

        $dvdDrives = @(Get-VMDvdDrive -VMName $VMName -ErrorAction SilentlyContinue)
        $isoPaths = @()
        foreach ($drive in $dvdDrives) {
            if ($drive.Path) {
                $isoPaths += $drive.Path
            }
        }

        foreach ($drive in $dvdDrives) {
            Write-Host "Removing DVD drive from VM '$VMName'."
            Remove-VMDvdDrive -VMDvdDrive $drive -ErrorAction Stop
            Start-Sleep -Milliseconds 300
            $stillAttached = Get-VMDvdDrive -VMName $VMName -ErrorAction SilentlyContinue |
                Where-Object { $_.Id -eq $drive.Id }
            if ($stillAttached) {
                throw "Failed to remove DVD drive from VM '$VMName'."
            }
        }

        foreach ($path in $isoPaths) {
            Remove-FileWithVerification -Path $path -Description 'ISO'
        }

        $candidateFolders = New-Object 'System.Collections.Generic.HashSet[string]'

        if ($vm.ConfigurationLocation) {
            try {
                $configItem = Get-Item -LiteralPath $vm.ConfigurationLocation -ErrorAction Stop
                if ($configItem -and $configItem.PSIsContainer) {
                    [void]$candidateFolders.Add($configItem.FullName)
                }
            }
            catch {
                # Ignore missing configuration directories
            }
        }

        if ($vm.Path) {
            try {
                $vmPathItem = Get-Item -LiteralPath $vm.Path -ErrorAction Stop
                if ($vmPathItem -and $vmPathItem.PSIsContainer) {
                    [void]$candidateFolders.Add($vmPathItem.FullName)
                }
            }
            catch {
                # Ignore missing VM paths
            }
        }

        foreach ($path in $diskPaths) {
            try {
                $folder = Split-Path -Path $path -Parent
                if ($folder) {
                    $folderItem = Get-Item -LiteralPath $folder -ErrorAction Stop
                    if ($folderItem -and $folderItem.PSIsContainer) {
                        [void]$candidateFolders.Add($folderItem.FullName)
                    }
                }
            }
            catch {
                # Ignore missing disk folders
            }
        }

        $candidateArray = @()
        foreach ($entry in $candidateFolders) {
            if ($entry) {
                $candidateArray += $entry
            }
        }

        $vmFolder = $null
        foreach ($folder in $candidateArray) {
            if ($folder -and (Split-Path -Path $folder -Leaf) -eq $VMName) {
                $vmFolder = $folder
                break
            }
        }
        if (-not $vmFolder -and $candidateArray.Count -gt 0) {
            $vmFolder = $candidateArray[0]
        }

        if ($vmFolder) {
            Remove-ProvisioningIsos -Folder $vmFolder
            $parentFolder = Split-Path -Path $vmFolder -Parent
            if ($parentFolder -and $parentFolder -ne $vmFolder) {
                Remove-ProvisioningIsos -Folder $parentFolder
            }
        }

        Write-Host "Unregistering VM '$VMName' from Hyper-V."
        Remove-VM -Name $VMName -Force -Confirm:$false -ErrorAction Stop

        $existingVm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
        if ($existingVm) {
            throw "VM '$VMName' is still registered after removal attempt."
        }

        if ($vmFolder) {
            try {
                Remove-EmptyDirectory -Path $vmFolder
                $parentFolder = Split-Path -Path $vmFolder -Parent
                if ($parentFolder -and $parentFolder -ne $vmFolder) {
                    Remove-EmptyDirectory -Path $parentFolder
                }
            }
            catch {
                Write-Host "Folder cleanup warning: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }

        Write-Host "Deletion workflow completed for VM '$VMName'." -ForegroundColor Green
    }

    try {
        $jobDefinition = Read-DeletionJobDefinition -PipelinedInput $script:CollectedInput
        $vmName = $jobDefinition['vm_name']
        if ([string]::IsNullOrWhiteSpace($vmName)) {
            throw "Deletion job definition missing required field 'vm_name'."
        }

        $forceDelete = $false
        if ($jobDefinition.ContainsKey('force')) {
            $forceDelete = [System.Convert]::ToBoolean($jobDefinition['force'])
        }

        if ($jobDefinition.ContainsKey('hyperv_host') -and $jobDefinition['hyperv_host']) {
            Write-Host "Target host reported by control plane: $($jobDefinition['hyperv_host'])."
        }

        Invoke-DeleteVmWorkflow -VMName $vmName -Force:$forceDelete
    }
    catch {
        Write-Error $_
        exit 1
    }
}
