"""Kerberos credential management for WinRM authentication."""

import base64
import logging
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set

from dns import resolver as dns_resolver

import gssapi
import gssapi.raw as gssapi_raw

from .spn_validator import check_wsman_spn

try:
    from ldap3 import (
        BASE,
        KERBEROS,
        SASL,
        SUBTREE,
        Connection,
        Server,
        NONE,
    )
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_bytes, escape_filter_chars
except ImportError:  # pragma: no cover - optional dependency safeguard
    BASE = None
    KERBEROS = None
    SASL = None
    SUBTREE = None
    Connection = None
    Server = None
    NONE = None
    LDAPException = Exception
    escape_bytes = None
    escape_filter_chars = None

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
        self.realm: Optional[str]
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
            cache_fd, cache_path_str = tempfile.mkstemp(
                prefix="krb5cc_aetherv_", suffix="")
            self._cache_path = Path(cache_path_str)

            # Set restrictive permissions (owner read/write only)
            os.chmod(self._cache_path, 0o600)

            # Close the file descriptor but keep the file
            # GSSAPI/kinit will overwrite it, avoiding the symlink race condition
            os.close(cache_fd)

            logger.debug("Prepared credential cache path: %s",
                         self._cache_path)
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
            logger.info(
                "Kerberos credentials acquired successfully for principal: %s", self.principal)

        except Exception as exc:
            logger.error("Failed to initialize Kerberos manager: %s", exc)
            self.cleanup()
            raise KerberosManagerError(
                f"Kerberos initialization failed: {exc}") from exc

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
            fd, keytab_path_str = tempfile.mkstemp(
                prefix="aetherv_", suffix=".keytab")
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
            raise KerberosManagerError(
                f"Failed to write keytab: {exc}") from exc

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
                logger.error("klist command failed with exit code %d: %s",
                             result.returncode, result.stderr)
                raise KerberosManagerError(
                    f"Failed to validate keytab with klist: {result.stderr}")

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
            matching_principals = [
                p for p in principals_found if p.lower() == principal_lower]

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

            logger.info("Validated keytab contains principal: %s",
                        matching_principals[0])

        except subprocess.TimeoutExpired:
            logger.error("klist command timed out")
            raise KerberosManagerError("Keytab validation timed out") from None
        except FileNotFoundError:
            logger.error(
                "klist command not found - ensure Kerberos tools are installed")
            raise KerberosManagerError(
                "klist command not found. Install krb5-user (Debian/Ubuntu) or krb5-workstation (RHEL/CentOS)"
            ) from None
        except KerberosManagerError:
            raise
        except Exception as exc:
            logger.error("Failed to validate keytab: %s", exc)
            raise KerberosManagerError(
                f"Keytab validation failed: {exc}") from exc

    def _configure_kdc_override(self) -> None:
        """Write a temporary krb5 configuration when a KDC override is provided."""

        if not self.kdc:
            return

        if not self.realm:
            raise KerberosManagerError(
                "KDC override requires a Kerberos realm to be set")

        conf_path: Optional[Path] = None

        try:
            fd, conf_path_str = tempfile.mkstemp(
                prefix="krb5_aetherv_", suffix=".conf")
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
            logger.debug(
                "Wrote temporary krb5.conf to %s for KDC override", conf_path)
        except KerberosManagerError:
            raise
        except Exception as exc:
            logger.error("Failed to configure KDC override: %s", exc)
            if conf_path and conf_path.exists():
                try:
                    conf_path.unlink()
                except Exception:
                    logger.debug(
                        "Unable to remove temporary krb5.conf after failure", exc_info=True)
            raise KerberosManagerError(
                f"Failed to configure KDC override: {exc}") from exc

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
            name = gssapi.Name(
                self.principal, gssapi.NameType.kerberos_principal)
            logger.debug("Parsed Kerberos principal: %s", name)

            # Acquire credentials from the keytab using the raw API
            # This is the correct way to obtain a TGT from a keytab file
            # The high-level gssapi.Credentials() only reads from existing cache
            try:
                creds_raw = gssapi_raw.acquire_cred_from(
                    {'client_keytab': str(self._keytab_path),
                     'ccache': f'FILE:{self._cache_path}'},
                    name=name.raw,  # type: ignore[attr-defined]
                    usage='initiate'
                )
                # Wrap the raw credentials in the high-level API for convenience
                creds = gssapi.Credentials(base=creds_raw.creds)
            except AttributeError:
                # Fallback: If acquire_cred_from is not available, use kinit
                logger.warning(
                    "gssapi.raw.acquire_cred_from not available, falling back to kinit")
                self._acquire_credentials_via_kinit()
                # Verify credentials were acquired
                creds = gssapi.Credentials(name=name, usage='initiate')

            logger.info(
                "Successfully acquired Kerberos credentials for %s", self.principal)
            logger.debug("Credential lifetime: %s seconds", creds.lifetime)

        except gssapi.exceptions.GSSError as exc:
            logger.error("GSSAPI error acquiring credentials: %s", exc)
            raise KerberosManagerError(
                f"Failed to acquire Kerberos credentials: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error acquiring credentials: %s", exc)
            raise KerberosManagerError(
                f"Failed to acquire Kerberos credentials: {exc}") from exc

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
            raise KerberosManagerError(
                "kinit command not found - ensure Kerberos client tools are installed")
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
                logger.debug("Removed temporary krb5.conf: %s",
                             self._krb5_conf_path)
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


