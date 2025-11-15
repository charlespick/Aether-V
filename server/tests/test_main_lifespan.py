"""Tests for FastAPI lifespan behaviour in main application."""

import sys
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

sys.modules.setdefault("gssapi", MagicMock())
sys.modules.setdefault("gssapi.raw", MagicMock())

from app import main
from app.core import config as app_config
from app.core import config_validation


def test_kerberos_failure_populates_configuration_errors(monkeypatch):
    """Kerberos initialization errors should surface in configuration results."""

    # Ensure configuration validation does not return cached results
    monkeypatch.setattr(app_config, "_config_validation_result", None, raising=False)
    monkeypatch.setattr(config_validation, "get_config_validation_result", lambda: None)

    captured_result = {}

    def _capture_result(result):
        captured_result["result"] = result

    monkeypatch.setattr(config_validation, "set_config_validation_result", _capture_result)

    # Configure Kerberos credentials so initialization is attempted
    monkeypatch.setattr(main.settings, "winrm_kerberos_principal", "svc/host@example.com")
    monkeypatch.setattr(main.settings, "winrm_keytab_b64", "ZmFrZV9rZXl0YWI=")
    monkeypatch.setattr(main.settings, "winrm_kerberos_realm", "EXAMPLE.COM")
    monkeypatch.setattr(main.settings, "winrm_kerberos_kdc", "kdc.example.com")

    def _raise_kerberos_error(**_):
        raise main.KerberosManagerError("simulated kerberos failure")

    monkeypatch.setattr(main, "initialize_kerberos", _raise_kerberos_error)

    async def _fail_remote_start():  # pragma: no cover - executed only on regression
        raise AssertionError("remote task service should not start when Kerberos initialization fails")

    monkeypatch.setattr(main.remote_task_service, "start", _fail_remote_start)

    async def _fail_host_deployment(*_):  # pragma: no cover - executed only on regression
        raise AssertionError("host deployment should not start when Kerberos initialization fails")

    monkeypatch.setattr(main.host_deployment_service, "start_startup_deployment", _fail_host_deployment)

    def _fail_cleanup():  # pragma: no cover - executed only on regression
        raise AssertionError("cleanup should not run when Kerberos initialization fails")

    monkeypatch.setattr(main, "cleanup_kerberos", _fail_cleanup)

    with TestClient(main.app):
        pass

    result = captured_result.get("result")
    assert result is not None, "Configuration validation result was not captured"

    messages = [issue.message for issue in getattr(result, "errors", [])]
    assert any("Kerberos initialization failed" in message for message in messages), (
        "Kerberos initialization failure should be surfaced as a configuration error"
    )
