"""Unit tests for helpers in the WinRM service."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Kerberos is disabled via environment variables in conftest.py

from pypsrp.exceptions import PSInvocationState
from pypsrp.powershell import InformationRecord
from pypsrp.serializer import GenericComplexObject

from app.services.winrm_service import (
    _PSRPStreamCursor,
    WinRMService,
    _format_output_preview,
)



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


def test_stream_cursor_drain_handles_multiple_streams():
    """Drain should emit stdout/information/error records and capture exit codes."""

    emitted: list[tuple[str, str]] = []

    def on_chunk(stream: str, payload: str) -> None:
        emitted.append((stream, payload))

    cursor = _PSRPStreamCursor(hostname="hv1", on_chunk=on_chunk)

    sentinel = f"{cursor._EXIT_SENTINEL} 7"
    ps = SimpleNamespace(
        output=["hello", sentinel],
        streams=SimpleNamespace(
            information=[InformationRecord(message_data="info message")],
            error=["problem", f"{cursor._EXIT_SENTINEL} 9"],
        ),
    )

    cursor.drain(ps)

    assert emitted == [
        ("stdout", "hello\n"),
        ("stdout", "info message\n"),
        ("stderr", "problem\n"),
    ]
    assert cursor.exit_code == 9
    assert cursor.stdout_chunks == 2
    assert cursor.stderr_chunks == 1
    assert cursor.stdout_bytes >= len("hello\n")
    assert cursor.stderr_bytes >= len("problem\n")


def test_format_output_preview_truncates_long_strings():
    """Long previews should be truncated with ellipsis."""

    preview = _format_output_preview("start\n" + "x" * 500)

    assert preview.startswith("\nstart")
    assert preview.endswith("...")


def test_session_context_manager_closes_resources():
    """The session context manager should always close pools and sessions."""

    service = WinRMService()
    wsman = MagicMock()
    pool = MagicMock()

    service._create_session = MagicMock(return_value=wsman)
    service._open_runspace_pool = MagicMock(return_value=pool)
    service._dispose_session = MagicMock()

    with service._session("hv1") as acquired:
        assert acquired is pool

    pool.close.assert_called_once()
    service._dispose_session.assert_called_once_with(wsman)


def test_execute_collects_and_returns_output(monkeypatch):
    """_execute should aggregate stdout/stderr chunks into strings."""

    service = WinRMService()

    class DummyCursor:
        def __init__(self, hostname: str, on_chunk):
            self.hostname = hostname
            self.on_chunk = on_chunk
            self.stdout_chunks = 0
            self.stderr_chunks = 0
            self.stdout_bytes = 0
            self.stderr_bytes = 0
            self.exit_code = None

    cursors: list[DummyCursor] = []

    def fake_cursor(hostname: str, on_chunk):
        cursor = DummyCursor(hostname, on_chunk)
        cursors.append(cursor)
        return cursor

    def fake_invoke(self, pool, hostname, script, cursor):
        cursor.on_chunk("stdout", "result line\n")
        cursor.on_chunk("stderr", "error line\n")
        cursor.stdout_chunks = 1
        cursor.stderr_chunks = 1
        cursor.stdout_bytes = len("result line\n".encode("utf-8"))
        cursor.stderr_bytes = len("error line\n".encode("utf-8"))
        cursor.exit_code = 2
        return 2, 1.25

    @contextmanager
    def fake_session(self, hostname: str):
        yield "pool"

    monkeypatch.setattr("app.services.winrm_service._PSRPStreamCursor", fake_cursor)
    monkeypatch.setattr(WinRMService, "_session", fake_session, raising=False)
    monkeypatch.setattr(WinRMService, "_invoke", fake_invoke, raising=False)

    stdout, stderr, exit_code = service._execute("hv1", "Write-Host 'hi'")

    assert stdout == "result line\n"
    assert stderr == "error line\n"
    assert exit_code == 2
    assert cursors and cursors[0].hostname == "hv1"


def test_invoke_polls_until_completion(monkeypatch):
    """_invoke should poll until the PowerShell state reports completion."""

    service = WinRMService()

    class DummyStreams:
        information: list = []
        error: list = []

    class DummyPS:
        def __init__(self):
            self.output = []
            self.streams = DummyStreams()
            self.state = PSInvocationState.RUNNING
            self.had_errors = False
            self._poll_count = 0

        def add_script(self, script):
            self.script = script

        def begin_invoke(self):
            self.began = True

        def poll_invoke(self, timeout):
            self._poll_count += 1
            if self._poll_count >= 2:
                self.state = PSInvocationState.COMPLETED

        def end_invoke(self):
            self.ended = True

        def close(self):
            self.closed = True

    dummy_ps = DummyPS()
    cursor = SimpleNamespace(exit_code=None, drain=MagicMock())

    times = [0.0, 1.0, 6.5, 7.0]

    def fake_perf_counter():
        if times:
            return times.pop(0)
        return 7.0

    monkeypatch.setattr("app.services.winrm_service.PowerShell", lambda pool: dummy_ps)
    monkeypatch.setattr("app.services.winrm_service.perf_counter", fake_perf_counter)
    monkeypatch.setattr("app.services.winrm_service.settings", SimpleNamespace(
        winrm_operation_timeout=30.0,
        winrm_poll_interval_seconds=1.0,
    ))

    exit_code, duration = service._invoke(pool="pool", hostname="hv1", script="Write-Host 'hi'", cursor=cursor)

    assert exit_code == 0
    assert pytest.approx(duration, rel=1e-6) == 7.0
    assert dummy_ps.ended
    assert dummy_ps.closed
    assert cursor.drain.call_count >= 2


def test_normalize_state_and_state_complete_helpers():
    """Helper methods should normalise enum and string states consistently."""

    class DummyState(PSInvocationState):
        def __init__(self, name: str):
            self.name = name

    assert WinRMService._normalize_state(DummyState("COMPLETED")) == "completed"
    assert WinRMService._normalize_state(None) == "unknown"
    assert WinRMService._normalize_state("FAILED") == "failed"

    assert WinRMService._state_complete(PSInvocationState.COMPLETED)
    assert WinRMService._state_complete("failed")
    assert not WinRMService._state_complete("running")


def test_wrap_command_includes_environment_variables():
    """_wrap_command should inject environment assignments and sentinel output."""

    service = WinRMService()
    script = service._wrap_command("Write-Host 'hi'", {"Path": "C:\\Temp", "Debug": "true"})

    assert "$env:Path = 'C:\\Temp'" in script
    assert "$env:Debug = 'true'" in script
    assert WinRMService._EXIT_SENTINEL in script


def test_build_script_invocation_handles_various_types():
    """_build_script_invocation should handle bools, numbers and strings."""

    service = WinRMService()
    invocation = service._build_script_invocation(
        "C:/Scripts/do.ps1",
        {"Enabled": True, "Retries": 3, "Label": "vm"},
    )

    assert "-Enabled" in invocation
    assert "-Retries 3" in invocation
    assert "-Label 'vm'" in invocation


def test_join_chunks_and_ps_quote_helpers():
    """Utility helpers should normalise chunk collections and quoting."""

    service = WinRMService()
    assert service._join_chunks(["a", "", "b"]) == "ab"
    assert service._ps_quote("it's done") == "'it''s done'"


def test_extract_information_message_handles_bytes():
    """Byte payloads should be decoded into clean strings."""

    payload = b"status update\r\n"
    result = _PSRPStreamCursor._extract_information_message(payload)

    assert result == "status update"
