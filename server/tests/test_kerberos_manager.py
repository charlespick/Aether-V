"""Unit tests for Kerberos manager service."""

import base64
import copy
import os
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

import pytest

from app.services.kerberos_manager import (
    KerberosManager,
    KerberosManagerError,
    _check_cluster_allowed_to_delegate,
    _check_cluster_delegation,
    _check_host_delegation_legacy,
    _check_wsman_spn,
    _extract_allowed_sids_from_security_descriptor,
    _format_ldap_server_target,
    _normalize_ldap_boolean,
    _parse_ldap_server_target,
    _sid_bytes_to_str,
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


def _build_security_descriptor_with_object_ace(sid_blob: bytes) -> bytes:
    """Construct a minimal self-relative security descriptor with an object ACE."""

    # Security descriptor header (self-relative, DACL present)
    header = bytearray(20)
    header[0] = 1  # Revision
    struct.pack_into("<H", header, 2, 0x0004)  # SE_DACL_PRESENT
    struct.pack_into("<I", header, 16, 20)  # DACL offset immediately after header

    # ACCESS_ALLOWED_OBJECT_ACE: header (4) + mask (4) + flags (4) + SID
    ace_size = 12 + len(sid_blob)
    ace = bytearray(ace_size)
    ace[0] = 0x05  # ACCESS_ALLOWED_OBJECT_ACE_TYPE
    struct.pack_into("<H", ace, 2, ace_size)
    struct.pack_into("<I", ace, 4, 0x00000001)  # ACCESS_MASK (arbitrary allow)
    struct.pack_into("<I", ace, 8, 0x00000000)  # Flags - no GUIDs present
    ace[12:] = sid_blob

    # ACL header plus the ACE payload
    acl_size = 8 + len(ace)
    acl = bytearray(8)
    acl[0] = 2  # ACL revision
    struct.pack_into("<H", acl, 2, acl_size)
    struct.pack_into("<H", acl, 4, 1)  # One ACE

    return bytes(header + acl + ace)


def _sid_from_components(*components: int) -> bytes:
    """Build a SID blob using the provided sub-authorities."""

    if not components:
        raise ValueError("At least one sub-authority is required")

    sid = bytearray()
    sid.append(1)  # Revision
    sid.append(len(components))
    sid.extend(b"\x00\x00\x00\x00\x00\x05")  # SECURITY_NT_AUTHORITY
    for value in components:
        sid.extend(struct.pack("<I", value))
    return bytes(sid)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("TRUE", True),
        ("false", False),
        ("1", True),
        ("0", False),
        (b"Yes", True),
        (b"no", False),
        ([], None),
        (None, None),
        ("maybe", None),
    ],
)
def test_normalize_ldap_boolean(value, expected):
    """LDAP boolean normalization should interpret typical encodings."""

    assert _normalize_ldap_boolean(value) is expected


@pytest.mark.parametrize(
    "target, expected_host, expected_port",
    [
        ("dc01.ad.example.com", "dc01.ad.example.com", None),
        ("dc01.ad.example.com:88", "dc01.ad.example.com", 88),
        ("[2001:db8::10]:636", "2001:db8::10", 636),
        ("server:3268", "server", 3268),
        (" :389 ", None, None),
    ],
)
def test_parse_ldap_server_target(target, expected_host, expected_port):
    """Target parsing should extract host and optional port information."""

    host, port = _parse_ldap_server_target(target)
    assert host == expected_host
    assert port == expected_port


@pytest.mark.parametrize(
    "host, port, expected",
    [
        ("dc01.ad.example.com", None, "dc01.ad.example.com"),
        ("dc01.ad.example.com", 636, "dc01.ad.example.com:636"),
        ("2001:db8::10", 3269, "[2001:db8::10]:3269"),
        ("[2001:db8::10]", 636, "[2001:db8::10]:636"),
    ],
)
def test_format_ldap_server_target(host, port, expected):
    """Formatting should preserve ports and ensure IPv6 literals are bracketed."""

    assert _format_ldap_server_target(host, port) == expected


