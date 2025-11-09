import asyncio

import pytest

try:  # pragma: no cover - environment guard for optional server package
    from app.core.config import settings
    from app.services.inventory_service import InventoryService
    from app.services.host_deployment_service import host_deployment_service
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    pytestmark = pytest.mark.skip(reason=f"server package unavailable: {exc}")
    settings = None  # type: ignore[assignment]
    InventoryService = None  # type: ignore[assignment]
    host_deployment_service = None  # type: ignore[assignment]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_refresh_inventory_allows_concurrent_mutation(monkeypatch):
    if (
        InventoryService is None
        or settings is None
        or host_deployment_service is None
    ):  # pragma: no cover - environment guard
        pytest.skip("server package unavailable")

    service = InventoryService()

    monkeypatch.setattr(settings, "hyperv_hosts", "slow,fast")
    monkeypatch.setattr(
        host_deployment_service, "_deployment_enabled", False, raising=False
    )

    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    fast_mutation_entered = asyncio.Event()

    async def fake_collect(self, hostname: str):
        payload = {
            "Host": {"ClusterName": "Default"},
            "VirtualMachines": [{"Name": f"{hostname}-vm", "State": "Running"}],
        }

        if hostname == "slow":
            slow_started.set()
            await release_slow.wait()
        return payload

    original_apply_locked = service._apply_host_snapshot_locked

    def instrumented_apply_locked(snapshot, previous_host):
        if snapshot.hostname == "fast":
            fast_mutation_entered.set()
        return original_apply_locked(snapshot, previous_host)

    monkeypatch.setattr(
        service,
        "_collect_with_recovery",
        fake_collect.__get__(service, InventoryService),
    )
    monkeypatch.setattr(service, "_apply_host_snapshot_locked", instrumented_apply_locked)

    slow_task = asyncio.create_task(
        service.refresh_inventory(hostnames=["slow"], rebuild_clusters=False)
    )

    await asyncio.wait_for(slow_started.wait(), timeout=1)

    fast_task = asyncio.create_task(
        service.refresh_inventory(hostnames=["fast"], rebuild_clusters=False)
    )

    await asyncio.wait_for(fast_mutation_entered.wait(), timeout=1)
    assert not slow_task.done()

    release_slow.set()

    slow_result = await asyncio.wait_for(slow_task, timeout=1)
    fast_result = await asyncio.wait_for(fast_task, timeout=1)

    assert slow_result["refreshed_hosts"] == ["slow"]
    assert fast_result["refreshed_hosts"] == ["fast"]
