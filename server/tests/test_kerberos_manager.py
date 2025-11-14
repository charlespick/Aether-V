"""Unit tests for Kerberos manager service."""

import base64

from unittest.mock import MagicMock, patch

import pytest

from app.services.kerberos_manager import (
    KerberosManager,
    KerberosManagerError,
    initialize_kerberos,
    cleanup_kerberos,
    get_kerberos_manager,
)


@pytest.fixture(autouse=True)
def mock_gssapi_components():
    """Auto-mock gssapi components for all tests in this file."""
    with patch("app.services.kerberos_manager.gssapi.Name") as mock_name_cls:
        with patch("app.services.kerberos_manager.gssapi_raw.acquire_cred_from") as mock_acquire:
            with patch("app.services.kerberos_manager.gssapi.Credentials") as mock_creds_cls:
                # Mock gssapi.Name to return a mock with .raw attribute
                mock_name = MagicMock()
                mock_name.raw = MagicMock()
                mock_name_cls.return_value = mock_name
                
                # Mock acquire_cred_from to return mock credentials
                mock_raw_creds = MagicMock()
                mock_raw_creds.creds = MagicMock()
                mock_acquire.return_value = mock_raw_creds
                
                # Mock gssapi.Credentials wrapper
                mock_creds_instance = MagicMock()
                mock_creds_instance.lifetime = 86400
                mock_creds_cls.return_value = mock_creds_instance
                
                yield


@pytest.fixture
def sample_keytab_b64():
    """Return a base64-encoded sample keytab."""
    # This is a minimal valid keytab structure (not a real keytab).
    # The bytes below represent the keytab file version header (0x05 0x02 for version 2),
    # followed by six zero bytes. This is sufficient for mocking keytab presence in tests.
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
    manager.cleanup()


def test_kerberos_manager_initialization(kerberos_manager, sample_keytab_b64):
    """Test that KerberosManager initializes correctly."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write"):
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp for keytab and cache
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_cache_path = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
                            kerberos_manager.initialize()
                            
                            assert kerberos_manager.is_initialized
                            assert kerberos_manager.principal == "test-user@EXAMPLE.COM"
                            assert kerberos_manager.realm == "EXAMPLE.COM"
                            assert kerberos_manager.kdc == "kdc.example.com"


def test_kerberos_manager_writes_keytab(kerberos_manager):
    """Test that keytab is written with correct permissions."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write") as mock_write:
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod") as mock_chmod:
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_cache_path = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
                            kerberos_manager.initialize()
                            
                            # Verify keytab was written via os.write
                            assert mock_write.call_count == 1
                            # Verify keytab permissions were set to 600
                            assert any(call[0][1] == 0o600 for call in mock_chmod.call_args_list)


def test_kerberos_manager_invalid_base64():
    """Test that invalid base64 keytab raises error."""
    manager = KerberosManager(
        principal="test-user@EXAMPLE.COM",
        keytab_b64="invalid-base64-!!!",
    )
    
    with pytest.raises(KerberosManagerError, match="Failed to write keytab"):
        manager.initialize()


def test_kerberos_manager_realm_auto_detection(sample_keytab_b64):
    """Test that realm is auto-detected from principal when not explicitly provided."""
    # Test with realm auto-detection
    manager = KerberosManager(
        principal="test-user@AUTO.EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
    )
    assert manager.realm == "AUTO.EXAMPLE.COM"
    assert manager.principal == "test-user@AUTO.EXAMPLE.COM"
    manager.cleanup()
    
    # Test with explicit realm override
    manager2 = KerberosManager(
        principal="test-user@AUTO.EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
        realm="OVERRIDE.EXAMPLE.COM",
    )
    assert manager2.realm == "OVERRIDE.EXAMPLE.COM"
    manager2.cleanup()
    
    # Test with principal without realm
    manager3 = KerberosManager(
        principal="test-user",
        keytab_b64=sample_keytab_b64,
    )
    assert manager3.realm is None
    manager3.cleanup()



