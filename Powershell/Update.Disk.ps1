function Invoke-ProvisioningUpdateDisk {
    <#
    .SYNOPSIS
        Update disk properties.
    
    .DESCRIPTION
        Accepts a partial resource_spec with only fields to update.
        Currently supports expanding disk size only (Hyper-V limitation).
        Queries current disk state and applies only provided changes.
    
    .PARAMETER ResourceSpec
        Hashtable containing vm_id, resource_id (disk ID), and optional:
        - disk_size_gb: int (can only expand, not shrink)
    
    .OUTPUTS
        Hashtable with update results
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$ResourceSpec
    )

    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    # Extract identifiers
    $vmId = $ResourceSpec['vm_id']
    $resourceId = $ResourceSpec['resource_id']
    
    if (-not $vmId -or -not $resourceId) {
        throw "vm_id and resource_id are required for disk update"
    }

    # Get VM
    $vm = Get-VM | Where-Object { $_.Id.ToString() -eq $vmId }
    if (-not $vm) {
        throw "VM with ID '$vmId' not found"
    }

    # Get disk
    $disk = Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Id -eq $resourceId }
    if (-not $disk) {
        throw "Disk with ID '$resourceId' not found on VM"
    }

    $diskPath = $disk.Path
    if (-not $diskPath) {
        throw "Disk has no path (passthrough disk?)"
    }

    if (-not (Test-Path -LiteralPath $diskPath -PathType Leaf)) {
        throw "Disk file not found: $diskPath"
    }

    $updates = @()
    $warnings = @()

    # Disk size update (expand only)
    if ($ResourceSpec.ContainsKey('disk_size_gb')) {
        $newSizeGb = [int]$ResourceSpec['disk_size_gb']
        $newSizeBytes = [uint64]($newSizeGb * 1GB)
        
        $vhd = Get-VHD -Path $diskPath
        $currentSizeBytes = $vhd.Size
        $currentSizeGb = [math]::Round($currentSizeBytes / 1GB, 2)
        
        if ($newSizeBytes -lt $currentSizeBytes) {
            throw "Cannot shrink disk from ${currentSizeGb}GB to ${newSizeGb}GB. Hyper-V does not support disk shrinking."
        }
        elseif ($newSizeBytes -eq $currentSizeBytes) {
            $updates += "Disk size already ${newSizeGb}GB (no change)"
        }
        else {
            # Check VM state - resize may require VM off depending on disk type and VM generation
            $vmState = $vm.State
            $requiresVmOff = $false
            
            # For Gen 1 VMs or IDE-attached disks, VM must be off
            if ($vm.Generation -eq 1) {
                $requiresVmOff = $true
            }
            elseif ($disk.ControllerType -eq 'IDE') {
                $requiresVmOff = $true
            }
            
            if ($requiresVmOff -and $vmState -ne 'Off') {
                throw "VM must be powered off to resize this disk (Gen 1 VM or IDE controller). Current state: $vmState"
            }
            
            # Perform resize
            try {
                Resize-VHD -Path $diskPath -SizeBytes $newSizeBytes
                $updates += "Disk expanded: ${currentSizeGb}GB -> ${newSizeGb}GB"
            }
            catch {
                throw "Failed to resize disk: $_"
            }
            
            # Note about in-guest partition expansion
            if ($vmState -eq 'Running') {
                $warnings += "Disk expanded successfully. You may need to extend the partition inside the guest OS to use the new space."
            }
        }
    }

    # Build result
    $result = @{
        vm_id = $vmId
        resource_id = $resourceId
        disk_path = $diskPath
        updates_applied = $updates
        warnings = $warnings
    }

    if ($updates.Count -eq 0 -and $warnings.Count -eq 0) {
        $result['message'] = 'No changes needed - all properties already match requested values'
    }
    elseif ($updates.Count -gt 0) {
        $result['message'] = "Applied $($updates.Count) update(s)"
    }

    return $result
}
