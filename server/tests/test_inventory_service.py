import asyncio

from datetime import datetime
from unittest.mock import patch

import pytest

# Patch Kerberos configuration before importing services to prevent hanging subprocess calls
kerberos_config_patcher = patch('app.core.config.Settings.has_kerberos_config', return_value=False)
kerberos_config_patcher.start()
kerberos_principal_patcher = patch('app.core.config.Settings.winrm_kerberos_principal', None)
kerberos_principal_patcher.start()
kerberos_keytab_patcher = patch('app.core.config.Settings.winrm_keytab_b64', None)
kerberos_keytab_patcher.start()

try:  # pragma: no cover - environment guard for optional server package
    from app.core.config import settings
    from app.core.models import Notification, NotificationCategory, NotificationLevel
    from app.services.inventory_service import InventoryService
    from app.services.host_deployment_service import host_deployment_service
    from app.services.notification_service import notification_service
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    pytestmark = pytest.mark.skip(reason=f"server package unavailable: {exc}")
    settings = None  # type: ignore[assignment]
    Notification = None  # type: ignore[assignment]
    NotificationCategory = None  # type: ignore[assignment]
    NotificationLevel = None  # type: ignore[assignment]
    InventoryService = None  # type: ignore[assignment]
    host_deployment_service = None  # type: ignore[assignment]
    notification_service = None  # type: ignore[assignment]


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


@pytest.mark.anyio("asyncio")
async def test_refresh_inventory_discards_stale_snapshots(monkeypatch):
    if (
        InventoryService is None
        or settings is None
        or host_deployment_service is None
    ):  # pragma: no cover - environment guard
        pytest.skip("server package unavailable")

    service = InventoryService()

    monkeypatch.setattr(settings, "hyperv_hosts", "dup")
    monkeypatch.setattr(
        host_deployment_service, "_deployment_enabled", False, raising=False
    )

    first_collection_started = asyncio.Event()
    allow_first_collection = asyncio.Event()
    second_collection_done = asyncio.Event()

    async def fake_collect(self, hostname: str):
        payload = {
            "Host": {"ClusterName": "Default"},
            "VirtualMachines": [
                {"Name": f"{hostname}-vm", "State": "Running"},
            ],
        }

        if not first_collection_started.is_set():
            first_collection_started.set()
            await allow_first_collection.wait()
            payload["Host"]["ClusterName"] = "OldCluster"
            payload["VirtualMachines"][0]["Name"] = f"{hostname}-old"
        else:
            payload["Host"]["ClusterName"] = "NewCluster"
            payload["VirtualMachines"][0]["Name"] = f"{hostname}-new"
            second_collection_done.set()
        return payload

    monkeypatch.setattr(
        service,
        "_collect_with_recovery",
        fake_collect.__get__(service, InventoryService),
    )

    first_refresh = asyncio.create_task(
        service.refresh_inventory(hostnames=["dup"], rebuild_clusters=False)
    )

    await asyncio.wait_for(first_collection_started.wait(), timeout=1)

    second_refresh = asyncio.create_task(
        service.refresh_inventory(hostnames=["dup"], rebuild_clusters=False)
    )

    await asyncio.wait_for(second_collection_done.wait(), timeout=1)

    second_result = await asyncio.wait_for(second_refresh, timeout=1)
    assert second_result["refreshed_hosts"] == ["dup"]

    allow_first_collection.set()
    first_result = await asyncio.wait_for(first_refresh, timeout=1)
    assert first_result["refreshed_hosts"] == ["dup"]

    host = service.hosts["dup"]
    assert host.cluster == "NewCluster"
    vm_key = "dup:dup-new"
    assert vm_key in service.vms
    assert "dup:dup-old" not in service.vms


@pytest.mark.anyio("asyncio")
async def test_refresh_inventory_prunes_unconfigured_hosts(monkeypatch):
    if (
        InventoryService is None
        or settings is None
        or host_deployment_service is None
        or notification_service is None
        or Notification is None
        or NotificationLevel is None
        or NotificationCategory is None
    ):  # pragma: no cover - environment guard
        pytest.skip("server package unavailable")

    service = InventoryService()

    monkeypatch.setattr(settings, "hyperv_hosts", "keep,drop")
    monkeypatch.setattr(
        host_deployment_service, "_deployment_enabled", False, raising=False
    )

    async def fake_collect(self, hostname: str):
        return {
            "Host": {"ClusterName": "Default"},
            "VirtualMachines": [
                {"Name": f"{hostname}-vm", "State": "Running"},
            ],
        }

    monkeypatch.setattr(
        service,
        "_collect_with_recovery",
        fake_collect.__get__(service, InventoryService),
    )

    monkeypatch.setattr(notification_service, "_initialized", True, raising=False)
    monkeypatch.setattr(notification_service, "notifications", {}, raising=False)
    monkeypatch.setattr(notification_service, "_system_notification_ids", {}, raising=False)

    await service.refresh_inventory(rebuild_clusters=False)

    assert set(service.hosts) == {"keep", "drop"}
    drop_vm_key = "drop:drop-vm"
    assert drop_vm_key in service.vms

    service._host_last_refresh.setdefault("drop", datetime.utcnow())
    service._host_last_applied_sequence["drop"] = 42

    service._job_vm_placeholders["job-1"] = {drop_vm_key}
    service._job_vm_originals["job-1"] = {drop_vm_key: None}
    service._preparing_hosts.add("drop")
    service._slow_hosts.add("drop")

    now = datetime.utcnow()
    preparing_key = service._preparing_notification_key("drop")
    preparing_id = "prep-id"
    notification_service.notifications[preparing_id] = Notification(
        id=preparing_id,
        title="Preparing",
        message="",
        level=NotificationLevel.INFO,
        category=NotificationCategory.SYSTEM,
        created_at=now,
        related_entity=f"system:{preparing_key}",
    )
    notification_service._system_notification_ids[preparing_key] = preparing_id

    slow_key = service._slow_host_notification_key("drop")
    slow_id = "slow-id"
    notification_service.notifications[slow_id] = Notification(
        id=slow_id,
        title="Slow host",
        message="",
        level=NotificationLevel.WARNING,
        category=NotificationCategory.SYSTEM,
        created_at=now,
        related_entity=f"system:{slow_key}",
    )
    notification_service._system_notification_ids[slow_key] = slow_id

    monkeypatch.setattr(settings, "hyperv_hosts", "keep")

    await service.refresh_inventory(rebuild_clusters=False)

    assert set(service.hosts) == {"keep"}
    assert all(not key.startswith("drop:") for key in service.vms)
    assert "drop" not in service._host_last_refresh
    assert "drop" not in service._host_last_applied_sequence
    assert service._job_vm_placeholders == {}
    assert service._job_vm_originals == {}
    assert "drop" not in service._preparing_hosts
    assert "drop" not in service._slow_hosts
    assert preparing_key not in notification_service._system_notification_ids
    assert slow_key not in notification_service._system_notification_ids
    assert preparing_id not in notification_service.notifications
    assert slow_id not in notification_service.notifications
