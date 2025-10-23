import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

_REQUIRED_MODULES = ("fastapi", "pydantic", "yaml")
SERVER_DEPS_AVAILABLE = all(
    importlib.util.find_spec(module) is not None for module in _REQUIRED_MODULES
)

if SERVER_DEPS_AVAILABLE:  # pragma: no branch - simple availability guard
    from fastapi.testclient import TestClient

# Configure environment defaults before the application imports settings
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("ALLOW_DEV_AUTH", "true")
os.environ.setdefault("DUMMY_DATA", "true")
os.environ.setdefault("SESSION_SECRET_KEY", "integration-test-secret")

if SERVER_DEPS_AVAILABLE:
    # Ensure the job schema loader points to the repository's schema directory
    default_schema = Path(__file__).resolve().parents[2] / "Schemas" / "job-inputs.yaml"
    from app.core import job_schema  # noqa: E402  # pylint: disable=wrong-import-position

    job_schema.DEFAULT_SCHEMA_PATH = default_schema
    job_schema._SCHEMA_CACHE = None  # type: ignore[attr-defined]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    if not SERVER_DEPS_AVAILABLE:
        pytest.skip(
            "FastAPI and its dependencies must be installed to run the server integration tests."
        )

    """Provide a FastAPI test client with external services patched."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.services.host_deployment_service import host_deployment_service
    from app.services.winrm_service import winrm_service

    monkeypatch.setattr(host_deployment_service, "ensure_host_setup", AsyncMock(return_value=True))
    monkeypatch.setattr(winrm_service, "execute_ps_command", Mock(return_value=("", "", 0)))
    monkeypatch.setattr(winrm_service, "execute_ps_script", Mock(return_value=("", "", 0)))

    app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user"}

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
