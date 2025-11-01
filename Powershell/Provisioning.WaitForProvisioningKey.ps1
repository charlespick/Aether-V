function Invoke-ProvisioningWaitForProvisioningKey {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [int]$TimeoutSeconds = 600
    )

    function Wait-ForVmRunningState {
        param(
            [string]$Name,
            [int]$Timeout
        )

        $pollInterval = 3
        $elapsed = 0
        $lastState = 'Unknown'

        while ($elapsed -lt $Timeout) {
            $vm = Get-VM -Name $Name -ErrorAction SilentlyContinue
            if ($vm) {
                if ($vm.State -eq 'Running') {
                    return $true
                }
                $lastState = $vm.State
            }
            else {
                $lastState = 'NotFound'
            }

            Start-Sleep -Seconds $pollInterval
            $elapsed += $pollInterval
        }

        throw "VM '$Name' did not reach the 'Running' state within $Timeout seconds (last observed state: '$lastState')."
    }

    function Wait-ForKvpExchangeComponent {
        param(
            [string]$Name,
            [int]$Timeout
        )

        $pollInterval = 3
        $elapsed = 0

        while ($elapsed -lt $Timeout) {
            $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_ComputerSystem -Filter "ElementName='$Name'"
            if ($vm) {
                $kvpComponent = $vm.GetRelated("Msvm_KvpExchangeComponent")
                if ($kvpComponent) {
                    return $vm
                }
            }

            Start-Sleep -Seconds $pollInterval
            $elapsed += $pollInterval
        }

        throw "The Hyper-V KVP exchange component for VM '$Name' did not become available within $Timeout seconds."
    }

    function Set-ProvisioningKvpValue {
        param (
            [string]$Name,
            [string]$Value,
            [System.Management.ManagementObject]$VmMgmt,
            [System.Management.ManagementObject]$VmObject
        )

        if (-not $VmMgmt) {
            throw "VirtualSystemManagementService instance is required when setting KVP '$Name'."
        }

        if (-not $VmObject) {
            throw "VM instance is required when setting KVP '$Name'."
        }

        $kvpComponents = $VmObject.GetRelated("Msvm_KvpExchangeComponent")
        if (-not $kvpComponents -or $kvpComponents.Count -eq 0) {
            throw "KVP exchange component was not available when attempting to set '$Name' on VM '$($VmObject.ElementName)'."
        }

        $kvpSettings = ($kvpComponents[0]).GetRelated("Msvm_KvpExchangeComponentSettingData")
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
                $null = $VmMgmt.RemoveKvpItems($VmObject, $toRemove)
            }
        }

        $kvpDataItem = ([WMIClass][String]::Format("\\{0}\{1}:{2}",
                $VmMgmt.ClassPath.Server,
                $VmMgmt.ClassPath.NamespacePath,
                "Msvm_KvpExchangeDataItem")).CreateInstance()

        $kvpDataItem.Name = $Name
        $kvpDataItem.Data = $Value
        $kvpDataItem.Source = 0
        $null = $VmMgmt.AddKvpItems($VmObject, $kvpDataItem.PSBase.GetText(1))
    }

    function Get-ProvisioningKvpValue {
        param (
            [string]$Name,
            [System.Management.ManagementObject]$VmObject
        )

        if (-not $VmObject) {
            return $null
        }

        $kvpComponent = $VmObject.GetRelated("Msvm_KvpExchangeComponent")
        if (-not $kvpComponent) {
            return $null
        }

        $guestItems = $kvpComponent.GuestExchangeItems
        foreach ($item in $guestItems) {
            try {
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
                Write-Warning "Error processing KVP item: $_"
            }
        }

        return $null
    }

    Write-Host "Verifying that VM '$VMName' is running before preparing KVP channel..."
    Wait-ForVmRunningState -Name $VMName -Timeout ([Math]::Min($TimeoutSeconds, 180))

    Write-Host "Waiting for Hyper-V KVP exchange component for VM '$VMName' to become available..."
    $vmObject = Wait-ForKvpExchangeComponent -Name $VMName -Timeout ([Math]::Min($TimeoutSeconds, 180))
    $vmMgmt = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_VirtualSystemManagementService

    Write-Host "Preparing KVP channel for VM '$VMName'..."
    Set-ProvisioningKvpValue -Name "hlvmm.meta.host_provisioning_system_state" -Value "waitingforpublickey" -VmMgmt $vmMgmt -VmObject $vmObject

    $scriptsVersionPath = Join-Path -Path $PSScriptRoot -ChildPath "scriptsversion"
    $scriptsVersion = if (Test-Path -LiteralPath $scriptsVersionPath) {
        Get-Content -LiteralPath $scriptsVersionPath -Raw
    } else {
        "unknown"
    }
    Set-ProvisioningKvpValue -Name "hlvmm.meta.version" -Value $scriptsVersion -VmMgmt $vmMgmt -VmObject $vmObject

    $intervalSeconds = 5
    $elapsed = 0

    Write-Host "Waiting up to $TimeoutSeconds seconds for guest provisioning readiness..."

    while ($elapsed -lt $TimeoutSeconds) {
        $guestState = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_system_state" -VmObject $vmObject
        if ($guestState -eq "waitingforaeskey") {
            Write-Host "Guest signalled readiness for AES key exchange." -ForegroundColor Green
            return $true
        }

        if ($elapsed % 30 -eq 0) {
            $publicKey = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_public_key" -VmObject $vmObject
            $statusMsg = "Elapsed: $elapsed s"
            if ($guestState) { $statusMsg += ", State: '$guestState'" }
            if ($publicKey) { $statusMsg += ", Public key received" }
            Write-Host $statusMsg
        }

        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
    }

    $finalState = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_system_state" -VmObject $vmObject
    $finalPublicKey = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_public_key" -VmObject $vmObject
    $publicKeyState = if ($finalPublicKey) { "received" } else { "not received" }

    throw "Guest on VM '$VMName' did not reach 'waitingforaeskey' within $TimeoutSeconds seconds. Final state: '$finalState', Public key: $publicKeyState."
}