def test_extract_allowed_sids_handles_object_ace():
    """Object ACE entries should yield SID blobs for RBCD lookups."""

    sid_blob = _sid_from_components(21, 1, 2, 3, 4)
    descriptor = _build_security_descriptor_with_object_ace(sid_blob)

    sids = _extract_allowed_sids_from_security_descriptor(descriptor)

    assert sids == [sid_blob]
    assert _sid_bytes_to_str(sid_blob) == "S-1-5-21-1-2-3-4"


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

    info = {
        "exists": True,
        "rbcd_present": False,
        "rbcd_principals": [],
        "rbcd_sid_strings": [],
        "delegate_targets": [],
        "delegate_present": False,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_delegation("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is False
    assert "Resource-Based Constrained Delegation" in message


def test_check_cluster_delegation_flags_missing_hosts(monkeypatch):
    """When a cluster host lacks delegation it should be reported as an error."""

    info = {
        "exists": True,
        "rbcd_present": True,
        "rbcd_principals": ["CONTOSO\\HV1$", "CONTOSO\\HV2$"],
        "rbcd_sid_strings": [],
        "delegate_targets": [],
        "delegate_present": False,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_delegation(
        "ClusterA", ["hv1", "hv3"], realm="EXAMPLE.COM"
    )

    assert success is False
    assert "hv3" in message
    assert "Principals:" in message


def test_check_cluster_delegation_success_when_all_hosts_present(monkeypatch):
    """Delegation succeeds when every cluster host is represented in the ACL."""

    info = {
        "exists": True,
        "rbcd_present": True,
        "rbcd_principals": ["CONTOSO\\HV1$", "WSMAN/hv2.contoso.com"],
        "rbcd_sid_strings": [],
        "delegate_targets": [],
        "delegate_present": False,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_delegation(
        "ClusterA", ["HV1", "hv2.contoso.com"], realm="EXAMPLE.COM"
    )

    assert success is True
    assert "Principals:" in message


def test_check_cluster_delegation_not_found(monkeypatch):
    """Missing cluster objects should produce an actionable error."""

    info = {"exists": False}

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_delegation("ClusterMissing", ["hv1"], realm="EXAMPLE.COM")

    assert success is False
    assert "not found" in message.lower()


def test_check_cluster_delegation_skips_when_ldap_unavailable(monkeypatch):
    """LDAP connectivity issues should cause the check to be skipped."""

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda *args, **kwargs: None,
    )

    success, message = _check_cluster_delegation("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is None
    lowered = message.lower()
    assert "skipped" in lowered
    assert "ldap" in lowered


def test_check_cluster_allowed_to_delegate_success(monkeypatch):
    """Delegation targets should report success with details."""

    info = {
        "exists": True,
        "rbcd_present": True,
        "rbcd_principals": [],
        "rbcd_sid_strings": [],
        "delegate_targets": ["WSMAN/hv1"],
        "delegate_present": True,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_allowed_to_delegate("ClusterA", ["hv1"], realm="EXAMPLE.COM")

    assert success is True
    assert "Targets:" in message


def test_check_cluster_allowed_to_delegate_not_found(monkeypatch):
    """Not found errors should return False for delegation targets."""

    info = {"exists": False}

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )

    success, message = _check_cluster_allowed_to_delegate("ClusterMissing", [], realm="EXAMPLE.COM")

    assert success is False
    assert "not found" in message.lower()


def test_check_host_delegation_legacy_reports_missing(monkeypatch):
    """Legacy host delegation should report when delegation is absent."""

    info = {
        "exists": True,
        "rbcd_present": False,
        "rbcd_principals": [],
        "rbcd_sid_strings": [],
        "delegate_targets": [],
        "delegate_present": False,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(info),
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
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

    cluster_info = {
        "exists": True,
        "rbcd_present": True,
        "rbcd_principals": ["CONTOSO\\HYPERV01$"],
        "rbcd_sid_strings": [],
        "delegate_targets": [],
        "delegate_present": False,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    def fake_ldap(name, realm=None):
        if name == "ClusterA":
            return copy.deepcopy(cluster_info)
        return None

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        fake_ldap,
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )
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

    cluster_info = {
        "exists": True,
        "rbcd_present": True,
        "rbcd_principals": ["CONTOSO\\HYPERV01$"],
        "rbcd_sid_strings": [],
        "delegate_targets": ["WSMAN/hyperv01"],
        "delegate_present": True,
        "trusted_to_auth": False,
        "trusted_for_delegation": False,
    }

    monkeypatch.setattr(
        "app.services.kerberos_manager._ldap_get_computer_delegation_info",
        lambda name, realm=None: copy.deepcopy(cluster_info) if name == "ClusterA" else None,
    )
    monkeypatch.setattr(
        "app.services.kerberos_manager.subprocess.run",
        MagicMock(side_effect=AssertionError("PowerShell should not be invoked")),
    )
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


def test_establish_ldap_connection_ignores_kdc_port(monkeypatch):
    """LDAP connections should ignore non-LDAP ports in the KDC override."""

    captured = {}

    class DummyServer:
        def __init__(self, host, **kwargs):
            captured["host"] = host
            captured["kwargs"] = kwargs

    class DummyConnection:
        def __init__(self, server, **kwargs):
            captured["server"] = server
            captured["connection_kwargs"] = kwargs

    monkeypatch.setattr("app.services.kerberos_manager.Server", DummyServer)
    monkeypatch.setattr("app.services.kerberos_manager.Connection", DummyConnection)
    monkeypatch.setattr("app.services.kerberos_manager.SASL", object())
    monkeypatch.setattr("app.services.kerberos_manager.KERBEROS", object())
    monkeypatch.setattr("app.services.kerberos_manager.BASE", object())
    monkeypatch.setattr("app.services.kerberos_manager.SUBTREE", object())
    monkeypatch.setattr("app.services.kerberos_manager.escape_filter_chars", lambda value: value)
    monkeypatch.setattr("app.services.kerberos_manager.NONE", object())

    from app.services.kerberos_manager import _establish_ldap_connection

    connection = _establish_ldap_connection("dc01.ad.example.com:88")

    assert connection is not None
    assert captured["host"] == "dc01.ad.example.com"
    assert captured["kwargs"].get("port") == 636
    assert captured["kwargs"].get("use_ssl") is True
    assert captured["connection_kwargs"]["sasl_mechanism"] is not None


def test_establish_ldap_connection_respects_ldaps_port(monkeypatch):
    """LDAPS default port should be passed to the ldap3 Server constructor."""

    captured = {}

    class DummyServer:
        def __init__(self, host, **kwargs):
            captured["host"] = host
            captured["kwargs"] = kwargs

    class DummyConnection:
        def __init__(self, server, **kwargs):
            captured["server"] = server
            captured["connection_kwargs"] = kwargs

    monkeypatch.setattr("app.services.kerberos_manager.Server", DummyServer)
    monkeypatch.setattr("app.services.kerberos_manager.Connection", DummyConnection)
    monkeypatch.setattr("app.services.kerberos_manager.SASL", object())
    monkeypatch.setattr("app.services.kerberos_manager.KERBEROS", object())
    monkeypatch.setattr("app.services.kerberos_manager.BASE", object())
    monkeypatch.setattr("app.services.kerberos_manager.SUBTREE", object())
    monkeypatch.setattr("app.services.kerberos_manager.escape_filter_chars", lambda value: value)
    monkeypatch.setattr("app.services.kerberos_manager.NONE", object())

    from app.services.kerberos_manager import _establish_ldap_connection

    connection = _establish_ldap_connection("dc01.ad.example.com:636")

    assert connection is not None
    assert captured["host"] == "dc01.ad.example.com"
    assert captured["kwargs"].get("port") == 636
    assert captured["kwargs"].get("use_ssl") is True
    assert captured["connection_kwargs"]["sasl_mechanism"] is not None


def test_establish_ldap_connection_respects_global_catalog_ldaps_port(monkeypatch):
    """LDAPS global catalog port 3269 should be honored when provided."""

    captured = {}

    class DummyServer:
        def __init__(self, host, **kwargs):
            captured["host"] = host
            captured["kwargs"] = kwargs

    class DummyConnection:
        def __init__(self, server, **kwargs):
            captured["server"] = server
            captured["connection_kwargs"] = kwargs

    monkeypatch.setattr("app.services.kerberos_manager.Server", DummyServer)
    monkeypatch.setattr("app.services.kerberos_manager.Connection", DummyConnection)
    monkeypatch.setattr("app.services.kerberos_manager.SASL", object())
    monkeypatch.setattr("app.services.kerberos_manager.KERBEROS", object())
    monkeypatch.setattr("app.services.kerberos_manager.BASE", object())
    monkeypatch.setattr("app.services.kerberos_manager.SUBTREE", object())
    monkeypatch.setattr("app.services.kerberos_manager.escape_filter_chars", lambda value: value)
    monkeypatch.setattr("app.services.kerberos_manager.NONE", object())

    from app.services.kerberos_manager import _establish_ldap_connection

    connection = _establish_ldap_connection("dc01.ad.example.com:3269")

    assert connection is not None
    assert captured["host"] == "dc01.ad.example.com"
    assert captured["kwargs"].get("port") == 3269
    assert captured["kwargs"].get("use_ssl") is True
    assert captured["connection_kwargs"]["sasl_mechanism"] is not None


def test_extract_domain_from_principal_lowercases_realm():
    """Kerberos principals should map to lowercase AD domains."""

    from app.services.kerberos_manager import _extract_domain_from_principal

    assert _extract_domain_from_principal("svc-account@EXAMPLE.COM") == "example.com"
    assert _extract_domain_from_principal("invalid") is None


def test_discover_ldap_server_hosts_uses_dns(monkeypatch):
    """LDAP discovery should query SRV records and return ordered DCs."""

    from app.services import kerberos_manager as km

    class DummyAnswer:
        def __init__(self, target: str, priority: int = 0, weight: int = 0):
            self.target = target
            self.priority = priority
            self.weight = weight

    class DummyResolver:
        def resolve(self, record: str, record_type: str):
            assert record == "_ldap._tcp.dc._msdcs.example.com"
            assert record_type == "SRV"
            return [
                DummyAnswer("dc2.example.com."),
                DummyAnswer("dc1.example.com.", priority=0, weight=10),
            ]

    monkeypatch.setattr(km, "dns_resolver", DummyResolver())
    monkeypatch.setattr(
        km,
        "get_kerberos_manager",
        lambda: SimpleNamespace(principal="svc-account@EXAMPLE.COM", realm=None, kdc=None),
    )

    hosts = km._discover_ldap_server_hosts("EXAMPLE.COM")

    assert hosts == ["dc1.example.com", "dc2.example.com"]


def test_discover_ldap_server_hosts_prefers_kdc_override(monkeypatch):
    """When a KDC override is configured, skip DNS discovery entirely."""

    from app.services import kerberos_manager as km

    resolver = MagicMock()
    resolver.resolve.side_effect = AssertionError("DNS should not be queried")

    manager = SimpleNamespace(
        principal="svc-account@EXAMPLE.COM",
        realm="EXAMPLE.COM",
        kdc="dc3.example.com:88",
    )

    monkeypatch.setattr(km, "dns_resolver", resolver)
    monkeypatch.setattr(km, "get_kerberos_manager", lambda: manager)

    hosts = km._discover_ldap_server_hosts("EXAMPLE.COM")

    assert hosts == ["dc3.example.com:88"]


def test_discover_ldap_server_hosts_uses_override_without_domain(monkeypatch):
    """The override should still provide a host when no realm or principal exists."""

    from app.services import kerberos_manager as km

    monkeypatch.setattr(km, "dns_resolver", MagicMock())
    monkeypatch.setattr(
        km,
        "get_kerberos_manager",
        lambda: SimpleNamespace(principal=None, realm=None, kdc="dc4.example.com"),
    )

    hosts = km._discover_ldap_server_hosts(None)

    assert hosts == ["dc4.example.com"]


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
