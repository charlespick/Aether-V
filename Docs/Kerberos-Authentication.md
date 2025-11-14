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

RBCD allows the Aether-V service account to delegate credentials to Hyper-V hosts and cluster objects for double-hop operations.

### Step 1: Configure Delegation for Hyper-V Hosts

For each Hyper-V host, configure RBCD to allow the service account to delegate:

```powershell
# Run on a domain controller or machine with AD PowerShell tools
# Replace placeholders with your actual values

$ServiceAccount = "svc-aetherv"
$HyperVHost = "hyperv01"

# Get the service account and host objects
$ServicePrincipal = Get-ADServiceAccount $ServiceAccount
$HostComputer = Get-ADComputer $HyperVHost

# Configure RBCD - allow service account to delegate to the host
Set-ADComputer $HostComputer -PrincipalsAllowedToDelegateToAccount $ServicePrincipal

# Verify configuration
Get-ADComputer $HostComputer -Properties PrincipalsAllowedToDelegateToAccount |
    Select-Object Name, PrincipalsAllowedToDelegateToAccount
```

### Step 2: Configure Delegation for Cluster Objects

If using Hyper-V failover clusters, also configure RBCD for the cluster name object:

```powershell
$ClusterName = "HV-CLUSTER01"

# Get cluster computer object
$ClusterComputer = Get-ADComputer $ClusterName

# Configure RBCD for cluster
Set-ADComputer $ClusterComputer -PrincipalsAllowedToDelegateToAccount $ServicePrincipal

# Verify
Get-ADComputer $ClusterComputer -Properties PrincipalsAllowedToDelegateToAccount |
    Select-Object Name, PrincipalsAllowedToDelegateToAccount
```

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

**Symptoms:** VM operations fail with access denied on cluster resources

**Solutions:**
1. Verify RBCD is configured for both host AND cluster objects
2. Check SPNs are properly registered
3. Ensure service account has necessary permissions on cluster
4. Test delegation: `Get-ADComputer <host> -Properties PrincipalsAllowedToDelegateToAccount`

### Issue: Legacy configuration detected

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