class PrincipalTokenizer:
    """Centralized token normalization for Kerberos principals and hosts.

    This class consolidates scattered token manipulation logic into a single,
    well-tested location, following the principle of centralizing common
    functionality when it doesn't require excessive conditional branching.
    """

    @staticmethod
    def normalize_principal(principal: str) -> Set[str]:
        """Return all comparable token variations for a principal.

        Handles various principal formats:
        - DOMAIN\\user → extracts user
        - host/service.domain.com → extracts service parts
        - user@REALM → extracts user and REALM parts
        - computer$ → extracts computer
        - CN=...,DC=... → extracts DN components
        """
        tokens: Set[str] = set()
        queue: List[str] = []

        if principal:
            queue.append(principal.strip().lower())

        while queue:
            current = queue.pop()
            if not current or current in tokens:
                continue

            tokens.add(current)

            # Extract domain\\user → user
            if "\\" in current:
                queue.append(current.split("\\", 1)[1])
            # Extract service/host → host
            if "/" in current:
                queue.append(current.split("/", 1)[1])
            # Extract user@realm → user
            if "@" in current:
                queue.append(current.split("@", 1)[0])
            # Extract computer$ → computer
            if current.endswith("$"):
                queue.append(current[:-1])
            # Extract fqdn.domain.com → fqdn
            if "." in current:
                queue.append(current.split(".", 1)[0])
            # Extract DN components: CN=value,DC=... → value
            if "=" in current:
                for part in current.split(","):
                    part = part.strip()
                    if "=" in part:
                        queue.append(part.split("=", 1)[1])

        return tokens

    @staticmethod
    def normalize_host(host: str, realm: Optional[str] = None) -> Set[str]:
        """Return all expected token variations for a Hyper-V host.

        Generates common variations:
        - host.domain.com → host.domain.com, host, host$
        - With realm: host$@REALM, host@REALM
        """
        tokens: Set[str] = set()

        if not host:
            return tokens

        host_lower = host.strip().lower()
        if not host_lower:
            return tokens

        # FQDN and short name
        short_name = host_lower.split(".", 1)[0]
        realm_lower = realm.lower() if realm else None

        # Base variations
        candidates = {
            host_lower,
            short_name,
            f"{short_name}$",
        }

        # Add realm-qualified variations
        if realm_lower:
            candidates.update({
                f"{short_name}$@{realm_lower}",
                f"{short_name}@{realm_lower}",
            })

        tokens.update(candidate for candidate in candidates if candidate)
        return tokens

    @staticmethod
    def extract_domain_from_principal(principal: Optional[str]) -> Optional[str]:
        """Extract DNS domain name from a Kerberos principal.

        Examples:
            user@EXAMPLE.COM → example.com
            host/server.ad.local@AD.LOCAL → ad.local
        """
        if not principal or "@" not in principal:
            return None

        realm = principal.split("@", 1)[1].strip().strip(".")
        if not realm:
            return None

        return realm.lower()

    @staticmethod
    def realm_to_base_dn(realm: Optional[str]) -> Optional[str]:
        """Convert Kerberos realm to LDAP base DN.

        Examples:
            EXAMPLE.COM → DC=example,DC=com
            AD.CORP → DC=ad,DC=corp
        """
        if not realm:
            return None

        realm = realm.strip().strip(".")
        if not realm:
            return None

        parts = [part.strip() for part in realm.split(".") if part.strip()]
        if not parts:
            return None

        return ",".join(f"DC={part.lower()}" for part in parts)

    @staticmethod
    def candidate_domains_for_ldap(realm: Optional[str]) -> List[str]:
        """Gather potential AD domain names from configuration.

        Checks principal, configured realm, and provided realm parameter.
        Returns unique, lowercase domain names in priority order.
        """
        domains: List[str] = []
        manager = get_kerberos_manager()

        # Try principal first
        if manager:
            principal_domain = PrincipalTokenizer.extract_domain_from_principal(
                manager.principal
            )
            if principal_domain:
                domains.append(principal_domain)

        # Add configured realms
        for candidate in (realm, manager.realm if manager else None):
            if not candidate:
                continue
            cleaned = candidate.strip().strip(".")
            if not cleaned:
                continue
            domain = cleaned.lower()
            if domain not in domains:
                domains.append(domain)

        return domains


