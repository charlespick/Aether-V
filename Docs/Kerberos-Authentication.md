# Kerberos Authentication for WinRM

This document provides comprehensive guidance on configuring Kerberos authentication for WinRM in Aether-V, including why it's necessary, how to configure it, and how to migrate from legacy NTLM/Basic/CredSSP authentication.

## Why Kerberos is Required

Aether-V requires Kerberos authentication for several critical security and functionality reasons:

### 1. **Secure Double-Hop Operations**

Hyper-V cluster management requires "double-hop" authentication - the ability for credentials to be delegated from the Aether-V service through the Hyper-V host to additional resources like:
- Cluster Shared Volumes (CSV)
- Failover cluster objects
- Storage controllers
- Remote file shares

**NTLM and Basic authentication cannot support double-hop** because they don't provide credential delegation. Only Kerberos with constrained delegation enables secure credential forwarding.

### 2. **Cluster Management**

When managing Hyper-V failover clusters, operations like VM migration, cluster validation, and shared storage access require the service account to:
- Authenticate to the target Hyper-V node
- Access cluster resources using delegated credentials
- Perform operations on shared storage

Without Kerberos delegation, these operations will fail with "Access Denied" errors.

### 3. **Enhanced Security**

Kerberos provides superior security compared to NTLM:
- Mutual authentication (both client and server verify identities)
- Time-limited tickets reduce exposure window
- No password transmission over the network
- Protection against replay attacks
- Support for modern encryption algorithms (AES)

### 4. **Industry Best Practices**

Microsoft recommends disabling NTLM and CredSSP in favor of Kerberos:
- CredSSP has known security vulnerabilities and should be disabled
- NTLM is deprecated and lacks modern security features
- Kerberos is the only authentication method that supports constrained delegation

## Prerequisites

Before configuring Kerberos authentication:

1. **Active Directory Environment**
   - Domain controllers accessible from both Aether-V and Hyper-V hosts
   - Synchronized time across all systems (critical for Kerberos)
   - DNS properly configured for domain resolution

2. **Service Account**
   - Dedicated service account in Active Directory for Aether-V
   - Account should NOT have "Password never expires" set (security best practice)
   - Account needs appropriate permissions on Hyper-V hosts

3. **Network Configuration**
   - UDP/TCP port 88 (Kerberos) allowed between Aether-V and domain controllers
   - UDP/TCP port 88 allowed between Hyper-V hosts and domain controllers
   - WinRM port 5985 (HTTP) or 5986 (HTTPS) accessible on Hyper-V hosts

## Keytab Generation

A keytab file contains the Kerberos principal and encrypted keys needed for authentication without interactive login.

### Option 1: Using ktutil on Linux

```bash
# Start ktutil
ktutil

# Add entry for the service account
addent -password -p svc-aetherv@AD.EXAMPLE.COM -k 1 -e aes256-cts-hmac-sha1-96
# Enter the service account password when prompted

# Write the keytab file
wkt /tmp/aetherv.keytab

# Exit ktutil
quit

# Verify the keytab
klist -kt /tmp/aetherv.keytab

# Base64 encode for Aether-V configuration
base64 < /tmp/aetherv.keytab | tr -d '\n' > /tmp/aetherv.keytab.b64

# Securely delete the original keytab
shred -u /tmp/aetherv.keytab
```

### Option 2: Using Active Directory Tools (Windows)

```powershell
# On a domain-joined Windows machine with AD tools installed
# Run as domain administrator

# Export keytab for the service account
ktpass /princ svc-aetherv@AD.EXAMPLE.COM `
       /mapuser svc-aetherv@ad.example.com `
       /crypto AES256-SHA1 `
       /ptype KRB5_NT_PRINCIPAL `
       /pass * `
       /out C:\temp\aetherv.keytab

# Base64 encode the keytab
$keytabBytes = [System.IO.File]::ReadAllBytes("C:\temp\aetherv.keytab")
$keytabB64 = [Convert]::ToBase64String($keytabBytes)
$keytabB64 | Out-File C:\temp\aetherv.keytab.b64 -NoNewline

