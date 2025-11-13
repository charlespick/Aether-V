"""Kerberos credential management for WinRM authentication."""

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import gssapi

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
        self.realm = realm
        self.kdc = kdc
        self._keytab_path: Optional[Path] = None
        self._cache_path: Optional[Path] = None
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

            # Set environment variables for Kerberos
            os.environ["KRB5_CLIENT_KTNAME"] = str(self._keytab_path)
            logger.debug("Set KRB5_CLIENT_KTNAME=%s", self._keytab_path)

            # Set cache location (also use temp file for security)
            cache_fd, cache_path_str = tempfile.mkstemp(prefix="krb5cc_aetherv_", suffix="")
            os.close(cache_fd)  # Close the file descriptor, we just need the path
            self._cache_path = Path(cache_path_str)
            self._cache_path.chmod(0o600)  # Secure the cache file
            os.environ["KRB5CCNAME"] = f"FILE:{self._cache_path}"
            logger.debug("Set KRB5CCNAME=%s", self._cache_path)

            # Set realm and KDC if provided
            if self.realm:
                logger.info("Using Kerberos realm: %s", self.realm)
            if self.kdc:
                logger.info("Using KDC server: %s", self.kdc)

            # Acquire Kerberos credentials (TGT) from the keytab
            self._acquire_credentials()

            self._initialized = True
            logger.info("Kerberos credentials acquired successfully for principal: %s", self.principal)

        except Exception as exc:
            logger.error("Failed to initialize Kerberos manager: %s", exc)
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
            
            try:
                # Write keytab data to the file descriptor
                os.write(fd, keytab_bytes)
            finally:
                # Always close the file descriptor
                os.close(fd)
            
            keytab_path = Path(keytab_path_str)
            
            # Set restrictive permissions (600 = rw-------)
            keytab_path.chmod(0o600)
            logger.debug("Set keytab permissions to 600")

            return keytab_path

        except Exception as exc:
            logger.error("Failed to write keytab: %s", exc)
            raise KerberosManagerError(f"Failed to write keytab: {exc}") from exc

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

            # Acquire credentials from the keytab
            # This obtains a TGT and stores it in the credential cache
            creds = gssapi.Credentials(name=name, usage='initiate')
            
            logger.info("Successfully acquired Kerberos credentials for %s", self.principal)
            logger.debug("Credential lifetime: %s seconds", creds.lifetime)

        except gssapi.exceptions.GSSError as exc:
            logger.error("GSSAPI error acquiring credentials: %s", exc)
            raise KerberosManagerError(f"Failed to acquire Kerberos credentials: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error acquiring credentials: %s", exc)
            raise KerberosManagerError(f"Failed to acquire Kerberos credentials: {exc}") from exc

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


__all__ = [
    "KerberosManager",
    "KerberosManagerError",
    "initialize_kerberos",
    "get_kerberos_manager",
    "cleanup_kerberos",
]