# Maintain backward compatibility with old function names
def _realm_to_base_dn(realm: Optional[str]) -> Optional[str]:
    """Convert a Kerberos realm to a base DN (deprecated - use PrincipalTokenizer)."""
    return PrincipalTokenizer.realm_to_base_dn(realm)


def _extract_domain_from_principal(principal: Optional[str]) -> Optional[str]:
    """Extract domain from principal (deprecated - use PrincipalTokenizer)."""
    return PrincipalTokenizer.extract_domain_from_principal(principal)


def _discover_ldap_server_hosts(realm: Optional[str]) -> List[str]:
    """Discover LDAP hosts by querying AD domain controller SRV records."""

    manager = get_kerberos_manager()
    kdc_override = manager.kdc if manager else None
    if kdc_override:
        override_host, override_port = _parse_ldap_server_target(kdc_override)
        if override_host:
            target = _format_ldap_server_target(override_host, override_port)
            logger.debug(
                "Using configured Kerberos KDC override for LDAP checks: %s",
                target,
            )
            return [target]
        logger.warning(
            "Configured Kerberos KDC override %r is not a valid LDAP target",
            kdc_override,
        )

    domains = PrincipalTokenizer.candidate_domains_for_ldap(realm)
    hosts: List[str] = []

    if not domains:
        logger.warning("Unable to determine AD domain for LDAP discovery")
        return hosts

    for domain in domains:
        srv_record = f"_ldap._tcp.dc._msdcs.{domain}"
        try:
            answers = dns_resolver.resolve(srv_record, "SRV")
        except Exception as exc:  # pragma: no cover - environment specific
            logger.warning(
                "Failed to resolve LDAP SRV records for %s: %s",
                srv_record,
                exc,
            )
            continue

        ordered: List[Tuple[int, int, str, str]] = []
        domain_hosts: List[str] = []
        for rdata in answers:
            srv_target: Optional[str] = getattr(rdata, "target", None)
            if not srv_target:
                continue
            host = str(srv_target).rstrip(".")
            if not host:
                continue
            priority = getattr(rdata, "priority", 0)
            weight = getattr(rdata, "weight", 0)
            ordered.append((int(priority), int(weight), host.lower(), host))

        for _, _, _, host in sorted(ordered, key=lambda item: (item[0], -item[1], item[2])):
            if host not in hosts:
                hosts.append(host)
            if host not in domain_hosts:
                domain_hosts.append(host)

        if domain_hosts:
            logger.debug(
                "Discovered LDAP domain controllers for %s: %s",
                domain,
                ", ".join(domain_hosts),
            )

    return hosts


def _parse_ldap_server_target(server_host: str) -> Tuple[Optional[str], Optional[int]]:
    """Split an LDAP server target into host and optional port components."""

    if not server_host:
        return None, None

    host = server_host.strip()
    if not host:
        return None, None

    port: Optional[int] = None

    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            bracket_host = host[1:closing].strip()
            remainder = host[closing + 1:]
            if remainder.startswith(":") and remainder[1:].isdigit():
                port = int(remainder[1:])
            host = bracket_host
    else:
        if host.count(":") == 1:
            possible_host, possible_port = host.rsplit(":", 1)
            if possible_port.isdigit():
                host = possible_host
                port = int(possible_port)

    cleaned_host = host.strip()
    if not cleaned_host:
        return None, None

    return cleaned_host, port


def _format_ldap_server_target(host: str, port: Optional[int]) -> str:
    """Return a normalized LDAP target preserving optional port information."""

    if port is None:
        return host

    if ":" in host and not host.startswith("["):
        # IPv6 literals must be enclosed in brackets when a port is supplied
        return f"[{host}]:{port}"

    return f"{host}:{port}"


