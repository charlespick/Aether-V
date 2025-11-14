"""Kerberos credential management for WinRM authentication."""

import base64
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import gssapi
import gssapi.raw as gssapi_raw

logger = logging.getLogger(__name__)


class KerberosManagerError(RuntimeError):
    """Base exception for Kerberos manager failures."""


class KerberosManager:
    """Manages Kerberos credentials for WinRM authentication."""

    def __init__(self, principal: str, keytab_b64: str, realm: Optional[str] = None, kdc: Optional[str] = None):
        """
        Initialize Kerberos manager.

        Args:
            principal: Kerberos principal (e.g., user@REALM)
            keytab_b64: Base64-encoded keytab file
            realm: Optional Kerberos realm override
            kdc: Optional KDC server override
        """
        self.principal = principal
        self.keytab_b64 = keytab_b64
        # Auto-detect realm from principal if not explicitly provided
        if realm:
            self.realm = realm
        elif "@" in principal:
            # Extract realm from principal (e.g., "user@REALM" -> "REALM")
            self.realm = principal.split("@", 1)[1]
            logger.debug("Auto-detected realm '%s' from principal", self.realm)
        else:
            self.realm = None
        self.kdc = kdc
        self._keytab_path: Optional[Path] = None
        self._cache_path: Optional[Path] = None
        self._krb5_conf_path: Optional[Path] = None
        self._initialized = False

    def initialize(self) -> None:
        """
        Initialize Kerberos authentication.

        This method:
        1. Decodes and writes the keytab file to a secure temporary location
        2. Sets required environment variables
        3. Acquires Kerberos credentials (TGT) using the keytab
        4. Validates the configuration

        Raises:
            KerberosManagerError: If initialization fails
        """
        if self._initialized:
            logger.debug("Kerberos manager already initialized")
            return

        try:
            # Decode and write keytab to secure temp file
            self._keytab_path = self._write_keytab()
            logger.info("Keytab written to %s", self._keytab_path)

            # Validate keytab contains the expected principal
            self._validate_keytab_with_klist()

            # Set environment variables for Kerberos
            os.environ["KRB5_CLIENT_KTNAME"] = str(self._keytab_path)
            logger.debug("Set KRB5_CLIENT_KTNAME=%s", self._keytab_path)

            # Set cache location (also use temp file for security)
            # Use mkstemp to generate a secure random filename and keep the file
            # to prevent symlink attacks (don't delete and recreate)
            cache_fd, cache_path_str = tempfile.mkstemp(prefix="krb5cc_aetherv_", suffix="")
            self._cache_path = Path(cache_path_str)
            
            # Set restrictive permissions (owner read/write only)
            os.chmod(self._cache_path, 0o600)
            
            # Close the file descriptor but keep the file
            # GSSAPI/kinit will overwrite it, avoiding the symlink race condition
            os.close(cache_fd)
            
            logger.debug("Prepared credential cache path: %s", self._cache_path)
            os.environ["KRB5CCNAME"] = f"FILE:{self._cache_path}"
            logger.debug("Set KRB5CCNAME=FILE:%s", self._cache_path)

            # Set realm and KDC if provided
            if self.realm:
                logger.info("Using Kerberos realm: %s", self.realm)
            if self.kdc:
                logger.info("Using KDC server: %s", self.kdc)
                self._configure_kdc_override()

            # Acquire Kerberos credentials (TGT) from the keytab
            self._acquire_credentials()

            self._initialized = True
            logger.info("Kerberos credentials acquired successfully for principal: %s", self.principal)

        except Exception as exc:
            logger.error("Failed to initialize Kerberos manager: %s", exc)
            self.cleanup()
            raise KerberosManagerError(f"Kerberos initialization failed: {exc}") from exc

    def _write_keytab(self) -> Path:
        """
        Decode and write keytab file to a secure temporary location.

        Uses tempfile.mkstemp to create a unique temporary file with O_EXCL
        to prevent symlink attacks and race conditions.

        Returns:
            Path to the written keytab file

        Raises:
            KerberosManagerError: If keytab cannot be written
        """
        try:
            # Decode base64 keytab
            keytab_bytes = base64.b64decode(self.keytab_b64)
            logger.debug("Decoded keytab: %d bytes", len(keytab_bytes))

            # Create secure temporary file for keytab
            # mkstemp creates the file with O_EXCL, preventing symlink attacks
            fd, keytab_path_str = tempfile.mkstemp(prefix="aetherv_", suffix=".keytab")
            keytab_path = Path(keytab_path_str)
            
            try:
                # Set restrictive permissions immediately (600 = rw-------)
                # Do this before writing sensitive data
                os.fchmod(fd, 0o600)
                logger.debug("Set keytab permissions to 600")
                
                # Write keytab data to the file descriptor
                os.write(fd, keytab_bytes)
            finally:
                # Always close the file descriptor
                os.close(fd)

            return keytab_path

        except Exception as exc:
            logger.error("Failed to write keytab: %s", exc)
            raise KerberosManagerError(f"Failed to write keytab: {exc}") from exc

    def _validate_keytab_with_klist(self) -> None:
        """
        Validate keytab contains the expected principal using klist.

        Runs 'klist -k' to list principals in the keytab and verifies
        that the configured principal is present.

        Raises:
            KerberosManagerError: If validation fails
        """
        try:
            # Run klist -k to list keytab entries
            result = subprocess.run(
                ["klist", "-k", str(self._keytab_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error("klist command failed with exit code %d: %s", result.returncode, result.stderr)
                raise KerberosManagerError(f"Failed to validate keytab with klist: {result.stderr}")

            # Parse klist output to find principals
            # Output format is typically:
            # Keytab name: FILE:/path/to/keytab
            # KVNO Principal
            # ---- --------------------------------------------------------------------------
            #    2 user@REALM
            #    2 user@realm
            
            output = result.stdout
            logger.debug("klist output:\n%s", output)

            # Extract principals from output
            principals_found = []
            for line in output.splitlines():
                # Skip header lines and empty lines
                line = line.strip()
                if not line or "Keytab name:" in line or "KVNO" in line or "----" in line:
                    continue
                
                # Extract principal (format: "KVNO principal")
                parts = line.split(None, 1)
                if len(parts) == 2:
                    principals_found.append(parts[1])

            if not principals_found:
                raise KerberosManagerError("No principals found in keytab")

            # Check if our principal is in the keytab (case-insensitive comparison)
            principal_lower = self.principal.lower()
            matching_principals = [p for p in principals_found if p.lower() == principal_lower]

            if not matching_principals:
                logger.error(
                    "Principal '%s' not found in keytab. Found principals: %s",
                    self.principal,
                    ", ".join(principals_found)
                )
                raise KerberosManagerError(
                    f"Keytab does not contain principal '{self.principal}'. "
                    f"Found: {', '.join(principals_found)}"
                )

            logger.info("Validated keytab contains principal: %s", matching_principals[0])

        except subprocess.TimeoutExpired:
            logger.error("klist command timed out")
            raise KerberosManagerError("Keytab validation timed out") from None
        except FileNotFoundError:
            logger.error("klist command not found - ensure Kerberos tools are installed")
            raise KerberosManagerError(
                "klist command not found. Install krb5-user (Debian/Ubuntu) or krb5-workstation (RHEL/CentOS)"
            ) from None
        except KerberosManagerError:
            raise
        except Exception as exc:
            logger.error("Failed to validate keytab: %s", exc)
            raise KerberosManagerError(f"Keytab validation failed: {exc}") from exc

    def _configure_kdc_override(self) -> None:
        """Write a temporary krb5 configuration when a KDC override is provided."""

        if not self.kdc:
            return

        if not self.realm:
            raise KerberosManagerError("KDC override requires a Kerberos realm to be set")

        conf_path: Optional[Path] = None

        try:
            fd, conf_path_str = tempfile.mkstemp(prefix="krb5_aetherv_", suffix=".conf")
            os.close(fd)
            conf_path = Path(conf_path_str)

            config_contents = (
                "[libdefaults]\n"
                f"    default_realm = {self.realm}\n"
                "    dns_lookup_kdc = false\n\n"
                "[realms]\n"
                f"    {self.realm} = {{\n"
                f"        kdc = {self.kdc}\n"
                "    }\n"
            )

            conf_path.write_text(config_contents, encoding="utf-8")
            os.chmod(conf_path, 0o600)

            self._krb5_conf_path = conf_path
            os.environ["KRB5_CONFIG"] = str(conf_path)
            logger.debug("Wrote temporary krb5.conf to %s for KDC override", conf_path)
        except KerberosManagerError:
            raise
        except Exception as exc:
            logger.error("Failed to configure KDC override: %s", exc)
            if conf_path and conf_path.exists():
                try:
                    conf_path.unlink()
                except Exception:
                    logger.debug("Unable to remove temporary krb5.conf after failure", exc_info=True)
            raise KerberosManagerError(f"Failed to configure KDC override: {exc}") from exc

    def _acquire_credentials(self) -> None:
        """
        Acquire Kerberos credentials (TGT) using the keytab.

        Uses gssapi to obtain credentials from the keytab, populating the
        credential cache so that subsequent WinRM connections can authenticate.

        Raises:
            KerberosManagerError: If credential acquisition fails
        """
        try:
            # Parse the principal name for gssapi
            name = gssapi.Name(self.principal, gssapi.NameType.kerberos_principal)
            logger.debug("Parsed Kerberos principal: %s", name)

            # Acquire credentials from the keytab using the raw API
            # This is the correct way to obtain a TGT from a keytab file
            # The high-level gssapi.Credentials() only reads from existing cache
            try:
                creds_raw = gssapi_raw.acquire_cred_from(
                    {'client_keytab': str(self._keytab_path), 'ccache': f'FILE:{self._cache_path}'},
                    name=name.raw,
                    usage='initiate'
                )
                # Wrap the raw credentials in the high-level API for convenience
                creds = gssapi.Credentials(base=creds_raw.creds)
            except AttributeError:
                # Fallback: If acquire_cred_from is not available, use kinit
                logger.warning("gssapi.raw.acquire_cred_from not available, falling back to kinit")
                self._acquire_credentials_via_kinit()
                # Verify credentials were acquired
                creds = gssapi.Credentials(name=name, usage='initiate')
            
            logger.info("Successfully acquired Kerberos credentials for %s", self.principal)
            logger.debug("Credential lifetime: %s seconds", creds.lifetime)

        except gssapi.exceptions.GSSError as exc:
            logger.error("GSSAPI error acquiring credentials: %s", exc)
            raise KerberosManagerError(f"Failed to acquire Kerberos credentials: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error acquiring credentials: %s", exc)
            raise KerberosManagerError(f"Failed to acquire Kerberos credentials: {exc}") from exc

    def _acquire_credentials_via_kinit(self) -> None:
        """
        Fallback method to acquire credentials using kinit command.
        
        This is used when gssapi.raw.acquire_cred_from is not available.
        
        Raises:
            KerberosManagerError: If kinit fails
        """
        try:
            cmd = [
                'kinit',
                '-k',  # Use keytab
                '-t', str(self._keytab_path),  # Keytab file path
                '-c', f'FILE:{self._cache_path}',  # Cache file path
                self.principal
            ]
            
            logger.debug("Running kinit command: %s", ' '.join(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            if result.returncode != 0:
                logger.error("kinit failed: %s", result.stderr)
                raise KerberosManagerError(f"kinit failed: {result.stderr}")
                
            logger.debug("kinit succeeded: %s", result.stdout)
            
        except FileNotFoundError:
            raise KerberosManagerError("kinit command not found - ensure Kerberos client tools are installed")
        except subprocess.CalledProcessError as exc:
            logger.error("kinit command failed: %s", exc.stderr)
            raise KerberosManagerError(f"kinit failed: {exc.stderr}") from exc

    def cleanup(self) -> None:
        """Clean up Kerberos resources."""
        if self._keytab_path and self._keytab_path.exists():
            try:
                self._keytab_path.unlink()
                logger.debug("Removed keytab file: %s", self._keytab_path)
            except Exception as exc:
                logger.warning("Failed to remove keytab: %s", exc)

        if self._cache_path and self._cache_path.exists():
            try:
                self._cache_path.unlink()
                logger.debug("Removed credential cache: %s", self._cache_path)
            except Exception as exc:
                logger.warning("Failed to remove credential cache: %s", exc)

        if self._krb5_conf_path and self._krb5_conf_path.exists():
            try:
                self._krb5_conf_path.unlink()
                logger.debug("Removed temporary krb5.conf: %s", self._krb5_conf_path)
            except Exception as exc:
                logger.warning("Failed to remove temporary krb5.conf: %s", exc)

        if self._krb5_conf_path and os.environ.get("KRB5_CONFIG") == str(self._krb5_conf_path):
            os.environ.pop("KRB5_CONFIG", None)
            logger.debug("Cleared KRB5_CONFIG environment override")

        self._krb5_conf_path = None

        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if Kerberos manager is initialized."""
        return self._initialized


# Global Kerberos manager instance
_kerberos_manager: Optional[KerberosManager] = None


def initialize_kerberos(principal: str, keytab_b64: str, realm: Optional[str] = None, kdc: Optional[str] = None) -> None:
    """
    Initialize global Kerberos manager.

    Args:
        principal: Kerberos principal
        keytab_b64: Base64-encoded keytab
        realm: Optional realm override
        kdc: Optional KDC override

    Raises:
        KerberosManagerError: If initialization fails
    """
    global _kerberos_manager

    if _kerberos_manager is not None:
        logger.warning("Kerberos manager already initialized; reinitializing")
        _kerberos_manager.cleanup()

    _kerberos_manager = KerberosManager(principal, keytab_b64, realm, kdc)
    _kerberos_manager.initialize()


def get_kerberos_manager() -> Optional[KerberosManager]:
    """Get the global Kerberos manager instance."""
    return _kerberos_manager


def cleanup_kerberos() -> None:
    """Clean up global Kerberos manager."""
    global _kerberos_manager

    if _kerberos_manager is not None:
        _kerberos_manager.cleanup()
        _kerberos_manager = None


def validate_host_kerberos_setup(
    hosts: List[str], 
    realm: Optional[str] = None,
    clusters: Optional[Dict[str, List[str]]] = None
) -> Dict[str, List[str]]:
    """
    Validate Kerberos setup for configured Hyper-V hosts and clusters.

    Checks:
    1. WSMAN SPN exists for each host
    2. Resource-Based Constrained Delegation (RBCD) is configured on cluster objects

    Args:
        hosts: List of hostnames to validate
        realm: Kerberos realm (optional, auto-detected from principal if not provided)
        clusters: Optional dict mapping cluster names to list of member hostnames

    Returns:
        Dictionary with 'errors', 'warnings', 'spn_errors', and 'delegation_errors' lists
    """
    result = {
        "errors": [], 
        "warnings": [], 
        "spn_errors": [],
        "delegation_errors": []
    }

    if not hosts:
        result["warnings"].append("No Hyper-V hosts configured to validate")
        return result

    logger.info("Validating Kerberos setup for %d host(s)", len(hosts))

    # Check WSMAN SPNs for all hosts
    for host in hosts:
        spn_check = _check_wsman_spn(host, realm)
        if not spn_check[0]:
            error_msg = f"Host '{host}': {spn_check[1]}"
            result["errors"].append(error_msg)
            result["spn_errors"].append(error_msg)
        else:
            logger.info("Host '%s': WSMAN SPN validated", host)

    # Check delegation on cluster objects (if clusters provided)
    if clusters:
        logger.info("Checking delegation for %d cluster(s)", len(clusters))
        for cluster_name, cluster_hosts in clusters.items():
            # Skip "Default" cluster (represents hosts not in a cluster)
            if cluster_name == "Default":
                logger.debug("Skipping delegation check for 'Default' cluster (non-clustered hosts)")
                continue
                
            delegation_check = _check_cluster_delegation(cluster_name, cluster_hosts, realm)
            if delegation_check[0] is False:
                error_msg = f"Cluster '{cluster_name}': {delegation_check[1]}"
                result["errors"].append(error_msg)
                result["delegation_errors"].append(error_msg)
            elif delegation_check[0] is None:
                # Could not determine - add warning
                warning_msg = f"Cluster '{cluster_name}': {delegation_check[1]}"
                result["warnings"].append(warning_msg)
            else:
                logger.info("Cluster '%s': Delegation validated", cluster_name)
    else:
        logger.debug("No cluster information provided; skipping delegation checks")

    return result


def _check_wsman_spn(host: str, realm: Optional[str] = None) -> Tuple[bool, str]:
    """
    Check if WSMAN SPN exists for a host.

    Uses 'setspn -Q' to query for WSMAN service principal.

    Args:
        host: Hostname to check
        realm: Optional Kerberos realm

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Query for WSMAN SPN
        # Format: WSMAN/hostname or WSMAN/hostname.domain
        spn_to_check = f"WSMAN/{host}"
        
        # Try setspn -Q (Windows AD query)
        result = subprocess.run(
            ["setspn", "-Q", spn_to_check],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # setspn -Q returns 0 if SPN is found
        if result.returncode == 0:
            # Parse output to confirm SPN exists
            if spn_to_check.lower() in result.stdout.lower():
                return (True, f"WSMAN SPN '{spn_to_check}' found")
            else:
                return (False, f"WSMAN SPN '{spn_to_check}' not found in Active Directory")
        else:
            return (False, f"WSMAN SPN '{spn_to_check}' not found (setspn exit code: {result.returncode})")

    except FileNotFoundError:
        # setspn not available (likely not on Windows or not in PATH)
        # Try alternative: kvno command (attempts to get service ticket)
        try:
            kvno_spn = f"WSMAN/{host}"
            if realm:
                kvno_spn = f"{kvno_spn}@{realm}"
            
            result = subprocess.run(
                ["kvno", kvno_spn],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                return (True, f"WSMAN SPN validated via kvno")
            else:
                return (False, f"WSMAN SPN '{kvno_spn}' not found or inaccessible: {result.stderr.strip()}")

        except FileNotFoundError:
            logger.warning("Neither setspn nor kvno available - cannot validate WSMAN SPN for %s", host)
            return (False, f"Cannot validate WSMAN SPN - setspn and kvno tools not available")
        except subprocess.TimeoutExpired:
            return (False, f"WSMAN SPN check timed out using kvno")
        except Exception as exc:
            return (False, f"WSMAN SPN validation failed: {exc}")

    except subprocess.TimeoutExpired:
        return (False, f"WSMAN SPN check timed out")
    except Exception as exc:
        return (False, f"WSMAN SPN check failed: {exc}")


def _check_cluster_delegation(cluster_name: str, cluster_hosts: List[str], realm: Optional[str] = None) -> Tuple[Optional[bool], str]:
    """
    Check if Resource-Based Constrained Delegation (RBCD) is configured for a cluster.

    RBCD should be configured on the cluster name object (CNO) to allow the Hyper-V hosts
    to delegate credentials when performing double-hop operations (e.g., accessing shared storage).

    Args:
        cluster_name: Name of the cluster
        cluster_hosts: List of hostnames that are members of this cluster
        realm: Optional Kerberos realm

    Returns:
        Tuple of (success: Optional[bool], message: str)
        - True: RBCD confirmed on cluster object
        - False: RBCD confirmed absent or misconfigured
        - None: Unable to determine
    """
    try:
        # Check if the cluster object has msDS-AllowedToActOnBehalfOfOtherIdentity configured
        # This is the RBCD attribute that allows the Hyper-V hosts to delegate on behalf of the cluster
        ps_script = f"""
        try {{
            $cluster = Get-ADComputer -Identity '{cluster_name}' -Properties 'msDS-AllowedToActOnBehalfOfOtherIdentity' -ErrorAction Stop
            
            if ($cluster.'msDS-AllowedToActOnBehalfOfOtherIdentity') {{
                # RBCD is configured - verify it includes the cluster hosts
                $rbcdACL = $cluster.'msDS-AllowedToActOnBehalfOfOtherIdentity'
                $securityDescriptor = New-Object System.DirectoryServices.ActiveDirectorySecurity
                $securityDescriptor.SetSecurityDescriptorBinaryForm($rbcdACL)
                
                $allowedPrincipals = @()
                foreach ($ace in $securityDescriptor.Access) {{
                    if ($ace.AccessControlType -eq 'Allow') {{
                        $allowedPrincipals += $ace.IdentityReference.Value
                    }}
                }}
                
                Write-Output "RBCD_CONFIGURED"
                Write-Output "Principals: $($allowedPrincipals -join ', ')"
            }} else {{
                Write-Output "NO_RBCD"
            }}
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            if "RBCD_CONFIGURED" in output:
                # Extract principals info if available
                principals_info = ""
                for line in output.splitlines():
                    if line.startswith("Principals:"):
                        principals_info = f" ({line})"
                return (True, f"Resource-Based Constrained Delegation (RBCD) configured{principals_info}")
            elif "NO_RBCD" in output:
                return (
                    False,
                    f"No Resource-Based Constrained Delegation (RBCD) configured on cluster object. "
                    f"Configure RBCD on the cluster name object '{cluster_name}' to allow Hyper-V hosts "
                    f"({', '.join(cluster_hosts)}) to delegate credentials for double-hop authentication."
                )
            elif "ERROR:" in output:
                error_msg = output.replace("ERROR:", "").strip()
                # Check if it's a "not found" error
                if "cannot be found" in error_msg.lower() or "not found" in error_msg.lower():
                    return (
                        False,
                        f"Cluster object '{cluster_name}' not found in Active Directory. "
                        f"Ensure the cluster is properly configured and the cluster name object exists."
                    )
                logger.debug("Delegation check error for cluster '%s': %s", cluster_name, error_msg)
                return (None, f"Unable to check RBCD: {error_msg}")
            else:
                logger.debug("Unexpected delegation check output for cluster '%s': %s", cluster_name, output)
                return (None, "Unable to determine RBCD status (unexpected output)")
        else:
            # PowerShell command failed
            logger.debug("Delegation check failed for cluster '%s': %s", cluster_name, result.stderr)
            return (None, "Unable to check RBCD (AD PowerShell module may not be available)")

    except FileNotFoundError:
        # PowerShell not available (not on Windows)
        logger.debug("PowerShell not available - skipping delegation check for cluster '%s'", cluster_name)
        return (None, "RBCD check skipped (PowerShell not available)")
    except subprocess.TimeoutExpired:
        logger.warning("Delegation check timed out for cluster '%s'", cluster_name)
        return (None, "RBCD check timed out")
    except Exception as exc:
        logger.debug("Delegation check failed for cluster '%s': %s", cluster_name, exc)
        return (None, f"Unable to check RBCD: {exc}")


def _check_host_delegation_legacy(host: str, realm: Optional[str] = None) -> Tuple[Optional[bool], str]:
    """
    Check if delegation is configured for a host (LEGACY - not used for cluster validation).

    This checks the old-style delegation on individual host objects, which is NOT the recommended
    approach for failover clusters. Use _check_cluster_delegation instead.

    This is a best-effort check. Returns None if unable to determine.

    Args:
        host: Hostname to check
        realm: Optional Kerberos realm

    Returns:
        Tuple of (success: Optional[bool], message: str)
        - True: Delegation confirmed
        - False: Delegation confirmed absent
        - None: Unable to determine
    """
    try:
        # Try to get delegation info using PowerShell Get-ADComputer
        # This requires Active Directory PowerShell module
        ps_script = f"""
        $computer = Get-ADComputer -Identity '{host}' -Properties TrustedForDelegation, TrustedToAuthForDelegation, msDS-AllowedToDelegateTo
        if ($computer.TrustedToAuthForDelegation -or $computer.TrustedForDelegation -or $computer.'msDS-AllowedToDelegateTo') {{
            Write-Output "DELEGATION_CONFIGURED"
            if ($computer.'msDS-AllowedToDelegateTo') {{
                Write-Output "RBCD: $($computer.'msDS-AllowedToDelegateTo' -join ', ')"
            }}
        }} else {{
            Write-Output "NO_DELEGATION"
        }}
        """

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            if "DELEGATION_CONFIGURED" in output:
                # Extract RBCD info if available
                rbcd_info = ""
                for line in output.splitlines():
                    if line.startswith("RBCD:"):
                        rbcd_info = f" ({line})"
                return (True, f"Delegation configured{rbcd_info}")
            elif "NO_DELEGATION" in output:
                return (
                    False,
                    f"No delegation configured. Set up Resource-Based Constrained Delegation (RBCD) "
                    f"for double-hop authentication."
                )
            else:
                logger.debug("Unexpected delegation check output: %s", output)
                return (None, "Unable to determine delegation status (unexpected output)")
        else:
            # PowerShell command failed - likely Get-ADComputer not available
            logger.debug("Delegation check failed: %s", result.stderr)
            return (None, "Unable to check delegation (AD PowerShell module may not be available)")

    except FileNotFoundError:
        # PowerShell not available (not on Windows)
        logger.debug("PowerShell not available - skipping delegation check")
        return (None, "Delegation check skipped (PowerShell not available)")
    except subprocess.TimeoutExpired:
        logger.warning("Delegation check timed out for %s", host)
        return (None, "Delegation check timed out")
    except Exception as exc:
        logger.debug("Delegation check failed: %s", exc)
        return (None, f"Unable to check delegation: {exc}")


__all__ = [
    "KerberosManager",
    "KerberosManagerError",
    "initialize_kerberos",
    "get_kerberos_manager",
    "cleanup_kerberos",
    "validate_host_kerberos_setup",
]
