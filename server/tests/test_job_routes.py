from uuid import uuid4
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
    from app.core.job_schema import get_job_schema
    from app.services.inventory_service import inventory_service


def _build_valid_submission(target_host: str) -> dict:
    schema = get_job_schema()
    return {
        "schema_version": schema["version"],
        "target_host": target_host,
        "values": {
            "vm_name": f"test-vm-{uuid4().hex[:8]}",
            "image_name": "base-image",
            "gb_ram": 4,
            "cpu_cores": 2,
            "guest_la_uid": "admin",
            "guest_la_pw": "P@ssw0rd!",
        },
    }


def test_submit_provisioning_job_returns_job_record(client):
    host = inventory_service.get_connected_hosts()[0]
    payload = _build_valid_submission(host.hostname)

    response = client.post("/api/v1/jobs/provision", json=payload)
    assert response.status_code == 200

    job = response.json()
    assert job["job_type"] == "provision_vm"
    assert job["status"] == "pending"
    assert job["target_host"] == host.hostname


def test_submit_provisioning_job_rejects_schema_mismatch(client):
    host = inventory_service.get_connected_hosts()[0]
    payload = _build_valid_submission(host.hostname)
    payload["schema_version"] = "unexpected"

    response = client.post("/api/v1/jobs/provision", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Schema version mismatch"
