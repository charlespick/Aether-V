"""Unit tests for Kerberos manager service."""

import base64
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

# Provide stub gssapi modules when the real package is unavailable
sys.modules.setdefault("gssapi", MagicMock())
sys.modules.setdefault("gssapi.raw", MagicMock())

import pytest

from app.services.kerberos_manager import (
    KerberosManager,
    KerberosManagerError,
    _check_cluster_allowed_to_delegate,
    _check_cluster_delegation,
    _check_host_delegation_legacy,
    _check_wsman_spn,
    cleanup_kerberos,
    get_kerberos_manager,
    initialize_kerberos,
    validate_host_kerberos_setup,
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
    )
    yield manager
    # Cleanup after test
    manager.cleanup()


def test_kerberos_manager_initialization(kerberos_manager, sample_keytab_b64):
    """Test that KerberosManager initializes correctly."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
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


def test_kerberos_manager_writes_keytab(kerberos_manager):
    """Test that keytab is written with correct permissions."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write") as mock_write, \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod") as mock_fchmod, \
         patch("app.services.kerberos_manager.os.chmod") as mock_chmod, \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
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
        # Verify keytab permissions were set to 600 using fchmod
        mock_fchmod.assert_any_call(1, 0o600)


def test_kerberos_manager_invalid_base64():
    """Test that invalid base64 keytab raises error."""
    manager = KerberosManager(
        principal="test-user@EXAMPLE.COM",
        keytab_b64="invalid-base64-!!!",
    )
    
    with pytest.raises(KerberosManagerError, match="Failed to write keytab"):
        manager.initialize()


def test_validate_keytab_missing_principal(sample_keytab_b64):
    """klist output without the principal should raise an informative error."""

    manager = KerberosManager(
        principal="user@EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
    )

    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   1 other@EXAMPLE.COM\n",
        )

        with pytest.raises(KerberosManagerError, match="Keytab does not contain principal"):
            manager.initialize()

    manager.cleanup()


def test_validate_keytab_missing_klist(sample_keytab_b64):
    """Missing klist binary should raise a helpful error message."""

    manager = KerberosManager(
        principal="user@EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
    )

    with patch("app.services.kerberos_manager.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(KerberosManagerError, match="klist command not found"):
            manager.initialize()

    manager.cleanup()


def test_configure_kdc_requires_realm(sample_keytab_b64):
    """Providing a KDC without a realm should raise an error."""

    manager = KerberosManager(
        principal="user",
        keytab_b64=sample_keytab_b64,
        kdc="kdc.example.com",
    )

    with pytest.raises(KerberosManagerError, match="requires a Kerberos realm"):
        manager._configure_kdc_override()


def test_acquire_credentials_falls_back_to_kinit(kerberos_manager):
    """When acquire_cred_from is missing we should fall back to kinit."""

    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls, \
         patch("app.services.kerberos_manager.gssapi_raw.acquire_cred_from", side_effect=AttributeError), \
         patch.object(KerberosManager, "_acquire_credentials_via_kinit") as mock_kinit, \
         patch("app.services.kerberos_manager.gssapi.Credentials") as mock_creds:

        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
        )

        mock_mkstemp.side_effect = [
            (1, "/tmp/aetherv_test.keytab"),
            (2, "/tmp/krb5cc_test"),
        ]

        mock_keytab_path = MagicMock()
        mock_cache_path = MagicMock()
        mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path]

        kerberos_manager.initialize()

        mock_kinit.assert_called_once()
        mock_creds.assert_called()


def test_acquire_credentials_via_kinit_success(monkeypatch):
    """Successful kinit execution should pass without raising."""

    manager = KerberosManager(principal="user@EXAMPLE.COM", keytab_b64="")
    manager._keytab_path = Path("/tmp/test.keytab")
    manager._cache_path = Path("/tmp/test.cache")

    called_commands = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        called_commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("app.services.kerberos_manager.subprocess.run", fake_run)

    manager._acquire_credentials_via_kinit()

    assert any("kinit" in part for part in called_commands[0])


def test_acquire_credentials_via_kinit_failure(monkeypatch):
    """kinit failures should surface as KerberosManagerError."""

    manager = KerberosManager(principal="user@EXAMPLE.COM", keytab_b64="")
    manager._keytab_path = Path("/tmp/test.keytab")
    manager._cache_path = Path("/tmp/test.cache")

    error = subprocess.CalledProcessError(returncode=1, cmd=["kinit"], stderr="bad keytab")

    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=error),
    )

    with pytest.raises(KerberosManagerError, match="kinit failed: bad keytab"):
        manager._acquire_credentials_via_kinit()


