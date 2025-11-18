from datetime import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.testclient import TestClient

# Kerberos is disabled via environment variables in conftest.py

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

    api_response = Response()

    response = await routes.readiness_check(api_response)
    assert api_response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
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

    api_response = Response()

    response = await routes.readiness_check(api_response)
    assert api_response.status_code == status.HTTP_200_OK
    assert response.status == "ready"


def test_vm_lookup_by_id_route_uses_global_search(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)

    dummy_vm = routes.VM(
        id="abc",
        name="vm-one",
        host="host01",
        state=routes.VMState.RUNNING,
    )

    by_id_calls: list[str] = []

    def fake_get_vm_by_id(vm_id: str):
        by_id_calls.append(vm_id)
        return dummy_vm

    def fail_get_vm(hostname: str, vm_name: str):  # pragma: no cover - regression guard
        raise AssertionError("Host-scoped VM lookup should not be used for by-id route")

    monkeypatch.setattr(routes.inventory_service, "get_vm_by_id", fake_get_vm_by_id)
    monkeypatch.setattr(routes.inventory_service, "get_vm", fail_get_vm)
    monkeypatch.setattr(routes.settings, "auth_enabled", False, raising=False)
    monkeypatch.setattr(routes.settings, "allow_dev_auth", True, raising=False)

    client = TestClient(app)
    response = client.get("/api/v1/vms/by-id/abc")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["id"] == "abc"
    assert by_id_calls == ["abc"]


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


@pytest.mark.anyio("asyncio")
async def test_logout_returns_idp_redirect(monkeypatch):
    monkeypatch.setattr(routes.settings, "oidc_force_https", False)
    monkeypatch.setattr(routes.settings, "oidc_post_logout_redirect_uri", None)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/logout",
        "headers": [(b"host", b"example.com")],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("example.com", 80),
        "query_string": b"",
        "app": SimpleNamespace(),
        "session": {
            "oidc_logout": {
                "id_token": routes._encode_logout_token("test-token"),
                "end_session_endpoint": "https://idp/logout",
                "session_state": "state-token",
            }
        },
    }

    request = Request(scope)
    response = await routes.logout(request)

    assert isinstance(response, routes.JSONResponse)

    payload = json.loads(response.body.decode())
    assert payload["redirect_url"] == "http://example.com/"
    assert "id_token_hint=test-token" in payload["idp_logout_url"]
    assert "post_logout_redirect_uri=http%3A%2F%2Fexample.com%2F" in payload["idp_logout_url"]
    assert request.session == {}


@pytest.mark.anyio("asyncio")
async def test_logout_get_prefers_idp_redirect(monkeypatch):
    monkeypatch.setattr(routes.settings, "oidc_force_https", True)
    monkeypatch.setattr(routes.settings, "oidc_post_logout_redirect_uri", "/after")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/logout",
        "headers": [(b"host", b"app.example" + b":8443")],
        "client": ("127.0.0.1", 4321),
        "scheme": "http",
        "server": ("app.example", 8443),
        "query_string": b"",
        "app": SimpleNamespace(),
        "session": {
            "oidc_logout": {
                "end_session_endpoint": "https://issuer/logout",
            }
        },
    }

    request = Request(scope)
    response = await routes.logout(request)

    assert isinstance(response, routes.RedirectResponse)
    location = response.headers["location"]
    assert location.startswith("https://issuer/logout")
    assert "post_logout_redirect_uri=https%3A%2F%2Fapp.example%3A8443%2Fafter" in location


@pytest.mark.anyio("asyncio")
async def test_logout_get_handles_post_logout_callback(monkeypatch):
    monkeypatch.setattr(routes.settings, "oidc_force_https", False)
    monkeypatch.setattr(routes.settings, "oidc_post_logout_redirect_uri", None)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/logout",
        "headers": [(b"host", b"example.com")],
        "client": ("127.0.0.1", 9999),
        "scheme": "http",
        "server": ("example.com", 80),
        "query_string": b"",
        "app": SimpleNamespace(),
        "session": {},
    }

    request = Request(scope)
    response = await routes.logout(request)

    assert isinstance(response, routes.RedirectResponse)
    assert response.headers["location"] == "http://example.com/"