# Securely delete the original keytab
Remove-Item C:\temp\aetherv.keytab -Force
```

### Security Notes for Keytab Management

- **Never commit keytabs to source control**
- Store base64-encoded keytabs in secure secrets management (e.g., Kubernetes Secrets, Azure Key Vault)
- Rotate keytabs periodically (aligned with password rotation policy)
- Use restrictive file permissions (0600) if storing keytabs on disk
- Delete temporary keytab files after base64 encoding

## Configuring Resource-Based Constrained Delegation (RBCD)

RBCD is **required** for Aether-V's Kerberos double-hop authentication (S4U2Proxy). This allows the Aether-V service to obtain delegated credentials when connecting to Hyper-V hosts and performing operations that require access to cluster resources.

### Critical Understanding: Where to Configure RBCD

**IMPORTANT:** For Aether-V's S4U2Proxy to work, RBCD **MUST** be configured on the **Hyper-V host computer objects**, NOT on the Cluster Name Object (CNO).

When Aether-V connects to a Hyper-V host's HTTP/WSMAN service:
1. The KDC checks the **target service's account** (the host's computer object)
2. The KDC looks at `msDS-AllowedToActOnBehalfOfOtherIdentity` on the **host's computer object**
3. If the Aether-V service account's SID is in that attribute with proper rights, S4U2Proxy succeeds

**Do NOT configure RBCD on the CNO** - the CNO is not the target for Aether-V's WinRM connections to hosts.

### Step 1: Configure RBCD for Hyper-V Hosts

For each Hyper-V host, configure RBCD to allow the Aether-V service account to act on behalf of other identities:

```powershell
# Run on a domain controller or machine with AD PowerShell tools
# Replace placeholders with your actual values

# Replace with the sAMAccountName of your Aether-V service account
$ServiceAccount = "svc-aetherv"
$HyperVHost = "hyperv01"

# Get the service account and host computer objects
$ServicePrincipal = Get-ADUser -Identity $ServiceAccount
$HostComputer = Get-ADComputer $HyperVHost

# Configure RBCD - this is the CORRECT configuration for Aether-V's double-hop
# This sets msDS-AllowedToActOnBehalfOfOtherIdentity on the HOST
Set-ADComputer $HostComputer -PrincipalsAllowedToDelegateToAccount $ServicePrincipal

# Verify configuration - check that msDS-AllowedToActOnBehalfOfOtherIdentity is set
Get-ADComputer $HostComputer -Properties PrincipalsAllowedToDelegateToAccount, msDS-AllowedToActOnBehalfOfOtherIdentity |
    Select-Object Name, PrincipalsAllowedToDelegateToAccount
```

**What this does:**
- Sets the `msDS-AllowedToActOnBehalfOfOtherIdentity` attribute on the Hyper-V host's computer object
- The attribute contains a security descriptor with an ACE granting the Aether-V service account SID full control
- When Aether-V requests S4U2Proxy tickets to the host, the KDC checks this attribute and allows delegation

### Step 2: Repeat for All Hyper-V Hosts

**You MUST configure RBCD on every Hyper-V host** that Aether-V will manage. For clustered environments, this means every node in every cluster:

```powershell
# Example: Configure RBCD for all hosts in a cluster
$ServiceAccount = "svc-aetherv"
$ServicePrincipal = Get-ADUser -Identity $ServiceAccount

$HyperVHosts = @("hyperv01", "hyperv02", "hyperv03")

foreach ($HostName in $HyperVHosts) {
    $HostComputer = Get-ADComputer $HostName
    Set-ADComputer $HostComputer -PrincipalsAllowedToDelegateToAccount $ServicePrincipal
    Write-Host "Configured RBCD for $HostName"
}

# Verify all hosts
foreach ($HostName in $HyperVHosts) {
    Get-ADComputer $HostName -Properties PrincipalsAllowedToDelegateToAccount |
        Select-Object Name, PrincipalsAllowedToDelegateToAccount
}
```

### DO NOT Configure RBCD on the Cluster Name Object (CNO)

**Common Mistake:** Configuring `PrincipalsAllowedToDelegateToAccount` or `msDS-AllowedToActOnBehalfOfOtherIdentity` on the Cluster Name Object (CNO).

**Why this is wrong:**
- Aether-V connects to the **HOST's** WinRM service (e.g., `HTTP/hyperv01.domain.com`)
- The KDC validates S4U2Proxy requests against the **target service's account** (the host, not the CNO)
- RBCD on the CNO does not help Aether-V obtain delegated credentials to the hosts

**Correct configuration:** RBCD on **each Hyper-V host computer object**

### Automatic RBCD Verification

After the initial inventory synchronization completes, Aether-V automatically validates the RBCD configuration:

1. Resolves the service account's SID from Active Directory
2. For each discovered Hyper-V host (including cluster members):
   - Queries the host's computer object in AD
   - Reads `msDS-AllowedToActOnBehalfOfOtherIdentity` attribute
   - Parses the security descriptor to extract ACEs
   - Verifies the service account's SID has an Allow ACE with GenericAll rights

If any host is missing proper RBCD configuration, Aether-V displays an error in the system notification panel with specific remediation steps.

### Step 3: Configure Service Principal Names (SPNs)

Ensure proper SPNs are registered for Hyper-V hosts:

```powershell
# Verify SPNs for a Hyper-V host
setspn -L hyperv01