def _establish_ldap_connection(server_host: Optional[str]) -> Optional[Connection]:
    """Bind to LDAP using the existing Kerberos ticket cache."""

    if (
        Server is None
        or Connection is None
        or SASL is None
        or KERBEROS is None
        or escape_filter_chars is None
        or BASE is None
        or SUBTREE is None
    ):
        logger.warning(
            "ldap3 module unavailable - skipping LDAP-based delegation checks"
        )
        return None

    if not server_host:
        logger.warning(
            "Unable to derive LDAP server host - skipping LDAP-based delegation checks"
        )
        return None

    host, override_port = _parse_ldap_server_target(server_host)

    if not host:
        logger.warning(
            "Unable to determine LDAP hostname from %r", server_host)
        return None

    server_kwargs = {"get_info": NONE, "use_ssl": True, "port": 636}

    if override_port in (636, 3269):
        server_kwargs["port"] = override_port
    elif override_port not in (None, 636, 3269):
        logger.debug(
            "Ignoring non-LDAPS port %s derived from %r when binding to LDAP",
            override_port,
            server_host,
        )

    try:
        server = Server(host, **server_kwargs)
        connection = Connection(
            server,
            authentication=SASL,
            sasl_mechanism=KERBEROS,
            auto_bind=True,
            raise_exceptions=True,
        )
        return connection
    except LDAPException as exc:  # pragma: no cover - environment specific
        logger.warning(
            "LDAP bind to %s failed: %s",
            server_host,
            exc,
            exc_info=True,
        )
        return None


def _lookup_default_naming_context(connection: Connection) -> Optional[str]:
    """Query root DSE for the default naming context."""

    try:
        if connection.search(
            "",
            "(objectClass=*)",
            search_scope=BASE,
            attributes=["defaultNamingContext"],
            size_limit=1,
        ) and connection.entries:
            entry = connection.entries[0]
            attr_dict = entry.entry_attributes_as_dict
            if not attr_dict:
                return None
            value = attr_dict.get("defaultNamingContext")
            if isinstance(value, list):
                value = value[0] if value else None
            if value:
                return str(value)
    except LDAPException as exc:  # pragma: no cover - environment specific
        logger.debug(
            "Failed to query defaultNamingContext via LDAP: %s", exc, exc_info=True)

    return None


def _extract_allowed_sids_from_security_descriptor(descriptor: bytes) -> List[bytes]:
    """Return SID blobs from ACCESS_ALLOWED ACEs (including object ACEs)."""

    if not descriptor:
        return []

    if isinstance(descriptor, memoryview):
        descriptor = descriptor.tobytes()
    elif isinstance(descriptor, bytearray):
        descriptor = bytes(descriptor)

    if not isinstance(descriptor, (bytes, bytearray)):
        return []  # type: ignore[unreachable]  # Defensive: handle unexpected types

    data = bytes(descriptor)
    if len(data) < 20:
        return []

    dacl_offset = struct.unpack_from("<I", data, 16)[0]
    if dacl_offset == 0 or dacl_offset >= len(data):
        return []

    if len(data) < dacl_offset + 8:
        return []

    ace_count = struct.unpack_from("<H", data, dacl_offset + 4)[0]
    cursor = dacl_offset + 8
    sids: List[bytes] = []

    ACE_OBJECT_TYPE_PRESENT = 0x1
    ACE_INHERITED_OBJECT_TYPE_PRESENT = 0x2

    for _ in range(ace_count):
        if cursor + 4 > len(data):
            break

        ace_type = data[cursor]
        ace_size = struct.unpack_from("<H", data, cursor + 2)[0]

        if ace_size < 8 or cursor + ace_size > len(data):
            break

        if ace_type == 0x00:  # ACCESS_ALLOWED_ACE_TYPE
            sid_start = cursor + 8
            sid_blob = data[sid_start: cursor + ace_size]
            if sid_blob:
                sids.append(sid_blob)
        elif ace_type == 0x05:  # ACCESS_ALLOWED_OBJECT_ACE_TYPE
            if ace_size < 12:
                cursor += ace_size
                continue

            flags = struct.unpack_from("<I", data, cursor + 8)[0]
            sid_start = cursor + 12

            # Object ACEs may include optional GUIDs depending on the flags
            if flags & ACE_OBJECT_TYPE_PRESENT:
                sid_start += 16
            if flags & ACE_INHERITED_OBJECT_TYPE_PRESENT:
                sid_start += 16

            if sid_start >= cursor + ace_size:
                cursor += ace_size
                continue

            sid_blob = data[sid_start: cursor + ace_size]
            if sid_blob:
                sids.append(sid_blob)

        cursor += ace_size

    return sids


