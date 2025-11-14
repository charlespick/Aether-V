import pytest
from unittest.mock import patch

# Patch Kerberos configuration before importing services to prevent hanging subprocess calls
kerberos_config_patcher = patch('app.core.config.Settings.has_kerberos_config', return_value=False)
kerberos_config_patcher.start()
kerberos_principal_patcher = patch('app.core.config.Settings.winrm_kerberos_principal', None)
kerberos_principal_patcher.start()
kerberos_keytab_patcher = patch('app.core.config.Settings.winrm_keytab_b64', None)
kerberos_keytab_patcher.start()

from app.services import vm_control_service as vm_module


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_start_vm_executes_command(monkeypatch):
    captured = {}

    async def fake_to_thread(func, hostname, command):
        captured["func"] = func
        captured["hostname"] = hostname
        captured["command"] = command
        return "started", "", 0

    monkeypatch.setattr(vm_module.asyncio, "to_thread", fake_to_thread)

    result = await vm_module.vm_control_service.start_vm("host01", "vm-test")

    assert result.stdout == "started"
    assert result.stderr == ""
    assert captured["func"].__name__ == "execute_ps_command"
    assert captured["hostname"] == "host01"
    assert "Start-VM" in captured["command"]
    assert "vm-test" in captured["command"]


@pytest.mark.anyio("asyncio")
async def test_run_command_raises_vm_control_error_on_failure(monkeypatch):
    async def fake_to_thread(func, hostname, command):
        return "", "Access denied", 1

    monkeypatch.setattr(vm_module.asyncio, "to_thread", fake_to_thread)

    with pytest.raises(vm_module.VMControlError) as exc:
        await vm_module.vm_control_service.stop_vm("host02", "vm02")

    assert exc.value.action == "stop"
    assert exc.value.hostname == "host02"
    assert "Access denied" in exc.value.message


@pytest.mark.anyio("asyncio")
async def test_run_command_wraps_transport_errors(monkeypatch):
    class DummyError(Exception):
        pass

    async def fake_to_thread(func, hostname, command):
        raise DummyError("boom")

    monkeypatch.setattr(vm_module.asyncio, "to_thread", fake_to_thread)

    with pytest.raises(vm_module.VMControlError) as exc:
        await vm_module.vm_control_service.reset_vm("host03", "vm03")

    assert exc.value.action == "reset"
    assert "WinRM communication failed" in exc.value.message


def test_power_shell_single_quote_escapes():
    quoted = vm_module.VMControlService._ps_single_quote("O'Reilly & Co")
    assert quoted == "'O''Reilly & Co'"
