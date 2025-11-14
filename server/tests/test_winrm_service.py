"""Unit tests for helpers in the WinRM service."""

from unittest.mock import MagicMock, patch

# Patch Kerberos configuration before importing services to prevent hanging subprocess calls
kerberos_config_patcher = patch('app.core.config.Settings.has_kerberos_config', return_value=False)
kerberos_config_patcher.start()
kerberos_principal_patcher = patch('app.core.config.Settings.winrm_kerberos_principal', None)
kerberos_principal_patcher.start()
kerberos_keytab_patcher = patch('app.core.config.Settings.winrm_keytab_b64', None)
kerberos_keytab_patcher.start()

from pypsrp.powershell import InformationRecord
from pypsrp.serializer import GenericComplexObject

from app.services.winrm_service import _PSRPStreamCursor, WinRMService



def test_stringify_prefers_complex_object_properties():
    obj = GenericComplexObject()
    obj.to_string = "System.Management.ManagementBaseObject"
    obj.adapted_properties = {
        "Name": "vm-01",
        "State": "Running",
    }
    obj.extended_properties = {"Notes": "Provisioned"}

    rendered = _PSRPStreamCursor._stringify(obj)

    assert rendered == "Name: vm-01\nState: Running\nNotes: Provisioned"


def test_stringify_handles_nested_complex_property_values():
    child = GenericComplexObject()
    child.to_string = "System.Management.ManagementBaseObject"
    child.adapted_properties = {"Status": "Healthy"}

    parent = GenericComplexObject()
    parent.to_string = "System.Management.ManagementBaseObject"
    parent.adapted_properties = {
        "Name": "vm-02",
        "Child": child,
        "Tags": ["compute", "lab"],
        "Metadata": {"owner": "ops"},
    }

    rendered = _PSRPStreamCursor._stringify(parent)

    assert rendered == (
        "Name: vm-02\n"
        "Child:\n"
        "  Status: Healthy\n"
        "Tags: compute, lab\n"
        "Metadata: owner=ops"
    )


def test_stringify_information_prefers_message_data_text():
    record = InformationRecord(message_data="Copy complete")

    rendered = _PSRPStreamCursor._stringify_information(record)

    assert rendered == "Copy complete"


def test_stringify_information_prefers_message_property_from_complex_data():
    payload = GenericComplexObject()
    payload.to_string = "System.Object"
    payload.adapted_properties = {"Message": "Transferring", "NoNewLine": False}

    record = InformationRecord(message_data=payload)

    rendered = _PSRPStreamCursor._stringify_information(record)

    assert rendered == "Transferring"


def test_stringify_information_handles_dict_payload():
    record = InformationRecord(message_data={"Message": "Provisioning complete", "NoNewLine": False})

    rendered = _PSRPStreamCursor._stringify_information(record)

    assert rendered == "Provisioning complete"


def test_winrm_service_create_session_uses_kerberos():
    """Test that WinRM service creates sessions with Kerberos authentication."""
    service = WinRMService()
    
    with patch("app.services.winrm_service.WSMan") as mock_wsman:
        with patch("app.services.winrm_service.settings") as mock_settings:
            # Configure mock settings for Kerberos
            mock_settings.winrm_kerberos_principal = "svc-test@EXAMPLE.COM"
            mock_settings.winrm_port = 5985
            mock_settings.winrm_connection_timeout = 30.0
            mock_settings.winrm_operation_timeout = 15.0
            mock_settings.winrm_read_timeout = 30.0
            
            # Create a mock WSMan instance
            mock_wsman_instance = MagicMock()
            mock_wsman.return_value = mock_wsman_instance
            
            # Call _create_session
            session = service._create_session("test-host.example.com")
            
            # Verify WSMan was called with Kerberos auth
            mock_wsman.assert_called_once()
            call_kwargs = mock_wsman.call_args.kwargs
            
            assert call_kwargs["auth"] == "kerberos"
            assert call_kwargs["username"] is None
            assert call_kwargs["password"] is None
            assert call_kwargs["port"] == 5985
            assert session == mock_wsman_instance


def test_winrm_service_logs_kerberos_principal():
    """Test that WinRM service logs the Kerberos principal."""
    service = WinRMService()
    
    with patch("app.services.winrm_service.WSMan"):
        with patch("app.services.winrm_service.settings") as mock_settings:
            with patch("app.services.winrm_service.logger") as mock_logger:
                # Configure mock settings
                mock_settings.winrm_kerberos_principal = "svc-test@EXAMPLE.COM"
                mock_settings.winrm_port = 5985
                mock_settings.winrm_connection_timeout = 30.0
                mock_settings.winrm_operation_timeout = 15.0
                mock_settings.winrm_read_timeout = 30.0
                
                # Call _create_session
                service._create_session("test-host.example.com")
                
                # Verify logging includes Kerberos principal
                info_calls = [call for call in mock_logger.info.call_args_list]
                assert any("kerberos" in str(call).lower() for call in info_calls)
                assert any("svc-test@EXAMPLE.COM" in str(call) for call in info_calls)