def _sid_bytes_to_str(sid: bytes) -> Optional[str]:
    """Convert a SID byte sequence to its S-1-x textual representation."""

    if not sid:
        return None

    if isinstance(sid, memoryview):
        sid = sid.tobytes()

    if len(sid) < 8:
        return None

    revision = sid[0]
    sub_authority_count = sid[1]
    identifier_authority = int.from_bytes(sid[2:8], byteorder="big")

    sub_authorities: List[str] = []
    offset = 8
    for _ in range(sub_authority_count):
        if offset + 4 > len(sid):
            return None
        sub_authority = struct.unpack_from("<I", sid, offset)[0]
        sub_authorities.append(str(sub_authority))
        offset += 4

    components = [f"S-{revision}", str(identifier_authority), *sub_authorities]
    return "-".join(components)


def _ldap_resolve_sids(
    connection: Connection, base_dn: str, sid_blobs: List[bytes]
) -> Dict[str, str]:
    """Resolve SID blobs to display names via LDAP."""

    if not sid_blobs or escape_bytes is None:
        return {}

    unique: List[Tuple[str, bytes]] = []
    seen: Set[str] = set()
    for blob in sid_blobs:
        sid_str = _sid_bytes_to_str(blob)
        if not sid_str or sid_str in seen:
            continue
        seen.add(sid_str)
        unique.append((sid_str, blob))

    resolved: Dict[str, str] = {}

    for index in range(0, len(unique), 25):
        chunk = unique[index:index + 25]
        filter_components = "".join(
            f"(objectSid={escape_bytes(blob)})" for _, blob in chunk
        )
        if not filter_components:
            continue

        ldap_filter = f"(|{filter_components})"

        try:
            connection.search(
                base_dn,
                ldap_filter,
                search_scope=SUBTREE,
                attributes=["sAMAccountName", "cn", "name", "objectSid"],
                size_limit=len(chunk),
            )
        except LDAPException as exc:  # pragma: no cover - environment specific
            logger.debug("LDAP SID lookup failed: %s", exc, exc_info=True)
            continue

        for entry in connection.entries:
            raw_sid_values = entry.entry_raw_attributes.get(
                "objectSid") if entry.entry_raw_attributes else None
            if not raw_sid_values:
                continue
            raw_sid = raw_sid_values[0]
            if isinstance(raw_sid, memoryview):
                raw_sid = raw_sid.tobytes()
            sid_str = _sid_bytes_to_str(raw_sid)
            if not sid_str:
                continue

            attr_dict = entry.entry_attributes_as_dict or {}
            candidate = attr_dict.get("sAMAccountName") or attr_dict.get(
                "cn") or attr_dict.get("name")
            if isinstance(candidate, list):
                candidate = candidate[0] if candidate else None
            display = str(entry.entry_dn) if not candidate else str(candidate)
            resolved[sid_str] = display

    return resolved


def _normalize_ldap_boolean(value: object) -> Optional[bool]:
    """Convert common LDAP flag encodings to real booleans."""

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (list, tuple, set)):
        for item in value:
            normalized = _normalize_ldap_boolean(item)
            if normalized is not None:
                return normalized
        return None

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", "ignore")
        except Exception:  # pragma: no cover - defensive safeguard
            value = ""

    if isinstance(value, (int, float)):
        return bool(value)

    string_value = str(value).strip().lower()
    if not string_value:
        return None

    if string_value in {"true", "1", "yes", "on"}:
        return True

    if string_value in {"false", "0", "no", "off"}:
        return False

    return None


