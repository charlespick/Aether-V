function Invoke-ProvisioningCleanupIso {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [Parameter(Mandatory = $true)]
        [string]$IsoPath
    )

    Write-Host "Cleaning up provisioning ISO for VM '$VMName'..."

    # Get the VM
    $vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
    if (-not $vm) {
        Write-Warning "VM '$VMName' not found. Skipping ISO unmount, but will attempt to delete ISO file."
    }
    else {
        # Find and remove the DVD drive with the ISO attached
        $dvdDrives = Get-VMDvdDrive -VM $vm -ErrorAction SilentlyContinue
        $isoUnmounted = $false
        
        foreach ($drive in $dvdDrives) {
            if ($drive.Path -and (Test-Path -LiteralPath $drive.Path -PathType Leaf)) {
                $drivePath = $drive.Path
                
                # Check if this is our provisioning ISO
                if ($drivePath -eq $IsoPath) {
                    try {
                        # Force unmount by removing the DVD drive
                        Remove-VMDvdDrive -VMDvdDrive $drive -ErrorAction Stop
                        Write-Host "Unmounted and removed DVD drive with ISO: $IsoPath" -ForegroundColor Green
                        $isoUnmounted = $true
                    }
                    catch {
                        Write-Warning "Failed to remove DVD drive from VM '$VMName': $_. Will attempt to delete ISO anyway."
                    }
                }
            }
        }
        
        if (-not $isoUnmounted) {
            Write-Host "ISO was not mounted or already unmounted." -ForegroundColor Yellow
        }
    }

    # Delete the ISO file from storage
    if (Test-Path -LiteralPath $IsoPath -PathType Leaf) {
        try {
            # Wait a moment for any file locks to be released
            Start-Sleep -Seconds 2
            
            Remove-Item -LiteralPath $IsoPath -Force -ErrorAction Stop
            Write-Host "Deleted provisioning ISO: $IsoPath" -ForegroundColor Green
        }
        catch {
            Write-Warning "Failed to delete provisioning ISO at '$IsoPath': $_. The file may need manual cleanup."
        }
    }
    else {
        Write-Host "ISO file not found at '$IsoPath'. It may have already been deleted." -ForegroundColor Yellow
    }
}
