function Invoke-ProvisioningWaitForProvisioningKey {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$VMName,

        [int]$TimeoutSeconds = 600
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

        $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class Msvm_ComputerSystem -Filter "ElementName='$VMName'"
        if (-not $vm) {
            return $null
        }

        $kvpComponent = $vm.GetRelated("Msvm_KvpExchangeComponent")
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

    Write-Host "Preparing KVP channel for VM '$VMName'..."
    Set-ProvisioningKvpValue -Name "hlvmm.meta.host_provisioning_system_state" -Value "waitingforpublickey"

    $versionPath = Join-Path -Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -ChildPath "version"
    $scriptsVersion = if (Test-Path -LiteralPath $versionPath) {
        (Get-Content -LiteralPath $versionPath -Raw).Trim()
    }
    else {
        "unknown"
    }
    Set-ProvisioningKvpValue -Name "hlvmm.meta.version" -Value $scriptsVersion

    $intervalSeconds = 5
    $elapsed = 0

    Write-Host "Waiting up to $TimeoutSeconds seconds for guest provisioning readiness..."

    while ($elapsed -lt $TimeoutSeconds) {
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

        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
    }

    $finalState = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_system_state"
    $finalPublicKey = Get-ProvisioningKvpValue -Name "hlvmm.meta.guest_provisioning_public_key"
    $publicKeyState = if ($finalPublicKey) { "received" } else { "not received" }

    throw "Guest on VM '$VMName' did not reach 'waitingforaeskey' within $TimeoutSeconds seconds. Final state: '$finalState', Public key: $publicKeyState."
}