def _ldap_get_computer_delegation_info(
    name: str, realm: Optional[str]
) -> Optional[Dict[str, object]]:
    """Fetch delegation-related attributes for a computer account via LDAP."""

    server_hosts = _discover_ldap_server_hosts(realm)
    if not server_hosts:
        logger.warning(
            "Unable to locate any LDAP servers for '%s' in realm '%s'",
            name,
            realm or "<default>",
        )
        return None

    connection: Optional[Connection] = None
    bound_host: Optional[str] = None

    for server_host in server_hosts:
        connection = _establish_ldap_connection(server_host)
        if connection is not None:
            bound_host = server_host
            break

    if connection is None:
        logger.warning(
            "LDAP connection unavailable for '%s' in realm '%s'",
            name,
            realm or "<default>",
        )
        return None

    try:
        manager = get_kerberos_manager()
        base_hint = _realm_to_base_dn(
            realm or (manager.realm if manager else None))
        base_dn = base_hint or _lookup_default_naming_context(connection)
        if not base_dn:
            logger.debug("Unable to determine LDAP base DN for '%s'", name)
            return None

        normalized_name = (name or "").strip()
        search_candidates: List[str] = []

        if normalized_name:
            trimmed_name = normalized_name.rstrip("$")

            if "." in trimmed_name:
                short_candidate = trimmed_name.split(".", 1)[0]
                if short_candidate:
                    search_candidates.append(short_candidate)

            if trimmed_name and trimmed_name not in search_candidates:
                search_candidates.append(trimmed_name)

        if not search_candidates:
            logger.debug(
                "Unable to derive LDAP search candidates for host '%s'", name
            )
            return None

        entry = None

        for candidate in search_candidates:
            sam_account = (
                candidate if candidate.endswith("$") else f"{candidate}$"
            )
            search_filter = (
                f"(&(objectClass=computer)(sAMAccountName={escape_filter_chars(sam_account)}))"
            )

            logger.debug(
                "Searching for computer '%s' using candidate '%s' (sAMAccountName '%s')",
                name,
                candidate,
                sam_account,
            )

            try:
                connection.search(
                    base_dn,
                    search_filter,
                    search_scope=SUBTREE,
                    attributes=[
                        "PrincipalsAllowedToDelegateToAccount",
                        "msDS-AllowedToActOnBehalfOfOtherIdentity",
                        "msDS-AllowedToDelegateTo",
                        "TrustedToAuthForDelegation",
                        "TrustedForDelegation",
                        "objectSid",
                    ],
                    size_limit=1,
                )
            except LDAPException as exc:  # pragma: no cover - environment specific
                logger.debug(
                    "LDAP search for '%s' (candidate '%s') failed: %s",
                    name,
                    candidate,
                    exc,
                    exc_info=True,
                )
                return None

            if connection.entries:
                entry = connection.entries[0]
                break

        if entry is None:
            return {"exists": False}

        raw_attrs = entry.entry_raw_attributes or {}
        attr_dict = entry.entry_attributes_as_dict or {}

        delegation_principals = attr_dict.get(
            "PrincipalsAllowedToDelegateToAccount") or []
        if isinstance(delegation_principals, str):
            delegation_principals = [delegation_principals]
        elif isinstance(delegation_principals, (tuple, set)):
            delegation_principals = list(delegation_principals)

        delegation_principals = [
            str(principal)
            for principal in delegation_principals
            if principal
        ]

        rbcd_values = raw_attrs.get(
            "msDS-AllowedToActOnBehalfOfOtherIdentity") or []
        sid_blobs: List[bytes] = []
        for descriptor in rbcd_values:
            sid_blobs.extend(
                _extract_allowed_sids_from_security_descriptor(descriptor))

        sid_strings = [
            sid_str
            for sid_str in (_sid_bytes_to_str(blob) for blob in sid_blobs)
            if sid_str
        ]

        principal_lookup = _ldap_resolve_sids(connection, base_dn, sid_blobs)
        allowed_principals: List[str] = []
        seen_principals: Set[str] = set()

        for blob in sid_blobs:
            sid_str = _sid_bytes_to_str(blob)
            if not sid_str:
                continue
            display = principal_lookup.get(sid_str, sid_str)
            if display not in seen_principals:
                seen_principals.add(display)
                allowed_principals.append(display)

        delegate_targets = attr_dict.get("msDS-AllowedToDelegateTo") or []
        if isinstance(delegate_targets, str):
            delegate_targets = [delegate_targets]
        elif isinstance(delegate_targets, (tuple, set)):
            delegate_targets = list(delegate_targets)

        delegate_targets = [str(value) for value in delegate_targets if value]

        object_sid_raw = raw_attrs.get(
            "objectSid") or attr_dict.get("objectSid") or None
        object_sid: Optional[str] = None
        if isinstance(object_sid_raw, (list, tuple)) and object_sid_raw:
            object_sid_raw = object_sid_raw[0]
        if isinstance(object_sid_raw, bytes):
            object_sid = _sid_bytes_to_str(object_sid_raw)
        elif object_sid_raw:
            object_sid = str(object_sid_raw)

        trusted_to_auth = _normalize_ldap_boolean(
            attr_dict.get("TrustedToAuthForDelegation")
        )
        trusted_for_delegation = _normalize_ldap_boolean(
            attr_dict.get("TrustedForDelegation")
        )

        return {
            "exists": True,
            "delegation_present": bool(delegation_principals),
            "delegation_principals": delegation_principals,
            "rbcd_present": bool(rbcd_values),
            "rbcd_principals": allowed_principals,
            "rbcd_sid_strings": sid_strings,
            "delegate_targets": delegate_targets,
            "delegate_present": bool(delegate_targets),
            "trusted_to_auth": bool(trusted_to_auth),
            "trusted_for_delegation": bool(trusted_for_delegation),
            "object_sid": object_sid,
        }
    finally:
        if connection is not None:
            logger.debug("Unbinding LDAP connection to %s",
                         bound_host or "<unknown>")
            connection.unbind()