# Required SPNs (usually auto-registered):
# - HOST/hyperv01.ad.example.com
# - HOST/hyperv01
# - WSMAN/hyperv01.ad.example.com
# - WSMAN/hyperv01

# If missing, register manually (usually not needed):
setspn -S WSMAN/hyperv01.ad.example.com hyperv01$
setspn -S WSMAN/hyperv01 hyperv01$
```

## Aether-V Configuration

### Environment Variables

Configure the following environment variables for Kerberos authentication:

```bash
# Required: Kerberos principal for the service account
WINRM_KERBEROS_PRINCIPAL=svc-aetherv@AD.EXAMPLE.COM

# Required: Base64-encoded keytab file
WINRM_KEYTAB_B64=<base64-encoded-keytab-content>

# Optional: Override Kerberos realm (defaults to the realm segment of WINRM_KERBEROS_PRINCIPAL)
# WINRM_KERBEROS_REALM=AD.EXAMPLE.COM

# Optional: Override KDC server. When set the server writes a temporary krb5.conf so GSSAPI and kinit target the provided host.
# WINRM_KERBEROS_KDC=dc01.ad.example.com

# Standard WinRM settings
HYPERV_HOSTS=hyperv01.ad.example.com,hyperv02.ad.example.com
WINRM_PORT=5985
```

Use the service account's UPN for `WINRM_KERBEROS_PRINCIPAL` so it matches the keytab entry (for example `svc-aetherv@AD.EXAMPLE.COM`). If you instead supply a service SPN such as `HTTP/aetherv.example.com@AD.EXAMPLE.COM`, ensure that SPN is registered to the same account and included in the keytab.

### Realm detection and KDC overrides

Aether-V automatically derives the Kerberos realm from `WINRM_KERBEROS_PRINCIPAL` when
`WINRM_KERBEROS_REALM` is not supplied, so most deployments only need to set the
principal and keytab. If DNS lookups for the realm return the wrong KDC, supply
`WINRM_KERBEROS_KDC`—the server writes a temporary `krb5.conf` with the override so
both GSSAPI and the `kinit` fallback use the specified domain controller.

### Kubernetes Deployment

Update Kubernetes manifests to include Kerberos credentials:

**`server/k8s/configmap.yaml`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: aetherv-config
  namespace: aetherv
data:
  WINRM_KERBEROS_PRINCIPAL: "svc-aetherv@AD.EXAMPLE.COM"
  HYPERV_HOSTS: "hyperv01.ad.example.com,hyperv02.ad.example.com"
  WINRM_PORT: "5985"
```

**`server/k8s/secret.yaml`:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aetherv-secrets
  namespace: aetherv
type: Opaque
stringData:
  WINRM_KEYTAB_B64: "<base64-encoded-keytab>"
  OIDC_CLIENT_SECRET: "<oidc-secret>"
  SESSION_SECRET_KEY: "<session-secret>"
```

### Docker Compose

```yaml
version: '3.8'
services:
  aetherv:
    image: aetherv:latest
    environment:
      - WINRM_KERBEROS_PRINCIPAL=svc-aetherv@AD.EXAMPLE.COM
      - WINRM_KEYTAB_B64=${WINRM_KEYTAB_B64}
      - HYPERV_HOSTS=hyperv01.ad.example.com,hyperv02.ad.example.com
    env_file:
      - .env
```

## Migrating from Legacy Authentication

### Step 1: Audit Current Configuration

Check your current deployment for legacy authentication settings:

```bash
# Check environment variables
env | grep -E "WINRM_(USERNAME|PASSWORD|TRANSPORT)"

# Check Kubernetes ConfigMap
kubectl get configmap aetherv-config -n aetherv -o yaml | grep -E "WINRM_(USERNAME|PASSWORD|TRANSPORT)"

