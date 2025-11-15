"""Kerberos credential management for WinRM authentication."""

import base64
import logging
import os
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from dns import resolver as dns_resolver

import gssapi
import gssapi.raw as gssapi_raw

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
    BASE = None  # type: ignore[assignment]
    KERBEROS = None  # type: ignore[assignment]
    SASL = None  # type: ignore[assignment]
    SUBTREE = None  # type: ignore[assignment]
    Connection = None  # type: ignore[assignment]
    Server = None  # type: ignore[assignment]
    NONE = None  # type: ignore[assignment]
    LDAPException = Exception  # type: ignore[assignment]
    escape_bytes = None  # type: ignore[assignment]
    escape_filter_chars = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


GENERIC_ALL_ACCESS_MASK = 0x10000000


@dataclass(frozen=True)
class ServiceAccountInfo:
    """Resolved information about the Aether-V service account."""

    distinguished_name: str
    sid: bytes
    sid_string: str
    sam_account_name: Optional[str] = None
    user_principal_name: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Return a human-friendly identifier for the account."""

        return (
            self.user_principal_name
            or self.sam_account_name
            or self.distinguished_name
            or self.sid_string
        )


@dataclass(frozen=True)
class ResolvedRbcdEntry:
    """Representation of an ACE within msDS-AllowedToActOnBehalfOfOtherIdentity."""

    sid: bytes
    sid_string: str
    access_mask: int
    resolved_name: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.resolved_name or self.sid_string

    def grants_generic_all(self) -> bool:
        return bool(self.access_mask & GENERIC_ALL_ACCESS_MASK)


class AllowedAce(NamedTuple):
    """Simplified representation of an ACCESS_ALLOWED ACE."""

    sid: bytes
    mask: int


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


def _realm_to_base_dn(realm: Optional[str]) -> Optional[str]:
    """Convert a Kerberos realm (e.g. EXAMPLE.COM) to a base DN."""

    if not realm:
        return None

    realm = realm.strip().strip(".")
    if not realm:
        return None

    parts = [part.strip() for part in realm.split(".") if part.strip()]
    if not parts:
        return None

    return ",".join(f"DC={part.lower()}" for part in parts)


def _extract_domain_from_principal(principal: Optional[str]) -> Optional[str]:
    """Convert a Kerberos principal into an AD DNS domain name."""

    if not principal or "@" not in principal:
        return None

    realm = principal.split("@", 1)[1].strip().strip(".")
    if not realm:
        return None

    return realm.lower()


def _candidate_domains_for_ldap(realm: Optional[str]) -> List[str]:
    """Gather potential AD domains from configuration hints."""

    domains: List[str] = []
    manager = get_kerberos_manager()

    principal_domain = _extract_domain_from_principal(manager.principal if manager else None)
    if principal_domain:
        domains.append(principal_domain)

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

    domains = _candidate_domains_for_ldap(realm)
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
            target = getattr(rdata, "target", None)
            if not target:
                continue
            host = str(target).rstrip(".")
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
            remainder = host[closing + 1 :]
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
        logger.warning("Unable to determine LDAP hostname from %r", server_host)
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
        logger.debug("Failed to query defaultNamingContext via LDAP: %s", exc, exc_info=True)

    return None


def _extract_allowed_aces_from_security_descriptor(descriptor: bytes) -> List[AllowedAce]:
    """Return simplified ACEs extracted from ACCESS_ALLOWED entries."""

    if not descriptor:
        return []

    if isinstance(descriptor, memoryview):
        descriptor = descriptor.tobytes()
    elif isinstance(descriptor, bytearray):
        descriptor = bytes(descriptor)

    if not isinstance(descriptor, (bytes, bytearray)):
        return []

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
    aces: List[AllowedAce] = []

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
            access_mask = struct.unpack_from("<I", data, cursor + 4)[0]
            sid_start = cursor + 8
            sid_blob = data[sid_start: cursor + ace_size]
            if sid_blob:
                aces.append(AllowedAce(bytes(sid_blob), access_mask))
        elif ace_type == 0x05:  # ACCESS_ALLOWED_OBJECT_ACE_TYPE
            if ace_size < 12:
                cursor += ace_size
                continue

            flags = struct.unpack_from("<I", data, cursor + 8)[0]
            access_mask = struct.unpack_from("<I", data, cursor + 4)[0]
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
                aces.append(AllowedAce(bytes(sid_blob), access_mask))

        cursor += ace_size

    return aces


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
            raw_sid_values = entry.entry_raw_attributes.get("objectSid") if entry.entry_raw_attributes else None
            if not raw_sid_values:
                continue
            raw_sid = raw_sid_values[0]
            if isinstance(raw_sid, memoryview):
                raw_sid = raw_sid.tobytes()
            sid_str = _sid_bytes_to_str(raw_sid)
            if not sid_str:
                continue

            attr_dict = entry.entry_attributes_as_dict or {}
            candidate = attr_dict.get("sAMAccountName") or attr_dict.get("cn") or attr_dict.get("name")
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


def _ldap_get_service_account_info(
    service_principal: str, realm: Optional[str]
) -> Optional[ServiceAccountInfo]:
    """Resolve the WinRM service account via LDAP and return its SID."""

    if Connection is None or escape_filter_chars is None:
        return None

    normalized = (service_principal or "").strip()
    if not normalized:
        return None

    server_hosts = _discover_ldap_server_hosts(realm)
    if not server_hosts:
        return None

    connection: Optional[Connection] = None
    bound_host: Optional[str] = None

    for server_host in server_hosts:
        connection = _establish_ldap_connection(server_host)
        if connection is not None:
            bound_host = server_host
            break

    if connection is None:
        return None

    try:
        manager = get_kerberos_manager()
        base_hint = _realm_to_base_dn(realm or (manager.realm if manager else None))
        base_dn = base_hint or _lookup_default_naming_context(connection)
        if not base_dn:
            return None

        conditions: Set[str] = set()

        if "/" in normalized:
            conditions.add(
                f"(servicePrincipalName={escape_filter_chars(normalized)})"
            )

        if "@" in normalized and "/" not in normalized:
            conditions.add(
                f"(userPrincipalName={escape_filter_chars(normalized)})"
            )

        sam_candidate = normalized
        if "@" in sam_candidate:
            sam_candidate = sam_candidate.split("@", 1)[0]

        if sam_candidate and "/" not in sam_candidate:
            conditions.add(
                f"(sAMAccountName={escape_filter_chars(sam_candidate)})"
            )
            if not sam_candidate.endswith("$"):
                conditions.add(
                    f"(sAMAccountName={escape_filter_chars(sam_candidate + '$')})"
                )

        if not conditions:
            return None

        if len(conditions) == 1:
            condition_filter = next(iter(conditions))
        else:
            condition_filter = "(|" + "".join(sorted(conditions)) + ")"

        search_filter = (
            f"(&(|(objectClass=user)(objectClass=computer)){condition_filter})"
        )

        try:
            connection.search(
                base_dn,
                search_filter,
                search_scope=SUBTREE,
                attributes=[
                    "objectSid",
                    "distinguishedName",
                    "sAMAccountName",
                    "userPrincipalName",
                ],
                size_limit=5,
            )
        except LDAPException as exc:  # pragma: no cover - environment specific
            logger.debug(
                "LDAP search for service principal '%s' failed: %s",
                service_principal,
                exc,
                exc_info=True,
            )
            return None

        best_entry = None
        for entry in connection.entries:
            raw_attrs = entry.entry_raw_attributes or {}
            sid_values = raw_attrs.get("objectSid")
            if not sid_values:
                continue
            attr_dict = entry.entry_attributes_as_dict or {}
            object_classes = {
                str(value).strip().lower()
                for value in attr_dict.get("objectClass", [])
                if value
            }
            if "user" in object_classes:
                best_entry = entry
                break
            if best_entry is None:
                best_entry = entry

        if best_entry is None:
            return None

        raw_attrs = best_entry.entry_raw_attributes or {}
        attr_dict = best_entry.entry_attributes_as_dict or {}

        sid_values = raw_attrs.get("objectSid") or []
        sid_bytes: Optional[bytes] = None
        if sid_values:
            first_value = sid_values[0]
            if isinstance(first_value, memoryview):
                sid_bytes = first_value.tobytes()
            elif isinstance(first_value, bytearray):
                sid_bytes = bytes(first_value)
            elif isinstance(first_value, bytes):
                sid_bytes = first_value

        if not sid_bytes:
            return None

        sid_string = _sid_bytes_to_str(sid_bytes)
        if not sid_string:
            return None

        def _attr_str(name: str) -> Optional[str]:
            value = attr_dict.get(name)
            if value is None:
                return None
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    candidate = str(item).strip()
                    if candidate:
                        return candidate
                return None
            candidate = str(value).strip()
            return candidate or None

        dn = (
            _attr_str("distinguishedName")
            or str(best_entry.entry_dn)
            if getattr(best_entry, "entry_dn", None)
            else ""
        )

        return ServiceAccountInfo(
            distinguished_name=dn,
            sid=sid_bytes,
            sid_string=sid_string,
            sam_account_name=_attr_str("sAMAccountName"),
            user_principal_name=_attr_str("userPrincipalName"),
        )
    finally:
        if connection is not None:
            logger.debug("Unbinding LDAP connection to %s", bound_host or "<unknown>")
            connection.unbind()


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
        base_hint = _realm_to_base_dn(realm or (manager.realm if manager else None))
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
                        "dNSHostName",
                        "sAMAccountName",
                        "distinguishedName",
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

        def _first_str(value: object) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    candidate = _first_str(item)
                    if candidate:
                        return candidate
                return None
            candidate = str(value).strip()
            return candidate or None

        sam_account_name = _first_str(attr_dict.get("sAMAccountName"))
        dns_host_name = _first_str(attr_dict.get("dNSHostName"))
        distinguished_name = _first_str(attr_dict.get("distinguishedName")) or (
            str(entry.entry_dn)
            if getattr(entry, "entry_dn", None)
            else None
        )

        delegation_principals = attr_dict.get("PrincipalsAllowedToDelegateToAccount") or []
        if isinstance(delegation_principals, str):
            delegation_principals = [delegation_principals]
        elif isinstance(delegation_principals, (tuple, set)):
            delegation_principals = list(delegation_principals)

        delegation_principals = [
            str(principal)
            for principal in delegation_principals
            if principal
        ]

        rbcd_values = raw_attrs.get("msDS-AllowedToActOnBehalfOfOtherIdentity") or []
        rbcd_aces: List[AllowedAce] = []
        for descriptor in rbcd_values:
            rbcd_aces.extend(
                _extract_allowed_aces_from_security_descriptor(descriptor)
            )

        sid_blobs: List[bytes] = [ace.sid for ace in rbcd_aces if ace.sid]

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

        resolved_rbcd_entries: List[ResolvedRbcdEntry] = []
        for ace in rbcd_aces:
            sid_str = _sid_bytes_to_str(ace.sid)
            if not sid_str:
                continue
            resolved_rbcd_entries.append(
                ResolvedRbcdEntry(
                    sid=ace.sid,
                    sid_string=sid_str,
                    access_mask=ace.mask,
                    resolved_name=principal_lookup.get(sid_str),
                )
            )

        delegate_targets = attr_dict.get("msDS-AllowedToDelegateTo") or []
        if isinstance(delegate_targets, str):
            delegate_targets = [delegate_targets]
        elif isinstance(delegate_targets, (tuple, set)):
            delegate_targets = list(delegate_targets)

        delegate_targets = [str(value) for value in delegate_targets if value]

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
            "rbcd_entries": resolved_rbcd_entries,
            "sam_account_name": sam_account_name,
            "dns_host_name": dns_host_name,
            "distinguished_name": distinguished_name,
            "delegate_targets": delegate_targets,
            "delegate_present": bool(delegate_targets),
            "trusted_to_auth": bool(trusted_to_auth),
            "trusted_for_delegation": bool(trusted_for_delegation),
        }
    finally:
        if connection is not None:
            logger.debug("Unbinding LDAP connection to %s", bound_host or "<unknown>")
            connection.unbind()



def validate_host_kerberos_setup(
    hosts: List[str],
    realm: Optional[str] = None,
    clusters: Optional[Dict[str, List[str]]] = None,
    service_principal: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Validate Kerberos prerequisites for Hyper-V hosts.

    Checks performed:
    1. Ensure each host exposes the expected WSMAN SPN.
    2. Confirm resource-based constrained delegation (RBCD) on every host computer
       object grants the Aether-V service account GenericAll rights.
    """

    result = {
        "errors": [],
        "warnings": [],
        "spn_errors": [],
        "delegation_errors": [],
    }

    host_list = [host for host in hosts if host]
    if host_list:
        logger.info("Validating Kerberos setup for %d host(s)", len(host_list))
        for host in host_list:
            success, message = _check_wsman_spn(host, realm)
            if not success:
                error_msg = f"Host '{host}': {message}"
                result["errors"].append(error_msg)
                result["spn_errors"].append(error_msg)
            else:
                logger.info("Host '%s': WSMAN SPN validated", host)
    elif not clusters:
        result["warnings"].append("No Hyper-V hosts configured to validate")

    delegation_hosts: Dict[str, str] = {}
    host_clusters: Dict[str, Set[str]] = {}

    def _add_host(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        candidate = name.strip()
        if not candidate:
            return None
        key = candidate.lower()
        if key not in delegation_hosts:
            delegation_hosts[key] = candidate
        return key

    for host in host_list:
        _add_host(host)

    if clusters:
        for cluster_name, cluster_hosts in clusters.items():
            if not cluster_hosts:
                continue
            for cluster_host in cluster_hosts:
                host_key = _add_host(cluster_host)
                if host_key is None:
                    continue
                host_clusters.setdefault(host_key, set()).add(cluster_name)

    if not delegation_hosts:
        logger.debug("No hosts available for delegation validation")
        return result

    resolved_principal = service_principal
    if resolved_principal is None:
        manager = get_kerberos_manager()
        if manager is not None:
            resolved_principal = manager.principal

    service_principal_clean = (
        resolved_principal.strip() if resolved_principal else ""
    )
    if not service_principal_clean:
        warning_msg = (
            "WinRM service account principal unavailable; skipping delegation validation"
        )
        logger.warning(warning_msg)
        result["warnings"].append(warning_msg)
        return result

    service_account_info = _ldap_get_service_account_info(
        service_principal_clean, realm
    )
    if service_account_info is None:
        warning_msg = (
            f"Unable to resolve service account '{service_principal_clean}' in Active Directory; "
            "skipping delegation validation"
        )
        logger.warning(warning_msg)
        result["warnings"].append(warning_msg)
        return result

    logger.info(
        "Validating resource-based delegation for %d host(s)",
        len(delegation_hosts),
    )

    service_sid = service_account_info.sid_string
    service_display = service_account_info.display_name

    def _format_host_prefix(host_label: str, clusters_for_host: Set[str]) -> str:
        if clusters_for_host:
            sorted_clusters = sorted(clusters_for_host)
            if len(sorted_clusters) == 1:
                return f"Cluster '{sorted_clusters[0]}': Host '{host_label}'"
            cluster_list = ", ".join(f"'{name}'" for name in sorted_clusters)
            return f"Clusters {cluster_list}: Host '{host_label}'"
        return f"Host '{host_label}'"

    def _format_existing(entries: List[ResolvedRbcdEntry]) -> str:
        if not entries:
            return "none"
        return ", ".join(
            f"{entry.display_name} (mask=0x{entry.access_mask:08x})"
            for entry in entries
        )

    for host_key, original_host in sorted(delegation_hosts.items()):
        directory_info = _ldap_get_computer_delegation_info(original_host, realm)
        if directory_info is None:
            warning_msg = (
                f"Host '{original_host}': Delegation check skipped (LDAP connection unavailable)"
            )
            logger.warning(warning_msg)
            result["warnings"].append(warning_msg)
            continue

        clusters_for_host = host_clusters.get(host_key, set())
        host_label = directory_info.get("dns_host_name") or original_host
        host_prefix = _format_host_prefix(host_label, clusters_for_host)

        if not directory_info.get("exists", True):
            error_msg = (
                f"{host_prefix}: Computer account not found in Active Directory. "
                f"Create the host computer object and grant '{service_display}' (SID {service_sid}) "
                "delegation via msDS-AllowedToActOnBehalfOfOtherIdentity."
            )
            result["errors"].append(error_msg)
            result["delegation_errors"].append(error_msg)
            continue

        rbcd_entries: List[ResolvedRbcdEntry] = list(
            directory_info.get("rbcd_entries") or []
        )
        attribute_present = bool(directory_info.get("rbcd_present"))
        sam_account_name = directory_info.get("sam_account_name")
        distinguished_name = directory_info.get("distinguished_name")
        computer_descriptor = (
            sam_account_name
            or distinguished_name
            or host_label
        )

        if not attribute_present or not rbcd_entries:
            reason = (
                "msDS-AllowedToActOnBehalfOfOtherIdentity is not set"
                if not attribute_present
                else "msDS-AllowedToActOnBehalfOfOtherIdentity has no delegation entries"
            )
            error_msg = (
                f"{host_prefix}: {reason}. Add '{service_display}' (SID {service_sid}) "
                f"to msDS-AllowedToActOnBehalfOfOtherIdentity on computer object '{computer_descriptor}'."
            )
            result["errors"].append(error_msg)
            result["delegation_errors"].append(error_msg)
            continue

        matching_entry = next(
            (entry for entry in rbcd_entries if entry.sid_string == service_sid),
            None,
        )

        if matching_entry is None:
            existing_summary = _format_existing(rbcd_entries)
            error_msg = (
                f"{host_prefix}: msDS-AllowedToActOnBehalfOfOtherIdentity does not include "
                f"the Aether-V service account '{service_display}' (SID {service_sid}). "
                f"Current entries: {existing_summary}. Update computer object '{computer_descriptor}' "
                "to delegate to the service account."
            )
            result["errors"].append(error_msg)
            result["delegation_errors"].append(error_msg)
            continue

        if not matching_entry.grants_generic_all():
            error_msg = (
                f"{host_prefix}: Delegation entry for '{service_display}' grants access mask "
                f"0x{matching_entry.access_mask:08x} which does not include GenericAll. "
                f"Update msDS-AllowedToActOnBehalfOfOtherIdentity on computer object '{computer_descriptor}' "
                "to grant GenericAll to the service account."
            )
            result["errors"].append(error_msg)
            result["delegation_errors"].append(error_msg)
            continue

        logger.info(
            "%s: Resource-based delegation validated for service account '%s'",
            host_prefix,
            service_display,
        )

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



def _check_host_delegation_legacy(
    host: str,
    realm: Optional[str] = None,
    *,
    directory_info: Optional[Dict[str, object]] = None,
) -> Tuple[Optional[bool], str]:
    """
    Check if delegation is configured for a host (LEGACY - not used for host validation).

    This checks the old-style delegation on individual host objects. Prefer
    validate_host_kerberos_setup for modern Resource-Based Constrained Delegation checks.

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
    if directory_info is None:
        directory_info = _ldap_get_computer_delegation_info(host, realm)

    if directory_info is None:
        return (
            None,
            "Delegation check skipped (LDAP connection unavailable)",
        )

    if not directory_info.get("exists", True):
        return (
            False,
            f"Computer object '{host}' not found in Active Directory. Ensure the host exists before configuring delegation.",
        )

    trusted_to_auth = bool(directory_info.get("trusted_to_auth"))
    trusted_for = bool(directory_info.get("trusted_for_delegation"))
    delegate_present = bool(directory_info.get("delegate_present"))
    delegate_targets = [
        str(target)
        for target in directory_info.get("delegate_targets", [])
        if target
    ]

    if trusted_to_auth or trusted_for or delegate_present:
        rbcd_info = ""
        if delegate_present and delegate_targets:
            rbcd_info = f" (RBCD: {', '.join(delegate_targets)})"
        return (True, f"Delegation configured{rbcd_info}")

    return (
        False,
        "No delegation configured. Set up Resource-Based Constrained Delegation (RBCD) "
        "for double-hop authentication.",
    )


__all__ = [
    "KerberosManager",
    "KerberosManagerError",
    "initialize_kerberos",
    "get_kerberos_manager",
    "cleanup_kerberos",
    "validate_host_kerberos_setup",
]