def validate_host_kerberos_setup(
    hosts: List[str],
    realm: Optional[str] = None,
    clusters: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, List[str]]:
    """
    Validate Kerberos setup for configured Hyper-V hosts.

    Checks:
    1. WSMAN SPN exists for each host
    2. Cluster Name Objects (CNOs) grant RBCD to the Hyper-V host computer accounts
       and do not include unexpected principals
    3. Hyper-V hosts are not configured with legacy/unconstrained delegation flags

    Args:
        hosts: List of hostnames to validate
        realm: Kerberos realm (optional, auto-detected from principal if not provided)
        clusters: Optional dict mapping cluster names to list of member hostnames

    Returns:
        Dictionary with 'errors', 'warnings', 'spn_errors', and 'delegation_errors' lists
    """
    result: Dict[str, List[str]] = {
        "errors": [],
        "warnings": [],
        "spn_errors": [],
        "delegation_errors": []
    }

    if hosts:
        logger.info("Validating Kerberos setup for %d host(s)", len(hosts))

        # Check WSMAN SPNs for all hosts
        for host in hosts:
            spn_check = check_wsman_spn(host, realm)
            if not spn_check[0]:
                error_msg = f"Host '{host}': {spn_check[1]}"
                result["errors"].append(error_msg)
                result["spn_errors"].append(error_msg)
            else:
                logger.info("Host '%s': WSMAN SPN validated", host)
    elif not clusters:
        # Only warn when we truly have nothing to validate
        result["warnings"].append("No Hyper-V hosts configured to validate")

    delegation_hosts: Set[str] = set(hosts)
    if clusters:
        for cluster_hosts in clusters.values():
            if not cluster_hosts:
                continue
            delegation_hosts.update(cluster_hosts)

    cluster_names: Set[str] = set(clusters.keys()) if clusters else set()

    if delegation_hosts or cluster_names:
        logger.info("Validating delegation and RBCD for %d host(s)",
                    len(delegation_hosts))

        host_tokens: Dict[str, Set[str]] = {
            host: PrincipalTokenizer.normalize_host(host, realm)
            for host in delegation_hosts
        }
        expected_host_tokens: Set[str] = set()
        for tokens in host_tokens.values():
            expected_host_tokens.update(tokens)

        for host in sorted(delegation_hosts):
            directory_info = _ldap_get_computer_delegation_info(host, realm)
            if directory_info is None:
                warning_msg = (
                    f"Host '{host}': Delegation check skipped (LDAP connection unavailable)"
                )
                logger.warning(warning_msg)
                result["warnings"].append(warning_msg)
                continue

            host_sid_value = directory_info.get("object_sid") or ""
            host_sid = str(host_sid_value).strip()
            if host_sid:
                host_tokens.setdefault(host, set()).add(host_sid.lower())
                expected_host_tokens.add(host_sid.lower())

            if not directory_info.get("exists", True):
                error_msg = (
                    f"Host '{host}': Computer object not found in Active Directory. "
                    "Ensure the host exists before configuring RBCD on cluster objects."
                )
                result["errors"].append(error_msg)
                result["delegation_errors"].append(error_msg)
                continue

            delegate_targets_value = directory_info.get(
                "delegate_targets") or []
            if isinstance(delegate_targets_value, list):
                delegate_targets = delegate_targets_value
            else:
                delegate_targets = []
            if delegate_targets:
                delegate_targets_str = ', '.join(
                    str(t) for t in delegate_targets)
                warning_msg = (
                    f"Host '{host}': Legacy constrained delegation is configured "
                    f"(msDS-AllowedToDelegateTo: {delegate_targets_str}). Remove these entries when using RBCD unless explicitly required."
                )
                logger.warning(warning_msg)
                result["warnings"].append(warning_msg)

            if directory_info.get("trusted_for_delegation"):
                error_msg = (
                    f"Host '{host}': Unconstrained delegation is enabled. Disable unconstrained delegation for RBCD deployments."
                )
                result["errors"].append(error_msg)
                result["delegation_errors"].append(error_msg)

            if directory_info.get("trusted_to_auth"):
                warning_msg = (
                    f"Host '{host}': Protocol transition delegation is enabled. This is not required for RBCD and should be disabled unless needed."
                )
                logger.warning(warning_msg)
                result["warnings"].append(warning_msg)

        if clusters:
            for cluster_name in sorted(cluster_names):
                directory_info = _ldap_get_computer_delegation_info(
                    cluster_name, realm)
                if directory_info is None:
                    warning_msg = (
                        f"Cluster '{cluster_name}': Delegation check skipped (LDAP connection unavailable)"
                    )
                    logger.warning(warning_msg)
                    result["warnings"].append(warning_msg)
                    continue

                if not directory_info.get("exists", True):
                    warning_msg = (
                        f"Cluster '{cluster_name}': Cluster Name Object not found in Active Directory"
                    )
                    logger.warning(warning_msg)
                    result["warnings"].append(warning_msg)
                    continue

                cluster_hosts = clusters.get(cluster_name, []) or []
                rbcd_principals = directory_info.get("rbcd_principals", [])
                rbcd_sid_strings = directory_info.get("rbcd_sid_strings", [])
                principals_list = (
                    rbcd_principals
                    if isinstance(rbcd_principals, list)
                    else []
                )
                sids_list = (
                    rbcd_sid_strings
                    if isinstance(rbcd_sid_strings, list)
                    else []
                )
                combined_principals = [
                    str(principal)
                    for principal in principals_list
                    if principal
                ]
                combined_principals.extend(
                    [str(sid) for sid in sids_list if sid]
                )

                allowed_tokens: Set[str] = set()
                for principal in combined_principals:
                    principal_lower = principal.strip().lower()
                    if principal_lower:
                        allowed_tokens.add(principal_lower)
                        tokenizer = PrincipalTokenizer
                        principal_tokens = tokenizer.normalize_principal(
                            principal_lower
                        )
                        allowed_tokens.update(principal_tokens)

                missing_hosts: List[str] = []
                for host in sorted(cluster_hosts):
                    tokenizer = PrincipalTokenizer
                    host_token_set = host_tokens.get(
                        host, tokenizer.normalize_host(host, realm)
                    )
                    is_disjoint = (
                        host_token_set and
                        host_token_set.isdisjoint(allowed_tokens)
                    )
                    if is_disjoint:
                        missing_hosts.append(host)

                unexpected_principals: List[str] = []
                expected_token_union = expected_host_tokens
                for principal in combined_principals:
                    tokens = PrincipalTokenizer.normalize_principal(principal)
                    tokens.add(principal.lower())
                    if tokens.isdisjoint(expected_token_union):
                        unexpected_principals.append(principal)

                rbcd_present = bool(directory_info.get("rbcd_present"))

                if not rbcd_present:
                    error_msg = (
                        f"Cluster '{cluster_name}': Resource-based constrained delegation is not configured. "
                        f"Allow the Hyper-V hosts {', '.join(cluster_hosts) if cluster_hosts else '<unknown>'} to delegate to the cluster object."
                    )
                    result["errors"].append(error_msg)
                    result["delegation_errors"].append(error_msg)
                    continue

                if missing_hosts:
                    error_msg = (
                        f"Cluster '{cluster_name}': RBCD is missing delegation entries for host(s): {', '.join(missing_hosts)}. "
                        "Update the cluster object's msDS-AllowedToActOnBehalfOfOtherIdentity to include these hosts."
                    )
                    result["errors"].append(error_msg)
                    result["delegation_errors"].append(error_msg)

                if unexpected_principals:
                    warning_msg = (
                        f"Cluster '{cluster_name}': RBCD allows unexpected principals: {', '.join(unexpected_principals)}. "
                        "Only Hyper-V host computer accounts required for delegation should be listed."
                    )
                    logger.warning(warning_msg)
                    result["warnings"].append(warning_msg)
    else:
        logger.debug("No hosts available for delegation validation")

    return result


__all__ = [
    "KerberosManager",
    "KerberosManagerError",
    "initialize_kerberos",
    "get_kerberos_manager",
    "cleanup_kerberos",
    "validate_host_kerberos_setup",
]
