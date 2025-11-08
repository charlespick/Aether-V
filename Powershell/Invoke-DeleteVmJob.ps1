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

    function Normalize-FileSystemPath {
        [CmdletBinding()]
        param(
            [Parameter()][AllowNull()][string]$Path
        )

        if ([string]::IsNullOrWhiteSpace($Path)) {
            return $null
        }

        try {
            $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
            if ($resolved -and $resolved.ProviderPath) {
                return $resolved.ProviderPath
            }
        }
        catch {
            try {
                return [System.IO.Path]::GetFullPath($Path)
            }
            catch {
                return $Path
            }
        }

        return $Path
    }

    function Find-AncestorFolderByLeafName {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$VmName
        )

        $current = $Path
        while ($current) {
            $leaf = Split-Path -Path $current -Leaf
            if ($leaf -and $leaf.Equals($VmName, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $current
            }

            $parent = Split-Path -Path $current -Parent
            if ([string]::IsNullOrWhiteSpace($parent) -or $parent.Equals($current, [System.StringComparison]::OrdinalIgnoreCase)) {
                break
            }

            $current = $parent
        }

        return $null
    }

    function Get-VmDirectoryCleanupPlan {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][object]$Vm,
            [Parameter()][string[]]$DiskPaths
        )

        $vmName = $Vm.Name
        if ([string]::IsNullOrWhiteSpace($vmName)) {
            return $null
        }

        $candidatePaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

        if ($Vm.ConfigurationLocation) {
            $normalized = Normalize-FileSystemPath -Path $Vm.ConfigurationLocation
            if ($normalized) { [void]$candidatePaths.Add($normalized) }
        }

        if ($Vm.Path) {
            $normalizedVmPath = Normalize-FileSystemPath -Path $Vm.Path
            if ($normalizedVmPath) { [void]$candidatePaths.Add($normalizedVmPath) }
        }

        foreach ($diskPath in $DiskPaths) {
            if ([string]::IsNullOrWhiteSpace($diskPath)) {
                continue
            }

            try {
                $parent = Split-Path -Path $diskPath -Parent
            }
            catch {
                $parent = $null
            }

            if ($parent) {
                $normalizedParent = Normalize-FileSystemPath -Path $parent
                if ($normalizedParent) {
                    [void]$candidatePaths.Add($normalizedParent)
                }
            }
        }

        $vmHomeFolder = $null
        foreach ($path in $candidatePaths) {
            $candidateHome = Find-AncestorFolderByLeafName -Path $path -VmName $vmName
            if ($candidateHome) {
                $vmHomeFolder = $candidateHome
                break
            }
        }

        if (-not $vmHomeFolder) {
            foreach ($diskPath in $DiskPaths) {
                if ([string]::IsNullOrWhiteSpace($diskPath)) {
                    continue
                }

                try {
                    $diskParent = Split-Path -Path $diskPath -Parent
                }
                catch {
                    $diskParent = $null
                }

                if ($diskParent) {
                    $vmHomeFolder = Normalize-FileSystemPath -Path $diskParent
                    if ($vmHomeFolder) {
                        break
                    }
                }
            }
        }

        if (-not $vmHomeFolder -and $Vm.Path) {
            $vmHomeFolder = Normalize-FileSystemPath -Path $Vm.Path
        }

        if (-not $vmHomeFolder) {
            return $null
        }

        $hypervRootFolder = $null
        try {
            $hypervRootFolder = Split-Path -Path $vmHomeFolder -Parent
            if ($hypervRootFolder) {
                $hypervRootFolder = Normalize-FileSystemPath -Path $hypervRootFolder
            }
        }
        catch {
            $hypervRootFolder = $null
        }

        $targetSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        [void]$targetSet.Add($vmHomeFolder)

        if ($hypervRootFolder) {
            [void]$targetSet.Add($hypervRootFolder)
        }

        $virtualMachinesFolder = $null
        $homeExists = Test-Path -LiteralPath $vmHomeFolder -PathType Container
        if ($homeExists) {
            $virtualMachinesCandidate = Join-Path -Path $vmHomeFolder -ChildPath 'Virtual Machines'
            if (Test-Path -LiteralPath $virtualMachinesCandidate -PathType Container) {
                $virtualMachinesFolder = Normalize-FileSystemPath -Path $virtualMachinesCandidate
            }
            else {
                try {
                    $childDirectories = Get-ChildItem -LiteralPath $vmHomeFolder -Directory -Force -ErrorAction Stop
                    foreach ($directory in $childDirectories) {
                        if ($directory.Name.Equals('Virtual Machines', [System.StringComparison]::OrdinalIgnoreCase)) {
                            $virtualMachinesFolder = $directory.FullName
                        }
                        [void]$targetSet.Add($directory.FullName)
                    }
                }
                catch {
                    Write-Host "Unable to enumerate child directories for '$vmHomeFolder': $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }

            if (-not $virtualMachinesFolder -and (Test-Path -LiteralPath $virtualMachinesCandidate -PathType Container)) {
                $virtualMachinesFolder = Normalize-FileSystemPath -Path $virtualMachinesCandidate
            }

            if ($virtualMachinesFolder) {
                [void]$targetSet.Add($virtualMachinesFolder)
            }

            try {
                $subdirectories = Get-ChildItem -LiteralPath $vmHomeFolder -Directory -Recurse -Force -ErrorAction Stop
                foreach ($subdirectory in $subdirectories) {
                    [void]$targetSet.Add($subdirectory.FullName)
                }
            }
            catch {
                Write-Host "Unable to enumerate recursive directories for '$vmHomeFolder': $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }

        $cleanupTargets = @()
        foreach ($entry in $targetSet) {
            if ($entry) {
                $cleanupTargets += $entry
            }
        }

        if ($cleanupTargets.Count -eq 0) {
            return $null
        }

        $orderedTargets = $cleanupTargets | Sort-Object { $_.Length } -Descending -Unique

        $isoCleanupTargets = New-Object 'System.Collections.Generic.List[string]'
        if ($vmHomeFolder) {
            $isoCleanupTargets.Add($vmHomeFolder) | Out-Null
        }
        if ($hypervRootFolder -and $hypervRootFolder -ne $vmHomeFolder) {
            $isoCleanupTargets.Add($hypervRootFolder) | Out-Null
        }

        return [pscustomobject]@{
            HomeFolder = $vmHomeFolder
            HypervRoot = $hypervRootFolder
            VirtualMachinesFolder = $virtualMachinesFolder
            Targets = $orderedTargets
            IsoTargets = $isoCleanupTargets.ToArray()
        }
    }

    function Invoke-DirectoryCleanupPlan {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][psobject]$CleanupPlan,
            [int]$MaxAttempts = 5,
            [int]$DelaySeconds = 5
        )

        if (-not $CleanupPlan -or -not $CleanupPlan.Targets) {
            return
        }

        $targets = @($CleanupPlan.Targets)
        if ($targets.Count -eq 0) {
            return
        }

        Write-Host "Beginning empty directory cleanup for VM home folder." 

        for ($attempt = 1; $attempt -le [math]::Max(1, $MaxAttempts); $attempt++) {
            Write-Host "Empty directory cleanup attempt $attempt/$MaxAttempts."

            $remainingEmptyTargets = New-Object 'System.Collections.Generic.List[string]'

            foreach ($target in $targets) {
                if ([string]::IsNullOrWhiteSpace($target)) {
                    continue
                }

                if (-not (Test-Path -LiteralPath $target -PathType Container)) {
                    continue
                }

                $items = @()
                try {
                    $items = @(Get-ChildItem -LiteralPath $target -Force -ErrorAction Stop)
                }
                catch {
                    Write-Host "Unable to inspect directory '$target': $($_.Exception.Message)" -ForegroundColor Yellow
                    continue
                }

                if ($items.Count -gt 0) {
                    continue
                }

                Write-Host "Removing empty directory '$target'."
                try {
                    Remove-Item -LiteralPath $target -Force -ErrorAction Stop
                }
                catch {
                    Write-Host "Failed to remove directory '$target': $($_.Exception.Message)" -ForegroundColor Yellow
                }

                Start-Sleep -Milliseconds 200

                if (Test-Path -LiteralPath $target -PathType Container) {
                    $postItems = @(Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue)
                    if (-not $postItems -or $postItems.Count -eq 0) {
                        $remainingEmptyTargets.Add($target) | Out-Null
                    }
                }
            }

            if ($remainingEmptyTargets.Count -eq 0) {
                Write-Host "Empty directory cleanup completed successfully." -ForegroundColor Green
                return
            }

            if ($attempt -lt $MaxAttempts) {
                Write-Host "Waiting $DelaySeconds seconds before retrying empty directory cleanup." -ForegroundColor Yellow
                Start-Sleep -Seconds $DelaySeconds
            }
            else {
                break
            }
        }

        $stillEmpty = @()
        foreach ($target in $targets) {
            if ([string]::IsNullOrWhiteSpace($target)) {
                continue
            }

            if (-not (Test-Path -LiteralPath $target -PathType Container)) {
                continue
            }

            $items = @(Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue)
            if (-not $items -or $items.Count -eq 0) {
                $stillEmpty += $target
            }
        }

        if ($stillEmpty.Count -gt 0) {
            throw "Unable to remove empty directories after $MaxAttempts attempts: $($stillEmpty -join ', ')"
        }

        Write-Host "Directory cleanup completed with remaining non-empty folders." -ForegroundColor Yellow
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

        $cleanupPlan = Get-VmDirectoryCleanupPlan -Vm $vm -DiskPaths $diskPaths
        if ($cleanupPlan) {
            if ($cleanupPlan.HomeFolder) {
                Write-Host "Identified VM home folder: '$($cleanupPlan.HomeFolder)'."
            }
            if ($cleanupPlan.HypervRoot) {
                Write-Host "Identified Hyper-V root folder: '$($cleanupPlan.HypervRoot)'."
            }
            if ($cleanupPlan.VirtualMachinesFolder) {
                Write-Host "Identified VM 'Virtual Machines' folder: '$($cleanupPlan.VirtualMachinesFolder)'."
            }
        }
        else {
            Write-Host "Unable to determine a complete folder cleanup plan for VM '$VMName'." -ForegroundColor Yellow
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

        $isoCleanupFolders = @()
        if ($cleanupPlan -and $cleanupPlan.IsoTargets) {
            $isoCleanupFolders += $cleanupPlan.IsoTargets
        }
        elseif ($vm.Path) {
            $isoCleanupFolders += $vm.Path
            try {
                $parentFolder = Split-Path -Path $vm.Path -Parent
                if ($parentFolder) {
                    $isoCleanupFolders += $parentFolder
                }
            }
            catch {
                # Ignore errors determining fallback parent path
            }
        }

        if (-not $cleanupPlan) {
            Write-Host "Unable to determine full cleanup plan for VM '$VMName'; using fallback ISO cleanup." -ForegroundColor Yellow
        }

        foreach ($folder in ($isoCleanupFolders | Sort-Object -Unique)) {
            Remove-ProvisioningIsos -Folder $folder
        }

        Write-Host "Unregistering VM '$VMName' from Hyper-V."
        Remove-VM -Name $VMName -Force -Confirm:$false -ErrorAction Stop

        $removalDeadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $removalDeadline) {
            $existingVm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
            if (-not $existingVm) {
                break
            }

            Start-Sleep -Seconds 1
        }

        $existingVm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
        if ($existingVm) {
            throw "VM '$VMName' is still registered after removal attempt."
        }

        Start-Sleep -Seconds 3

        if ($cleanupPlan) {
            try {
                Invoke-DirectoryCleanupPlan -CleanupPlan $cleanupPlan -MaxAttempts 5 -DelaySeconds 5
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
