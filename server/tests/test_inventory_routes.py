import importlib.util

import pytest

_REQUIRED_MODULES = ("fastapi", "pydantic", "yaml")
SERVER_DEPS_AVAILABLE = all(
    importlib.util.find_spec(module) is not None for module in _REQUIRED_MODULES
)

pytestmark = pytest.mark.skipif(
    not SERVER_DEPS_AVAILABLE,
    reason="FastAPI and its dependencies must be installed to run the server integration tests.",
)

if SERVER_DEPS_AVAILABLE:
    from app.services.inventory_service import inventory_service


def test_inventory_summary_matches_counts(client):
    response = client.get("/api/v1/inventory")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total_hosts"] == len(payload["hosts"]) + len(payload["disconnected_hosts"])
    assert payload["total_vms"] == len(payload["vms"])
    assert payload["total_clusters"] == len(payload["clusters"])
    assert payload["disconnected_count"] == len(payload["disconnected_hosts"])
    assert payload["last_refresh"] is not None


def test_list_hosts_returns_known_entries(client):
    response = client.get("/api/v1/hosts")
    assert response.status_code == 200

    hostnames = {host["hostname"] for host in response.json()}
    expected_hosts = {host.hostname for host in inventory_service.get_all_hosts()}
    assert expected_hosts.issubset(hostnames)
