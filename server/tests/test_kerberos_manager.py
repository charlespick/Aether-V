"""Unit tests for Kerberos manager service."""

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.kerberos_manager import (
    KerberosManager,
    KerberosManagerError,
    initialize_kerberos,
    cleanup_kerberos,
    get_kerberos_manager,
)


@pytest.fixture
def sample_keytab_b64():
    """Return a base64-encoded sample keytab."""
    # This is a minimal valid keytab structure (not a real keytab)
    fake_keytab = b"\x05\x02\x00\x00\x00\x00\x00\x00"
    return base64.b64encode(fake_keytab).decode("utf-8")


@pytest.fixture
def kerberos_manager(sample_keytab_b64):
    """Return a KerberosManager instance."""
    manager = KerberosManager(
        principal="test-user@EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
        realm="EXAMPLE.COM",
        kdc="kdc.example.com",
    )
    yield manager
    # Cleanup after test
    if manager.is_initialized:
        manager.cleanup()


def test_kerberos_manager_initialization(kerberos_manager, sample_keytab_b64, tmp_path):
    """Test that KerberosManager initializes correctly."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        # Mock the keytab path
        mock_keytab = MagicMock()
        mock_keytab.exists.return_value = True
        mock_path.return_value = mock_keytab
        
        kerberos_manager.initialize()
        
        assert kerberos_manager.is_initialized
        assert kerberos_manager.principal == "test-user@EXAMPLE.COM"
        assert kerberos_manager.realm == "EXAMPLE.COM"
        assert kerberos_manager.kdc == "kdc.example.com"


def test_kerberos_manager_writes_keytab(kerberos_manager, tmp_path):
    """Test that keytab is written with correct permissions."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_path.return_value = mock_keytab
        
        kerberos_manager.initialize()
        
        # Verify keytab was written
        mock_keytab.write_bytes.assert_called_once()
        # Verify permissions were set to 600
        mock_keytab.chmod.assert_called_once_with(0o600)


def test_kerberos_manager_invalid_base64(tmp_path):
    """Test that invalid base64 keytab raises error."""
    manager = KerberosManager(
        principal="test-user@EXAMPLE.COM",
        keytab_b64="invalid-base64-!!!",
    )
    
    with pytest.raises(KerberosManagerError, match="Failed to write keytab"):
        manager.initialize()


def test_kerberos_manager_cleanup(kerberos_manager):
    """Test that cleanup removes keytab file."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_keytab.exists.return_value = True
        mock_path.return_value = mock_keytab
        
        kerberos_manager.initialize()
        kerberos_manager.cleanup()
        
        # Verify keytab was removed
        mock_keytab.unlink.assert_called_once()
        assert not kerberos_manager.is_initialized


def test_kerberos_manager_double_initialization(kerberos_manager):
    """Test that double initialization is handled correctly."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_path.return_value = mock_keytab
        
        kerberos_manager.initialize()
        first_initialized = kerberos_manager.is_initialized
        
        # Second initialization should be a no-op
        kerberos_manager.initialize()
        
        assert first_initialized == kerberos_manager.is_initialized


def test_global_kerberos_manager_initialize(sample_keytab_b64):
    """Test global Kerberos manager initialization."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_path.return_value = mock_keytab
        
        initialize_kerberos(
            principal="global-test@EXAMPLE.COM",
            keytab_b64=sample_keytab_b64,
        )
        
        manager = get_kerberos_manager()
        assert manager is not None
        assert manager.principal == "global-test@EXAMPLE.COM"
        
        # Cleanup
        cleanup_kerberos()
        assert get_kerberos_manager() is None


def test_global_kerberos_manager_reinitialize(sample_keytab_b64):
    """Test that reinitializing global manager cleans up previous instance."""
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_path.return_value = mock_keytab
        
        # First initialization
        initialize_kerberos(
            principal="first@EXAMPLE.COM",
            keytab_b64=sample_keytab_b64,
        )
        
        # Second initialization should cleanup first
        initialize_kerberos(
            principal="second@EXAMPLE.COM",
            keytab_b64=sample_keytab_b64,
        )
        
        manager = get_kerberos_manager()
        assert manager.principal == "second@EXAMPLE.COM"
        
        # Cleanup
        cleanup_kerberos()


def test_keytab_bytes_decoding(sample_keytab_b64):
    """Test that keytab bytes are decoded correctly."""
    manager = KerberosManager(
        principal="test@EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
    )
    
    # Decode manually to compare
    expected_bytes = base64.b64decode(sample_keytab_b64)
    
    with patch("app.services.kerberos_manager.Path") as mock_path:
        mock_keytab = MagicMock()
        mock_path.return_value = mock_keytab
        
        manager.initialize()
        
        # Check that write_bytes was called with correct data
        call_args = mock_keytab.write_bytes.call_args
        assert call_args is not None
        actual_bytes = call_args[0][0]
        assert actual_bytes == expected_bytes
