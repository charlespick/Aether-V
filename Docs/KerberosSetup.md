# Kerberos Setup for Aether-V

Aether-V authenticates to Hyper-V hosts exclusively with Kerberos. The server pod
loads a pre-generated keytab, obtains a ticket at startup, and then relies on
resource-based constrained delegation (RBCD) to reach Failover Cluster resources
from each host. Follow the steps below to provision the credentials and
configure delegation.

## 1. Create a service principal

1. Sign in to Active Directory with an account that can manage service
   principals.
2. Create a dedicated user or group-managed service account (gMSA) that Aether-V
   will use, for example `svc-aetherv`.
3. Register Service Principal Names (SPNs) for the WinRM endpoint. The example
   below assumes the service will connect to hosts as `HTTP/<hostname>`:

   ```powershell
   setspn -S HTTP/aetherv.makerad.makerland.xyz svc-aetherv
   setspn -S HTTP/aetherv svc-aetherv
   ```
4. Generate a keytab that contains the Kerberos keys for the account. On a
   domain controller run:

   ```powershell
   ktpass /out c:\temp\aetherv.keytab /princ HTTP/aetherv.makerad.makerland.xyz@MAKERLAND.MAKERLAND.XYZ \ 
          /mapuser svc-aetherv@MAKERLAND.MAKERLAND.XYZ /crypto AES256-SHA1 /ptype KRB5_NT_PRINCIPAL /pass *
   ```

   The command prompts for the account password and emits `aetherv.keytab`.
   Copy the file to a secure workstation where you prepare Kubernetes secrets.

## 2. Store the keytab as a Kubernetes secret

1. Encode the keytab into a secret. The example below stores the file as
   `kerberos.keytab` in the `aetherv-secrets` namespace:

   ```bash
   kubectl create secret generic aetherv-kerberos \
     --namespace aetherv \
     --from-file=kerberos.keytab=/path/to/aetherv.keytab
   ```

2. Mount the secret into the server pod (see `server/k8s/deployment.yaml`) and
   set the environment variables:

   ```text
   WINRM_KERBEROS_PRINCIPAL=AETHERV/host@MAKERLAND.MAKERLAND.XYZ
   WINRM_KERBEROS_KEYTAB=/var/run/secrets/aetherv/kerberos.keytab
   WINRM_KERBEROS_CCACHE=/tmp/aetherv_krb5_ccache
   ```

   The container needs the `kinit` and `klist` utilities (installed via the
   `krb5-user` package on Debian-based images) to materialise the ticket cache.

## 3. Configure resource-based constrained delegation

Resource-based delegation must be configured on every Hyper-V host _and_ on the
Failover Cluster computer objects (if present) so that WinRM can perform the
second hop to the cluster service.

```powershell
$principal = Get-ADUser -Identity "svc-aetherv"
$delegatingAccount = @($principal)

# Allow the service principal to delegate to each Hyper-V host
"HYPERV01","HYPERV02" | ForEach-Object {
    Set-ADComputer -Identity ("{0}$" -f $_) -PrincipalsAllowedToDelegateToAccount $delegatingAccount
}

# Allow delegation to the cluster computer object as well
Set-ADComputer -Identity "TMPECLUSTER02$" -PrincipalsAllowedToDelegateToAccount $delegatingAccount
```

Verify the settings with:

```powershell
Get-ADComputer -Identity "HYPERV01$" -Properties PrincipalsAllowedToDelegateToAccount | \
    Select-Object -ExpandProperty PrincipalsAllowedToDelegateToAccount
```

## 4. Validate from Aether-V

1. Deploy or restart the Aether-V server. During startup the server runs
   `kinit` using the provided keytab. Initialization failures appear in the
   logs and the container exits.
2. The inventory service now runs a Kerberos delegation probe during startup. If
   a host denies cluster access, the UI surfaces a warning titled
   “Enable Kerberos delegation for <hostname>” and the logs contain diagnostic
   messages from the underlying PowerShell command.
3. After delegation is configured correctly, re-run the probe by restarting the
   server or triggering a manual inventory refresh; the warning disappears once
   the host permits delegated cluster access.

With the keytab, Kubernetes secret, and RBCD configuration in place, Aether-V
can securely manage clustered virtual machines without relying on NTLM or
CredSSP fallbacks.