# Check Kubernetes Secret
kubectl get secret aetherv-secrets -n aetherv -o yaml | grep -E "WINRM_(USERNAME|PASSWORD|TRANSPORT)"
```

### Step 2: Generate Keytab

Follow the keytab generation instructions above to create a keytab for your service account.

### Step 3: Update Configuration

1. **Remove legacy variables:**
   ```bash
   # Remove from environment, ConfigMap, and Secrets:
   # - WINRM_USERNAME
   # - WINRM_PASSWORD
   # - WINRM_TRANSPORT
   ```

2. **Add Kerberos variables:**
   ```bash
   # Add to ConfigMap:
   WINRM_KERBEROS_PRINCIPAL=svc-aetherv@AD.EXAMPLE.COM
   
   # Add to Secret:
   WINRM_KEYTAB_B64=<base64-encoded-keytab>
   ```

### Step 4: Configure Delegation

Configure RBCD as described above for all Hyper-V hosts and cluster objects.

### Step 5: Test

Deploy the updated configuration and verify:

```bash
# Check application logs for successful Kerberos initialization
kubectl logs -n aetherv deployment/aetherv-server | grep -i kerberos

# Expected output:
# Initializing Kerberos authentication for principal: svc-aetherv@AD.EXAMPLE.COM
# Kerberos authentication initialized successfully

# Test WinRM connectivity
kubectl exec -it -n aetherv deployment/aetherv-server -- \
    python -c "from app.services.winrm_service import winrm_service; \
               winrm_service.execute_ps_command('hyperv01.ad.example.com', 'Get-VM')"
```

## Security Advisories

### 1. Disable CredSSP

If your environment previously used CredSSP, **disable it immediately** due to known security vulnerabilities:

```powershell
# On each Hyper-V host, run as administrator:
Set-Item WSMan:\localhost\Service\Auth\CredSSP -Value $false

# Disable CredSSP client as well
Set-Item WSMan:\localhost\Client\Auth\CredSSP -Value $false

# Verify
Get-Item WSMan:\localhost\Service\Auth\CredSSP
Get-Item WSMan:\localhost\Client\Auth\CredSSP
```

### 2. Disable NTLM (Optional but Recommended)

For maximum security, disable NTLM after confirming Kerberos works:

```powershell
# On each Hyper-V host:
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $false
Set-Item WSMan:\localhost\Service\Auth\Kerberos -Value $true

# Verify only Kerberos is enabled
Get-Item WSMan:\localhost\Service\Auth\* | Format-Table Name, Value
```

### 3. Time Synchronization

Kerberos requires time synchronization within 5 minutes (default). Ensure NTP is configured:

```bash
# On Linux (Aether-V container host):
timedatectl status

# Configure NTP if needed
sudo timedatectl set-ntp true

# On Windows (Hyper-V hosts):
w32tm /query /status
```

### 4. Keytab Rotation

Implement a keytab rotation policy:

- Rotate keytabs when the service account password changes
- Use automation (e.g., GitHub Actions secrets rotation) for Kubernetes deployments
- Store old keytabs briefly during rotation to allow graceful transition

### 5. Monitor Authentication

Monitor for authentication failures that might indicate issues:

```bash
# Check Aether-V logs for authentication errors
kubectl logs -n aetherv deployment/aetherv-server | grep -i "authentication\|kerberos"

