from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from app.api import routes
from app.core.models import BuildInfo, VMState


class DummyVM:
    def __init__(self, name: str, state):
        self.name = name
        self.state = state


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "value, expected",
    [
        (VMState.RUNNING, VMState.RUNNING),
        ("off", VMState.OFF),
        ("   paused   ", VMState.PAUSED),
        ("unknown-state", VMState.UNKNOWN),
        (None, VMState.UNKNOWN),
    ],
)
def test_normalize_vm_state(value, expected):
    assert routes._normalize_vm_state(value) is expected


def test_current_build_info_returns_model(monkeypatch):
    fake_metadata = SimpleNamespace(
        version="1.2.3",
        source_control="git",
        git_commit="abc",
        git_ref="main",
        git_state="clean",
        build_time=datetime(2024, 1, 2),
        build_host="builder",
    )
    monkeypatch.setattr(routes, "build_metadata", fake_metadata)

    info = routes._current_build_info()
    assert isinstance(info, BuildInfo)
    assert info.version == "1.2.3"
    assert info.build_host == "builder"


@pytest.mark.anyio("asyncio")
async def test_health_check_includes_build_metadata(monkeypatch):
    fake_metadata = SimpleNamespace(
        version="9.9.9",
        source_control="git",
        git_commit=None,
        git_ref=None,
        git_state=None,
        build_time=None,
        build_host=None,
    )
    monkeypatch.setattr(routes, "build_metadata", fake_metadata)

    response = await routes.health_check()

    assert response.status == "healthy"
    assert response.version == "9.9.9"
    assert response.build.version == "9.9.9"


@pytest.mark.anyio("asyncio")
async def test_readiness_check_reflects_config_errors(monkeypatch):
    fake_metadata = SimpleNamespace(
        version="1.0.0",
        source_control="git",
        git_commit=None,
        git_ref=None,
        git_state=None,
        build_time=None,
        build_host=None,
    )
    monkeypatch.setattr(routes, "build_metadata", fake_metadata)

    class DummyResult:
        has_errors = True

    monkeypatch.setattr(routes, "get_config_validation_result", lambda: DummyResult())

    response = await routes.readiness_check()
    assert response.status == "config_error"


@pytest.mark.anyio("asyncio")
async def test_readiness_check_without_errors_reports_ready(monkeypatch):
    fake_metadata = SimpleNamespace(
        version="1.0.1",
        source_control="git",
        git_commit=None,
        git_ref=None,
        git_state=None,
        build_time=None,
        build_host=None,
    )
    monkeypatch.setattr(routes, "build_metadata", fake_metadata)
    monkeypatch.setattr(routes, "get_config_validation_result", lambda: None)

    response = await routes.readiness_check()
    assert response.status == "ready"


@pytest.mark.anyio("asyncio")
async def test_handle_vm_action_success(monkeypatch):
    hostname = "host01"
    vm_name = "vm01"

    async def fake_executor(host, vm):
        fake_executor.calls.append((host, vm))
        return routes.VMActionResult(stdout="ok", stderr="")

    fake_executor.calls = []

    rule = routes.VMActionRule(
        executor=fake_executor,
        allowed_states=(VMState.OFF,),
        label="start",
        success_message="Start command accepted for VM {vm_name}.",
    )
    monkeypatch.setitem(routes.VM_ACTION_RULES, "start", rule)
    monkeypatch.setattr(routes.inventory_service, "get_vm", lambda h, v: DummyVM(vm_name, VMState.OFF))

    async def fake_refresh():
        fake_refresh.invoked = True

    fake_refresh.invoked = False
    monkeypatch.setattr(routes.inventory_service, "refresh_inventory", fake_refresh)

    scheduled = {}

    def fake_create_task(coro):
        scheduled["coro"] = coro
        return None

    monkeypatch.setattr(routes.asyncio, "create_task", fake_create_task)

    result = await routes._handle_vm_action("start", hostname, vm_name)

    assert result["status"] == "accepted"
    assert result["action"] == "start"
    assert result["previous_state"] == VMState.OFF.value
    assert fake_executor.calls == [(hostname, vm_name)]
    assert "message" in result

    await scheduled["coro"]
    assert fake_refresh.invoked is True


@pytest.mark.anyio("asyncio")
async def test_handle_vm_action_vm_not_found(monkeypatch):
    async def noop_executor(*args, **kwargs):
        return routes.VMActionResult(stdout="", stderr="")

    monkeypatch.setitem(
        routes.VM_ACTION_RULES,
        "start",
        routes.VMActionRule(
            executor=noop_executor,
            allowed_states=(VMState.OFF,),
            label="start",
            success_message="",
        ),
    )
    monkeypatch.setattr(routes.inventory_service, "get_vm", lambda h, v: None)

    with pytest.raises(HTTPException) as exc:
        await routes._handle_vm_action("start", "host", "vm")

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio("asyncio")
async def test_handle_vm_action_rejects_disallowed_state(monkeypatch):
    async def noop_executor(*args, **kwargs):
        return routes.VMActionResult(stdout="", stderr="")

    monkeypatch.setitem(
        routes.VM_ACTION_RULES,
        "start",
        routes.VMActionRule(
            executor=noop_executor,
            allowed_states=(VMState.OFF,),
            label="start",
            success_message="",
        ),
    )
    monkeypatch.setattr(routes.inventory_service, "get_vm", lambda h, v: DummyVM("vm", VMState.RUNNING))

    with pytest.raises(HTTPException) as exc:
        await routes._handle_vm_action("start", "host", "vm")

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["vm_state"] == VMState.RUNNING.value


@pytest.mark.anyio("asyncio")
async def test_handle_vm_action_wraps_vm_control_error(monkeypatch):
    async def failing_executor(host, vm):
        raise routes.VMControlError("start", host, vm, "nope")

    monkeypatch.setitem(
        routes.VM_ACTION_RULES,
        "start",
        routes.VMActionRule(
            executor=failing_executor,
            allowed_states=(VMState.OFF,),
            label="start",
            success_message="",
        ),
    )
    monkeypatch.setattr(routes.inventory_service, "get_vm", lambda h, v: DummyVM("vm", VMState.OFF))

    with pytest.raises(HTTPException) as exc:
        await routes._handle_vm_action("start", "host", "vm")

    assert exc.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Failed to start VM" in exc.value.detail["message"]