def test_kerberos_manager_cleanup(kerberos_manager):
    """Test that cleanup removes keytab file."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write"):
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_keytab_path.exists.return_value = True
                            mock_cache_path = MagicMock()
                            mock_cache_path.exists.return_value = True
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
                            kerberos_manager.initialize()
                            kerberos_manager.cleanup()
                            
                            # Verify keytab was removed
                            mock_keytab_path.unlink.assert_called_once()
                            # Verify cache path was removed
                            mock_cache_path.unlink.assert_called()
                            assert not kerberos_manager.is_initialized


def test_kerberos_manager_double_initialization(kerberos_manager):
    """Test that double initialization is handled correctly."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write"):
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_cache_path = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
                            kerberos_manager.initialize()
                            first_initialized = kerberos_manager.is_initialized
                            
                            # Second initialization should be a no-op
                            kerberos_manager.initialize()
                            
                            assert first_initialized == kerberos_manager.is_initialized


def test_global_kerberos_manager_initialize(sample_keytab_b64):
    """Test global Kerberos manager initialization."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write"):
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 global-test@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_cache_path = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
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
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write"):
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist - different principals for each init
                            mock_subprocess.side_effect = [
                                MagicMock(returncode=0, stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 first@EXAMPLE.COM\n"),
                                MagicMock(returncode=0, stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 second@EXAMPLE.COM\n"),
                            ]
                            
                            # Mock tempfile.mkstemp - will be called twice (2 files per init, 2 inits)
                            mock_mkstemp.side_effect = [
                                (1, "/tmp/aetherv_test1.keytab"), (2, "/tmp/krb5cc_test1"),
                                (3, "/tmp/aetherv_test2.keytab"), (4, "/tmp/krb5cc_test2")
                            ]
                            
                            # Mock Path instances for both initializations
                            mock_keytab_path1 = MagicMock()
                            mock_cache_path1 = MagicMock()
                            mock_keytab_path2 = MagicMock()
                            mock_cache_path2 = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path1, mock_cache_path1, mock_keytab_path2, mock_cache_path2]
                            
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
    
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
            with patch("app.services.kerberos_manager.os.write") as mock_write:
                with patch("app.services.kerberos_manager.os.close"):
                    with patch("app.services.kerberos_manager.os.chmod"):
                        with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                            # Mock subprocess for klist with correct principal
                            mock_subprocess.return_value = MagicMock(
                                returncode=0,
                                stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test@EXAMPLE.COM\n"
                            )
                            
                            # Mock tempfile.mkstemp
                            mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                            
                            # Mock Path instances
                            mock_keytab_path = MagicMock()
                            mock_cache_path = MagicMock()
                            mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                            
                            manager.initialize()
                            
                            # Check that os.write was called with correct data
                            assert mock_write.call_count == 1
                            call_args = mock_write.call_args
                            assert call_args is not None
                            actual_bytes = call_args[0][1]
                            assert actual_bytes == expected_bytes


def test_credential_acquisition_failure(kerberos_manager):
    """Test that credential acquisition failure is handled properly."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        with patch("app.services.kerberos_manager.gssapi_raw.acquire_cred_from") as mock_acquire:
            with patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp:
                with patch("app.services.kerberos_manager.os.write"):
                    with patch("app.services.kerberos_manager.os.close"):
                        with patch("app.services.kerberos_manager.os.chmod"):
                            with patch("app.services.kerberos_manager.Path") as mock_path_cls:
                                # Mock subprocess for klist with correct principal
                                mock_subprocess.return_value = MagicMock(
                                    returncode=0,
                                    stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n"
                                )
                                
                                # Mock tempfile.mkstemp
                                mock_mkstemp.side_effect = [(1, "/tmp/aetherv_test.keytab"), (2, "/tmp/krb5cc_test")]
                                
                                # Mock Path instances
                                mock_keytab_path = MagicMock()
                                mock_cache_path = MagicMock()
                                mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]
                                
                                # Simulate credential acquisition failure
                                class DummyGSSError(Exception):
                                    def __init__(self, *args, **kwargs):
                                        super().__init__(*args)
                                mock_acquire.side_effect = DummyGSSError(1, 2)
                                
                                with pytest.raises(KerberosManagerError, match="Kerberos initialization failed"):
                                    kerberos_manager.initialize()
