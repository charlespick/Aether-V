from types import SimpleNamespace

from app.core.config import settings
from app.services.inventory_service import inventory_service


def test_health_endpoint_reports_status(client):
    response = client.get("/healthz")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["version"] == settings.app_version
    assert "timestamp" in payload

    # Security middleware should add standard headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"


def test_readyz_returns_config_error_when_startup_failed(client, monkeypatch):
    mock_result = SimpleNamespace(has_errors=True, has_warnings=False)
    monkeypatch.setattr("app.api.routes.get_config_validation_result", lambda: mock_result)

    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "config_error"


def test_readyz_waits_for_inventory_initialisation(client):
    previous_refresh = inventory_service.last_refresh
    try:
        inventory_service.last_refresh = None
        response = client.get("/readyz")
    finally:
        inventory_service.last_refresh = previous_refresh

    assert response.status_code == 503
    assert response.json()["detail"] == "Inventory not yet initialized"
