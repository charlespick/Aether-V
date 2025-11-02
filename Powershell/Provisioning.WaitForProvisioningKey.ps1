function Invoke-ProvisioningWaitForProvisioningKey {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [int]$TimeoutSeconds = 300
    )

    function Set-ProvisioningKvpValue {
        param (
            [string]$Name,
            [string]$Value
        )

        $vmMgmt = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_VirtualSystemManagementService
        $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_ComputerSystem -Filter "ElementName='$VMName'"

        if (-not $vm) {
            throw "VM '$VMName' not found when updating KVP '$Name'."
        }

        $kvpSettings = ($vm.GetRelated("Msvm_KvpExchangeComponent")[0]).GetRelated("Msvm_KvpExchangeComponentSettingData")
        $hostItems = @($kvpSettings.HostExchangeItems)
        if ($hostItems.Count -gt 0) {
            $toRemove = @()
            foreach ($item in $hostItems) {
                $match = ([xml]$item).SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']")
                if ($match -ne $null) {
                    $toRemove += $item
                }
            }
            if ($toRemove.Count -gt 0) {
                $null = $vmMgmt.RemoveKvpItems($vm, $toRemove)
            }
        }

        $kvpDataItem = ([WMIClass][String]::Format("\\{0}\{1}:{2}",
                $vmMgmt.ClassPath.Server,
                $vmMgmt.ClassPath.NamespacePath,
                "Msvm_KvpExchangeDataItem")).CreateInstance()

        $kvpDataItem.Name = $Name
        $kvpDataItem.Data = $Value
        $kvpDataItem.Source = 0
        $null = $vmMgmt.AddKvpItems($vm, $kvpDataItem.PSBase.GetText(1))
    }

    function Get-ProvisioningKvpValue {
        param (
            [string]$Name
        )

        try {
            $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_ComputerSystem -Filter "ElementName='$VMName'" -ErrorAction Stop
            if (-not $vm) {
                return $null
            }

            $kvpComponent = $vm.GetRelated("Msvm_KvpExchangeComponent")
            if (-not $kvpComponent) {
                return $null
            }

            # Check if GuestExchangeItems property exists and is accessible
            $guestItems = $null
            try {
                $guestItems = $kvpComponent.GuestExchangeItems
            }
            catch {
                # GuestExchangeItems might not be available yet - this is normal during early boot
                return $null
            }

            if (-not $guestItems) {
                return $null
            }

            foreach ($item in $guestItems) {
                try {
                    if ([string]::IsNullOrEmpty($item)) {
                        continue
                    }

                    $xml = [xml]$item
                    $match = $xml.SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']")
                    if ($match -ne $null) {
                        $dataNode = $xml.SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Data']/VALUE/child::text()")
                        if ($dataNode) {
                            return $dataNode.Value
                        }
                    }
                }
                catch {
                    # Ignore individual item processing errors and continue
                    continue
                }
            }

            return $null
        }
        catch {
            # Log the error but don't fail - this is expected during guest startup
            return $null
        }
    }

    Write-Host "Preparing KVP channel for VM '$VMName'..."
    Set-ProvisioningKvpValue -Name "hlvmm.meta.host_provisioning_system_state" -Value "waitingforpublickey"

    # Use the globally detected version from the main script
    if (-not $global:ProvisioningScriptsVersion) {
        throw "FATAL: Provisioning scripts version not available. Version validation should have occurred in main script."
    }
    
    Set-ProvisioningKvpValue -Name "hlvmm.meta.version" -Value $global:ProvisioningScriptsVersion

    $intervalSeconds = 5
    $elapsed = 0

    Write-Host "Waiting up to $TimeoutSeconds seconds for guest provisioning readiness..."

    while ($elapsed -lt $TimeoutSeconds) {
        try {
            $guestState = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_system_state"
            if ($guestState -eq "waitingforaeskey") {
                Write-Host "Guest signalled readiness for AES key exchange." -ForegroundColor Green
                return $true
            }

            if ($elapsed % 30 -eq 0) {
                $publicKey = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_public_key"
                $statusMsg = "Elapsed: $elapsed s"
                if ($guestState) { $statusMsg += ", State: '$guestState'" }
                if ($publicKey) { $statusMsg += ", Public key received" }
                Write-Host $statusMsg
            }
        }
        catch {
            # Ignore all errors during the wait loop - guest might not be ready yet
            if ($elapsed % 60 -eq 0) {
                Write-Host "Elapsed: $elapsed s - Guest KVP not yet accessible (normal during boot)"
            }
        }

        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
    }

    try {
        $finalState = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_system_state"
        $finalPublicKey = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_public_key"
        $publicKeyState = if ($finalPublicKey) { "received" } else { "not received" }

        throw "Guest on VM '$VMName' did not reach 'waitingforaeskey' within $TimeoutSeconds seconds. Final state: '$finalState', Public key: $publicKeyState."
    }
    catch {
        # If we can't even get the final state, provide a simpler error message
        throw "Guest on VM '$VMName' did not reach 'waitingforaeskey' within $TimeoutSeconds seconds. KVP communication may not be available yet."
    }
}