def test_check_wsman_spn_uses_kvno_when_setspn_missing(monkeypatch):
    """setspn absence should fall back to kvno validation."""

    def fake_run(cmd, capture_output=True, text=True, timeout=15):
        if cmd[0] == "setspn":
            raise FileNotFoundError
        assert cmd[0] == "kvno"
        return SimpleNamespace(returncode=0, stdout="ticket", stderr="")

    monkeypatch.setattr("app.services.kerberos_manager.subprocess.run", fake_run)

    success, message = _check_wsman_spn("hyperv01", realm="EXAMPLE.COM")

    assert success
    assert "kvno" in message.lower()


def test_check_wsman_spn_reports_missing_tools(monkeypatch):
    """If neither setspn nor kvno is present we should surface a failure."""

    def fake_run(cmd, capture_output=True, text=True, timeout=15):
        raise FileNotFoundError

    monkeypatch.setattr("app.services.kerberos_manager.subprocess.run", fake_run)

    success, message = _check_wsman_spn("hyperv02")

    assert not success
    assert "not available" in message.lower()


def test_check_cluster_delegation_reports_missing_rbcd(monkeypatch):
    """Cluster delegation without RBCD should return False and guidance."""

    stdout = "NO_RBCD"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_delegation("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is False
    assert "Resource-Based Constrained Delegation" in message


def test_check_cluster_delegation_flags_missing_hosts(monkeypatch):
    """When a cluster host lacks delegation it should be reported as an error."""

    stdout = "RBCD_CONFIGURED\nPrincipals: CONTOSO\\HV1$, CONTOSO\\HV2$"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_delegation(
        "ClusterA", ["hv1", "hv3"], realm="EXAMPLE.COM"
    )

    assert success is False
    assert "hv3" in message
    assert "Principals:" in message


def test_check_cluster_delegation_success_when_all_hosts_present(monkeypatch):
    """Delegation succeeds when every cluster host is represented in the ACL."""

    stdout = "RBCD_CONFIGURED\nPrincipals: CONTOSO\\HV1$, WSMAN/hv2.contoso.com"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_delegation(
        "ClusterA", ["HV1", "hv2.contoso.com"], realm="EXAMPLE.COM"
    )

    assert success is True
    assert "Principals:" in message


def test_check_cluster_delegation_not_found(monkeypatch):
    """Missing cluster objects should produce an actionable error."""

    stdout = "ERROR: Cannot be found"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_delegation("ClusterMissing", ["hv1"], realm="EXAMPLE.COM")

    assert success is False
    assert "not found" in message.lower()


def test_check_cluster_delegation_skips_when_powershell_missing(monkeypatch):
    """FileNotFoundError should indicate the check was skipped."""

    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=FileNotFoundError),
    )

    success, message = _check_cluster_delegation("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is None
    assert "skipped" in message.lower()


def test_check_cluster_allowed_to_delegate_success(monkeypatch):
    """Delegation targets should report success with details."""

    stdout = "DELEGATION_TARGETS\nTargets: WSMAN/hv1"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_allowed_to_delegate("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is True
    assert "Targets:" in message


def test_check_cluster_allowed_to_delegate_not_found(monkeypatch):
    """Not found errors should return False for delegation targets."""

    stdout = "ERROR: Object cannot be found"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_cluster_allowed_to_delegate("ClusterMissing", [], realm="EXAMPLE.COM")

    assert success is False
    assert "not found" in message.lower()


def test_check_host_delegation_legacy_reports_missing(monkeypatch):
    """Legacy host delegation should report when delegation is absent."""

    stdout = "NO_DELEGATION"
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")),
    )

    success, message = _check_host_delegation_legacy("hyperv01")

    assert success is False
    assert "No delegation" in message
def test_kerberos_manager_cleanup(kerberos_manager):
    """Test that cleanup removes keytab file."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
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
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
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
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 global-test@EXAMPLE.COM\n",
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
        assert manager.realm == "EXAMPLE.COM"

        # Cleanup
        cleanup_kerberos()
        assert get_kerberos_manager() is None


def test_global_kerberos_manager_reinitialize(sample_keytab_b64):
    """Test that reinitializing global manager cleans up previous instance."""
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
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
    
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write") as mock_write, \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test@EXAMPLE.COM\n",
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
    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.gssapi_raw.acquire_cred_from") as mock_acquire, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod"), \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:
        # Mock subprocess for klist with correct principal
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
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


def test_validate_host_kerberos_setup_reports_missing_cluster_delegation(monkeypatch):
    """Missing msDS-AllowedToDelegateTo entries should be reported as errors."""

    def fake_run(cmd, capture_output=True, text=True, timeout=20):
        script = cmd[-1]
        if "msDS-AllowedToActOnBehalfOfOtherIdentity" in script:
            return MagicMock(
                returncode=0,
                stdout="RBCD_CONFIGURED\nPrincipals: CONTOSO\\HYPERV01$",
                stderr="",
            )
        if "msDS-AllowedToDelegateTo" in script:
            return MagicMock(returncode=0, stdout="NO_DELEGATION_TARGETS", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("app.services.kerberos_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "app.services.kerberos_manager._check_wsman_spn",
        lambda host, realm=None: (True, "WSMAN SPN validated"),
    )

    result = validate_host_kerberos_setup(
        hosts=[],
        realm="EXAMPLE.COM",
        clusters={"ClusterA": ["hyperv01", "hyperv02"]},
    )

    assert any(
        "msDS-AllowedToDelegateTo" in error for error in result["delegation_errors"]
    )
    assert result["errors"], "Expected errors when delegation targets are missing"


def test_validate_host_kerberos_setup_succeeds_with_delegation(monkeypatch):
    """Delegation checks should pass when targets are configured."""

    def fake_run(cmd, capture_output=True, text=True, timeout=20):
        script = cmd[-1]
        if "msDS-AllowedToActOnBehalfOfOtherIdentity" in script:
            return MagicMock(
                returncode=0,
                stdout="RBCD_CONFIGURED\nPrincipals: CONTOSO\\HYPERV01$",
                stderr="",
            )
        if "msDS-AllowedToDelegateTo" in script:
            return MagicMock(
                returncode=0,
                stdout="DELEGATION_TARGETS\nTargets: WSMAN/hyperv01",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("app.services.kerberos_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "app.services.kerberos_manager._check_wsman_spn",
        lambda host, realm=None: (True, "WSMAN SPN validated"),
    )

    result = validate_host_kerberos_setup(
        hosts=[],
        realm="EXAMPLE.COM",
        clusters={"ClusterA": ["hyperv01"]},
    )

    assert not result["delegation_errors"], "Delegation errors should not be reported"
    assert not result["warnings"], "No warnings expected when checks succeed"


def test_kdc_override_sets_krb5_config(monkeypatch, sample_keytab_b64):
    """KDC overrides should materialize a temporary krb5.conf and set KRB5_CONFIG."""

    manager = KerberosManager(
        principal="test-user@EXAMPLE.COM",
        keytab_b64=sample_keytab_b64,
        realm="EXAMPLE.COM",
        kdc="kdc.example.com",
    )

    monkeypatch.delenv("KRB5_CONFIG", raising=False)

    with patch("app.services.kerberos_manager.subprocess.run") as mock_subprocess, \
         patch("app.services.kerberos_manager.tempfile.mkstemp") as mock_mkstemp, \
         patch("app.services.kerberos_manager.os.write"), \
         patch("app.services.kerberos_manager.os.close"), \
         patch("app.services.kerberos_manager.os.fchmod"), \
         patch("app.services.kerberos_manager.os.chmod") as mock_chmod, \
         patch("app.services.kerberos_manager.Path") as mock_path_cls:

        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Keytab name: FILE:/tmp/test.keytab\nKVNO Principal\n---- ----\n   2 test-user@EXAMPLE.COM\n",
        )

        mock_mkstemp.side_effect = [
            (1, "/tmp/aetherv_test.keytab"),
            (2, "/tmp/krb5cc_test"),
            (3, "/tmp/krb5_override.conf"),
        ]

        mock_keytab_path = MagicMock()
        mock_keytab_path.__str__.return_value = "/tmp/aetherv_test.keytab"
        mock_cache_path = MagicMock()
        mock_cache_path.__str__.return_value = "/tmp/krb5cc_test"
        mock_conf_path = MagicMock()
        mock_conf_path.__str__.return_value = "/tmp/krb5_override.conf"
        mock_conf_path.exists.return_value = True

        mock_path_cls.side_effect = [mock_keytab_path, mock_cache_path, mock_conf_path]

        manager.initialize()

        mock_conf_path.write_text.assert_called_once()
        written_conf = mock_conf_path.write_text.call_args[0][0]
        assert "kdc = kdc.example.com" in written_conf
        assert mock_conf_path.write_text.call_args[1].get("encoding") == "utf-8"
        mock_chmod.assert_any_call(mock_conf_path, 0o600)
        assert os.environ.get("KRB5_CONFIG") == "/tmp/krb5_override.conf"

        manager.cleanup()

        mock_conf_path.unlink.assert_called_once()
        assert "KRB5_CONFIG" not in os.environ