# On Hyper-V hosts, check Security event log
Get-WinEvent -LogName Security -FilterXPath "*[System[(EventID=4768 or EventID=4769 or EventID=4771)]]" -MaxEvents 50
```

## Troubleshooting

### Issue: "Failed to initialize Kerberos"

**Symptoms:** Application fails to start with "Failed to initialize Kerberos" (may be followed by additional warning messages)

**Solutions:**
1. Verify keytab is properly base64-encoded
2. Check principal name matches exactly (case-sensitive, include @REALM)
3. Ensure keytab was generated for the correct principal
4. Verify time synchronization between all systems

### Issue: "Access Denied" during cluster operations

**Symptoms:** VM operations fail with access denied on cluster resources, or errors about delegation

**Solutions:**
1. **Verify RBCD is configured on Hyper-V HOSTS, not the CNO:**
   ```powershell
   # Check each host's RBCD configuration
   $ServiceAccount = "svc-aetherv"
   $HostName = "hyperv01"
   
   $ServicePrincipal = Get-ADUser -Identity $ServiceAccount
   $HostComputer = Get-ADComputer $HostName
   
   # Check if the service account is in PrincipalsAllowedToDelegateToAccount
   Get-ADComputer $HostComputer -Properties PrincipalsAllowedToDelegateToAccount |
       Select-Object Name, PrincipalsAllowedToDelegateToAccount
   ```

2. **Verify the service account SID is in the RBCD attribute:**
   ```powershell
   # Get the raw RBCD attribute
   $HostComputer = Get-ADComputer $HostName -Properties msDS-AllowedToActOnBehalfOfOtherIdentity
   
   # If this is $null or empty, RBCD is not configured
   if ($null -eq $HostComputer.'msDS-AllowedToActOnBehalfOfOtherIdentity') {
       Write-Host "RBCD not configured on $HostName - configure using Set-ADComputer"
   }
   ```

3. **Ensure SPNs are properly registered:**
   ```powershell
   setspn -L hyperv01
   # Should show WSMAN/hyperv01.domain.com and WSMAN/hyperv01
   ```

4. **DO NOT configure RBCD on the CNO** - it will not help Aether-V and may cause confusion

### Issue: "Resource-Based Constrained Delegation (RBCD) is not correctly configured"

**Symptoms:** Aether-V shows an error notification about missing RBCD configuration

**Solutions:**
1. **This error means the service account's SID is NOT in the host's msDS-AllowedToActOnBehalfOfOtherIdentity attribute**

2. **Configure RBCD on EACH Hyper-V host:**
   ```powershell
   $ServiceAccount = "svc-aetherv"  # Your service account name
   $ServicePrincipal = Get-ADUser -Identity $ServiceAccount
   
   # Configure for each host
   foreach ($HostName in @("hyperv01", "hyperv02", "hyperv03")) {
       $HostComputer = Get-ADComputer $HostName
       Set-ADComputer $HostComputer -PrincipalsAllowedToDelegateToAccount $ServicePrincipal
       Write-Host "Configured RBCD for $HostName"
   }
   ```

3. **Verify using Aether-V's validation:**
   - Check the system notifications panel in Aether-V UI
   - The error will list specific hosts that need configuration
   - After configuring RBCD, wait for the next inventory refresh (or restart Aether-V)

### Issue: Legacy configuration detected

**Symptoms:** "Legacy WinRM configuration detected" or "Delegation incorrectly applied to the Cluster Name Object"

**Solutions:**
This indicates you may have configured delegation on the wrong objects:

1. **Remove RBCD from the CNO (if present):**
   ```powershell
   $ClusterName = "HV-CLUSTER01"
   $ClusterComputer = Get-ADComputer $ClusterName
   
   # Clear the RBCD attribute
   Set-ADComputer $ClusterComputer -PrincipalsAllowedToDelegateToAccount $null
   ```

2. **Configure RBCD on the hosts instead:**
   ```powershell
   # Follow the "Configure RBCD for Hyper-V Hosts" section above
   ```

3. **Remove any `msDS-AllowedToDelegateTo` entries on the service account** (these are for classic constrained delegation, not RBCD)

### Issue: "Legacy WinRM configuration detected"

**Symptoms:** "Legacy WinRM configuration detected" error on startup

**Solutions:**
1. Remove all instances of WINRM_USERNAME, WINRM_PASSWORD, WINRM_TRANSPORT
2. Check environment variables, ConfigMaps, Secrets, and .env files
3. Restart application after removing legacy settings

### Issue: "krb5-config not found" during installation

**Symptoms:** Python package installation fails with krb5-config error

**Solutions:**
1. Install Kerberos development packages:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install krb5-user libkrb5-dev libsasl2-dev
   
   # RHEL/CentOS
   sudo yum install krb5-workstation krb5-devel
   ```
2. Verify installation: `which krb5-config`

## Additional Resources

- [Microsoft: Kerberos Constrained Delegation](https://docs.microsoft.com/en-us/windows-server/security/kerberos/kerberos-constrained-delegation-overview)
- [Microsoft: Resource-Based Constrained Delegation](https://docs.microsoft.com/en-us/windows-server/security/kerberos/whats-new-in-kerberos-authentication#resource-based-constrained-delegation)
- [PowerShell Remoting Security Considerations](https://docs.microsoft.com/en-us/powershell/scripting/learn/remoting/winrmsecurity)
- [Kerberos Authentication Explained](https://web.mit.edu/kerberos/krb5-latest/doc/)
