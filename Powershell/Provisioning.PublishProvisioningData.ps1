function Invoke-ProvisioningPublishProvisioningData {
    [CmdletBinding()]
    param (
        [string]$GuestV4IpAddr,
        [string]$GuestV4CidrPrefix,
        [string]$GuestV4DefaultGw,
        [string]$GuestV4Dns1,
        [string]$GuestV4Dns2,
        [string]$GuestNetDnsSuffix,
        [string]$GuestDomainJoinTarget,
        [string]$GuestDomainJoinUid,
        [string]$GuestDomainJoinOU,
        [string]$AnsibleSshUser,
        [string]$AnsibleSshKey,

        [Parameter(Mandatory = $true)]
        [string]$GuestLaUid,

        [Parameter(Mandatory = $true)]
        [string]$GuestHostName
    )

    $GuestLaPw = $env:GuestLaPw
    if (-not $GuestLaPw) {
        throw "GuestLaPw is mandatory and must be set in the environment variable 'GuestLaPw'."
    }
    $GuestDomainJoinPw = $env:GuestDomainJoinPw

    if ($GuestV4IpAddr -or $GuestV4CidrPrefix -or $GuestV4DefaultGw -or $GuestV4Dns1 -or $GuestV4Dns2) {
        if (-not $GuestV4IpAddr -or -not $GuestV4CidrPrefix -or -not $GuestV4DefaultGw -or -not $GuestV4Dns1 -or -not $GuestV4Dns2) {
            throw "All IP settings (GuestV4IpAddr, GuestV4CidrPrefix, GuestV4DefaultGw, GuestV4Dns1, GuestV4Dns2) must be provided if any IP setting is specified."
        }
    }

    if ($GuestDomainJoinTarget -or $GuestDomainJoinUid -or $GuestDomainJoinPw -or $GuestDomainJoinOU) {
        if (-not $GuestDomainJoinTarget -or -not $GuestDomainJoinUid -or -not $GuestDomainJoinPw -or -not $GuestDomainJoinOU) {
            throw "All domain settings (GuestDomainJoinTarget, GuestDomainJoinUid, GuestDomainJoinPw, GuestDomainJoinOU) must be provided if any domain setting is specified."
        }
    }

    if ($AnsibleSshUser -or $AnsibleSshKey) {
        if (-not $AnsibleSshUser -or -not $AnsibleSshKey) {
            throw "Both Ansible SSH settings (AnsibleSshUser, AnsibleSshKey) must be provided if any Ansible SSH setting is specified."
        }
    }

    function Set-VMKeyValuePair {
        param (
            [Parameter(Mandatory = $true)]
            [string]$VMName,

            [Parameter(Mandatory = $true)]
            [string]$Name,

            [Parameter(Mandatory = $true)]
            [string]$Value
        )

        try {
            $VmMgmt = Get-WmiObject -Namespace root\virtualization\v2 -Class `
                Msvm_VirtualSystemManagementService
        }
        catch {
            throw "Failed to get VM management service: $_"
        }

        try {
            $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class `
                Msvm_ComputerSystem -Filter "ElementName='$VMName'"
        }
        catch {
            throw "Failed to get VM '$VMName': $_"
        }

        if (-not $vm) {
            throw "VM '$VMName' not found."
        }

        try {
            $kvpSettings = ($vm.GetRelated("Msvm_KvpExchangeComponent")[0]).GetRelated("Msvm_KvpExchangeComponentSettingData")
            $hostItems = @($kvpSettings.HostExchangeItems)
        }
        catch {
            throw "Failed to get KVP settings: $_"
        }

        if ($hostItems.Count -gt 0) {
            $toRemove = @()

            foreach ($item in $hostItems) {
                $match = ([xml]$item).SelectSingleNode(
                    "/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']"
                )
                if ($match -ne $null) {
                    $toRemove += $item
                }
            }

            if ($toRemove.Count -gt 0) {
                try {
                    $null = $VmMgmt.RemoveKvpItems($vm, $toRemove)
                }
                catch {
                    throw "Failed to remove existing KVP items: $_"
                }
            }
        }

        try {
            $kvpDataItem = ([WMIClass][String]::Format("\\{0}\{1}:{2}",
                    $VmMgmt.ClassPath.Server,
                    $VmMgmt.ClassPath.NamespacePath,
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
            throw "Failed to set KVP properties: $_"
        }

        try {
            $kvpXml = $kvpDataItem.PSBase.GetText(1)
            $VmMgmt.AddKvpItems($vm, $kvpXml)
        }
        catch {
            throw "Failed to add KVP item '$Name': $_"
        }
    }

    function Get-VMKeyValuePair {
        param (
            [Parameter(Mandatory = $true)]
            [string]$VMName,

            [Parameter(Mandatory = $true)]
            [string]$Name
        )

        $vm = Get-WmiObject -Namespace root\virtualization\v2 -Class `
            Msvm_ComputerSystem -Filter "ElementName='$VMName'"

        $directResult = $vm.GetRelated("Msvm_KvpExchangeComponent").GuestExchangeItems | % { `
                $GuestExchangeItemXml = ([XML]$_).SelectSingleNode(`
                    "/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$Name']")
            if ($GuestExchangeItemXml -ne $null) {
                $GuestExchangeItemXml.SelectSingleNode(`
                        "/INSTANCE/PROPERTY[@NAME='Data']/VALUE/child::text()").Value
            }
        }

        if ($directResult) {
            return $directResult
        }

        $chunks = @{}
        $chunkKeys = @()

        $allKvpItems = $vm.GetRelated("Msvm_KvpExchangeComponent").GuestExchangeItems

        for ($chunkIndex = 0; $chunkIndex -le 29; $chunkIndex++) {
            $chunkKey = "$Name._$chunkIndex"

            $chunkResult = $allKvpItems | % { `
                    $GuestExchangeItemXml = ([XML]$_).SelectSingleNode(`
                        "/INSTANCE/PROPERTY[@NAME='Name']/VALUE[child::text() = '$chunkKey']")
                if ($GuestExchangeItemXml -ne $null) {
                    $GuestExchangeItemXml.SelectSingleNode(`
                            "/INSTANCE/PROPERTY[@NAME='Data']/VALUE/child::text()").Value
                }
            }

            if ($chunkResult) {
                $chunks[$chunkIndex] = $chunkResult
                $chunkKeys += $chunkKey
            } else {
                break
            }
        }

        if ($chunks.Count -gt 0) {
            $reconstructedValue = ""

            for ($i = 0; $i -lt $chunks.Count; $i++) {
                if ($chunks.ContainsKey($i)) {
                    $reconstructedValue += $chunks[$i]
                }
            }

            return $reconstructedValue
        }

        return $null
    }

    function Publish-KvpEncryptedValue {
        param (
            [Parameter(Mandatory = $true)]
            [string]$VmName,

            [Parameter(Mandatory = $true)]
            [string]$Key,

            [Parameter(Mandatory = $true)]
            [string]$Value,

            [Parameter(Mandatory = $true)]
            [string]$AesKey
        )

        if ($Value.Length -le 100) {
            $aes = $null
            $encryptor = $null
            try {
                $aes = New-Object System.Security.Cryptography.AesManaged
                $aes.Key = [Convert]::FromBase64String($AesKey)
                $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
                $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
                $aes.GenerateIV()

                $iv = $aes.IV
                $encryptor = $aes.CreateEncryptor()

                $valueBytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
                $encryptedBytes = $encryptor.TransformFinalBlock($valueBytes, 0, $valueBytes.Length)

                $encryptedValue = [Convert]::ToBase64String($iv + $encryptedBytes)
            }
            catch {
                throw "Failed to encrypt the value: $_"
            }
            finally {
                if ($encryptor) {
                    $encryptor.Dispose()
                }
                if ($aes) {
                    $aes.Dispose()
                }
            }

            try {
                Set-VMKeyValuePair -VMName $VmName -Name $Key -Value $encryptedValue
                Write-Host "Successfully published encrypted value for key '$Key' on VM '$VmName'."
            }
            catch {
                throw "Failed to publish the encrypted value to the KVP: $_"
            }
        }
        else {
            Write-Host "Value for key '$Key' is $($Value.Length) characters, chunking into 100-character pieces..."

            $chunkCount = [Math]::Ceiling($Value.Length / 100.0)

            if ($chunkCount -gt 30) {
                throw "Value for key '$Key' is too long ($($Value.Length) characters). Maximum supported length is 3000 characters (30 chunks of 100 characters each)."
            }

            for ($i = 0; $i -lt $chunkCount; $i++) {
                $startIndex = $i * 100
                $chunkLength = [Math]::Min(100, $Value.Length - $startIndex)
                $chunk = $Value.Substring($startIndex, $chunkLength)
                $chunkKey = "$Key._$i"

                $aes = $null
                $encryptor = $null
                try {
                    $aes = New-Object System.Security.Cryptography.AesManaged
                    $aes.Key = [Convert]::FromBase64String($AesKey)
                    $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
                    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
                    $aes.GenerateIV()

                    $iv = $aes.IV
                    $encryptor = $aes.CreateEncryptor()

                    $chunkBytes = [System.Text.Encoding]::UTF8.GetBytes($chunk)
                    $encryptedChunkBytes = $encryptor.TransformFinalBlock($chunkBytes, 0, $chunkBytes.Length)

                    $encryptedChunk = [Convert]::ToBase64String($iv + $encryptedChunkBytes)
                }
                catch {
                    throw "Failed to encrypt chunk $i for key '$Key': $_"
                }
                finally {
                    if ($encryptor) {
                        $encryptor.Dispose()
                    }
                    if ($aes) {
                        $aes.Dispose()
                    }
                }

                try {
                    Set-VMKeyValuePair -VMName $VmName -Name $chunkKey -Value $encryptedChunk
                    Write-Host "Successfully published encrypted chunk $i for key '$Key' as '$chunkKey' on VM '$VmName'."
                }
                catch {
                    throw "Failed to publish encrypted chunk $i for key '$Key': $_"
                }
            }

            Write-Host "Successfully published $chunkCount chunks for key '$Key' on VM '$VmName'."
        }
    }

    function Get-RsaFromGuestProvisioningKey {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory)]
            [string]$PublicKeyBase64
        )

        $normalized = ($PublicKeyBase64 -replace '\s', '')
        $keyBytes = [Convert]::FromBase64String($normalized)

        try {
            $cngKey = [System.Security.Cryptography.CngKey]::Import(
                $keyBytes,
                [System.Security.Cryptography.CngKeyBlobFormat]::GenericPublicBlob
            )
            return [System.Security.Cryptography.RSACng]::new($cngKey)
        }
        catch {
            try {
                if ($keyBytes.Length -lt 10) {
                    throw "Key too short to be valid PKCS#1 RSA public key"
                }

                if ($keyBytes[0] -ne 0x30) {
                    throw "Not a valid DER SEQUENCE (expected 0x30, got 0x$($keyBytes[0].ToString('X2')))"
                }

                $offset = 1
                $lengthByte = $keyBytes[$offset]
                $offset++

                $totalLength = 0
                if (($lengthByte -band 0x80) -eq 0) {
                    $totalLength = $lengthByte
                }
                else {
                    $lengthBytes = $lengthByte -band 0x7F
                    if ($lengthBytes -gt 4) { throw "Length field too long" }

                    for ($i = 0; $i -lt $lengthBytes; $i++) {
                        $totalLength = ($totalLength -shl 8) + $keyBytes[$offset]
                        $offset++
                    }
                }

                if ($keyBytes[$offset] -ne 0x02) {
                    throw "Expected INTEGER tag for modulus (0x02), got 0x$($keyBytes[$offset].ToString('X2'))"
                }
                $offset++

                $modulusLengthByte = $keyBytes[$offset]
                $offset++

                $modulusLength = 0
                if (($modulusLengthByte -band 0x80) -eq 0) {
                    $modulusLength = $modulusLengthByte
                }
                else {
                    $modulusLengthBytes = $modulusLengthByte -band 0x7F
                    if ($modulusLengthBytes -gt 4) { throw "Modulus length field too long" }
                    for ($i = 0; $i -lt $modulusLengthBytes; $i++) {
                        $modulusLength = ($modulusLength -shl 8) + $keyBytes[$offset]
                        $offset++
                    }
                }

                $modulus = $keyBytes[$offset..($offset + $modulusLength - 1)]
                $offset += $modulusLength

                if ($modulus[0] -eq 0x00) {
                    $modulus = $modulus[1..($modulus.Length - 1)]
                }

                if ($keyBytes[$offset] -ne 0x02) {
                    throw "Expected INTEGER tag for exponent (0x02), got 0x$($keyBytes[$offset].ToString('X2'))"
                }
                $offset++

                $exponentLengthByte = $keyBytes[$offset]
                $offset++

                $exponentLength = 0
                if (($exponentLengthByte -band 0x80) -eq 0) {
                    $exponentLength = $exponentLengthByte
                }
                else {
                    $exponentLengthBytes = $exponentLengthByte -band 0x7F
                    if ($exponentLengthBytes -gt 4) { throw "Exponent length field too long" }
                    for ($i = 0; $i -lt $exponentLengthBytes; $i++) {
                        $exponentLength = ($exponentLength -shl 8) + $keyBytes[$offset]
                        $offset++
                    }
                }

                $exponent = $keyBytes[$offset..($offset + $exponentLength - 1)]

                $rsaParameters = [System.Security.Cryptography.RSAParameters]::new()
                $rsaParameters.Modulus = $modulus
                $rsaParameters.Exponent = $exponent

                $rsa = [System.Security.Cryptography.RSACng]::new()
                $rsa.ImportParameters($rsaParameters)
                return $rsa
            }
            catch {
                throw "Failed to import guest provisioning RSA public key: $_"
            }
        }
    }

    function ConvertTo-Base64Url {
        param(
            [byte[]]$Bytes
        )
        return ([Convert]::ToBase64String($Bytes).TrimEnd('=') -replace '\+', '-' -replace '/', '_')
    }

    function Publish-EncryptedSecret {
        param(
            [string]$VmName,
            [string]$Key,
            [string]$Secret,
            [string]$PublicKey
        )

        $rsa = Get-RsaFromGuestProvisioningKey -PublicKeyBase64 $PublicKey

        $aes = [System.Security.Cryptography.AesManaged]::new()
        $aes.KeySize = 256
        $aes.GenerateKey()
        $aesKeyBase64 = [Convert]::ToBase64String($aes.Key)

        Publish-KvpEncryptedValue -VmName $VmName -Key $Key -Value $Secret -AesKey $aesKeyBase64

        $encryptedAesKey = $rsa.Encrypt($aes.Key, [System.Security.Cryptography.RSAEncryptionPadding]::Pkcs1)
        $encodedKey = ConvertTo-Base64Url -Bytes $encryptedAesKey

        Set-VMKeyValuePair -VMName $VmName -Name "hlvmm.meta.aes_key" -Value $encodedKey
    }

    Write-Host "Waiting for guest provisioning public key..."
    $publicKey = $null
    for ($i = 0; $i -lt 120; $i++) {
        $publicKey = Get-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.meta.guest_provisioning_public_key"
        if ($publicKey) {
            break
        }
        Start-Sleep -Seconds 1
    }

    if (-not $publicKey) {
        throw "Guest provisioning public key not received from VM '$GuestHostName'."
    }

    Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_host_name" -Value $GuestHostName
    Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_la_uid" -Value $GuestLaUid

    Publish-EncryptedSecret -VmName $GuestHostName -Key "hlvmm.data.guest_la_pw" -Secret $GuestLaPw -PublicKey $publicKey

    if ($GuestV4IpAddr) {
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_v4_ip_addr" -Value $GuestV4IpAddr
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_v4_cidr_prefix" -Value $GuestV4CidrPrefix
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_v4_default_gw" -Value $GuestV4DefaultGw
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_v4_dns1" -Value $GuestV4Dns1
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_v4_dns2" -Value $GuestV4Dns2
    }

    if ($GuestNetDnsSuffix) {
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_net_dns_suffix" -Value $GuestNetDnsSuffix
    }

    if ($GuestDomainJoinTarget) {
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_domain_join_target" -Value $GuestDomainJoinTarget
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_domain_join_uid" -Value $GuestDomainJoinUid
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.guest_domain_join_ou" -Value $GuestDomainJoinOU
        Publish-EncryptedSecret -VmName $GuestHostName -Key "hlvmm.data.guest_domain_join_pw" -Secret $GuestDomainJoinPw -PublicKey $publicKey
    }

    if ($AnsibleSshUser) {
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.ansible_ssh_user" -Value $AnsibleSshUser
        Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.data.ansible_ssh_key" -Value $AnsibleSshKey
    }

    Set-VMKeyValuePair -VMName $GuestHostName -Name "hlvmm.meta.host_provisioning_system_state" -Value "publisheddetails"
    Write-Host "Provisioning data published for VM '$GuestHostName'."
}
