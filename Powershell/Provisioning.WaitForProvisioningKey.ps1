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

        try {
            $vmMgmt = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_VirtualSystemManagementService
        }
        catch {
            throw "Failed to get VM management service: $_"
        }

        try {
            $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_ComputerSystem -Filter "ElementName='$VMName'"
        }
        catch {
            throw "Failed to get VM '$VMName': $_"
        }

        if (-not $vm) {
            throw "VM '$VMName' not found when updating KVP '$Name'."
        }

        try {
            $kvpComponent = $vm.GetRelated("Msvm_KvpExchangeComponent")[0]
            $kvpSettings = $kvpComponent.GetRelated("Msvm_KvpExchangeComponentSettingData")
            
            $rawHostItems = $kvpSettings.HostExchangeItems
            
            if ($null -eq $rawHostItems) {
                $hostItems = @()
            }
            elseif ($rawHostItems -is [Array]) {
                $hostItems = $rawHostItems
            }
            else {
                $hostItems = @($rawHostItems)
            }
        }
        catch {
            throw "Failed to get KVP settings: $_"
        }

        if ($hostItems -and $hostItems.Count -gt 0) {
            $toRemove = @()
            foreach ($item in $hostItems) {
                try {
                    $match = ([xml]$item).SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']")
                    if ($null -ne $match) {
                        $toRemove += $item
                    }
                }
                catch {
                    # Ignore individual item processing errors
                }
            }
            
            if ($toRemove -and $toRemove.Count -gt 0) {
                try {
                    $null = $vmMgmt.RemoveKvpItems($vm, $toRemove)
                }
                catch {
                    throw "Failed to remove existing KVP items: $_"
                }
            }
        }

        try {
            $kvpDataItem = ([WMIClass][String]::Format("\\{0}\{1}:{2}",
                    $vmMgmt.ClassPath.Server,
                    $vmMgmt.ClassPath.NamespacePath,
                    "Msvm_KvpExchangeDataItem")).CreateInstance()
        }
        catch {
            throw "Failed to create KVP data item: $_"
        }

        try {
            $kvpDataItem.Name = $Name
            $kvpDataItem.Data = $Value
            $kvpDataItem.Source = 0
        }
        catch {
            throw "Failed to set KVP item properties: $_"
        }

        try {
            $null = $vmMgmt.AddKvpItems($vm, $kvpDataItem.PSBase.GetText(1))
        }
        catch {
            throw "Failed to add KVP item '$Name': $_"
        }
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
                $rawGuestItems = $kvpComponent.GuestExchangeItems
                
                if ($null -eq $rawGuestItems) {
                    return $null
                }
                elseif ($rawGuestItems -is [Array]) {
                    $guestItems = $rawGuestItems
                }
                else {
                    $guestItems = @($rawGuestItems)
                }
            }
            catch {
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
                    if ($null -ne $match) {
                        $dataNode = $xml.SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Data']/VALUE/child::text()")
                        if ($dataNode) {
                            $value = $dataNode.Value
                            return $value
                        }
                    }
                }
                catch {
                    continue
                }
            }

            return $null
        }
        catch {
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

function Invoke-ProvisioningWaitForProvisioningCompletion {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [int]$TimeoutSeconds = 1800,

        [int]$PollIntervalSeconds = 5
    )

    if ($PollIntervalSeconds -le 0) {
        $PollIntervalSeconds = 5
    }

    Write-Host "Waiting for guest provisioning completion on VM '$VMName' (timeout: $TimeoutSeconds seconds)..."

    function Get-GuestKvpValue {
        param(
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

            $guestItems = $null
            try {
                $rawGuestItems = $kvpComponent.GuestExchangeItems

                if ($null -eq $rawGuestItems) {
                    return $null
                }
                elseif ($rawGuestItems -is [Array]) {
                    $guestItems = $rawGuestItems
                }
                else {
                    $guestItems = @($rawGuestItems)
                }
            }
            catch {
                return $null
            }

            foreach ($item in $guestItems) {
                try {
                    $xml = [xml]$item
                    $match = $xml.SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']")
                    if ($null -ne $match) {
                        $dataNode = $xml.SelectSingleNode("/INSTANCE/PROPERTY[@NAME='Data']/VALUE/child::text()")
                        if ($dataNode) {
                            return $dataNode.Value
                        }
                    }
                }
                catch {
                    continue
                }
            }

            return $null
        }
        catch {
            return $null
        }
    }

    $elapsed = 0
    $lastState = $null
    $lastError = $null

    while ($elapsed -le $TimeoutSeconds) {
        $guestState = $null
        $guestError = $null

        try {
            $guestState = Get-GuestKvpValue -Name "hlvmm.meta.guest_provisioning_system_state"
            $guestError = Get-GuestKvpValue -Name "hlvmm.meta.guest_provisioning_error"
        }
        catch {
            # Ignore transient read errors; the guest may still be booting
        }

        if ($guestState -ne $lastState -or $guestError -ne $lastError) {
            $stateDisplay = if ($guestState) { $guestState } else { '<unknown>' }
            $statusMessage = "Guest state: '$stateDisplay'"
            if ($guestError) {
                $statusMessage += ", Error: '$guestError'"
            }
            Write-Host $statusMessage
            $lastState = $guestState
            $lastError = $guestError
        }

        if ($guestState -eq 'provisioningapplied') {
            Write-Host "Guest signalled provisioning completion."
            return
        }

        if ($guestState -eq 'provisioningfailed') {
            $errorSummary = if ($guestError) { $guestError } else { '<unspecified>' }
            throw "Guest provisioning failed on VM '$VMName'. Guest summary: $errorSummary"
        }

        Start-Sleep -Seconds $PollIntervalSeconds
        $elapsed += $PollIntervalSeconds
    }

    $finalState = $null
    $finalError = $null
    try {
        $finalState = Get-GuestKvpValue -Name "hlvmm.meta.guest_provisioning_system_state"
        $finalError = Get-GuestKvpValue -Name "hlvmm.meta.guest_provisioning_error"
    }
    catch {
        # Ignore errors when capturing final state for timeout message
    }

    $errorSummary = if ($finalError) { $finalError } else { '<unspecified>' }
    throw "Guest on VM '$VMName' did not report provisioning completion within $TimeoutSeconds seconds. Last state: '$finalState'. Guest summary: $errorSummary"
}
