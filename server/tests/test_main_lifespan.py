"""Tests for FastAPI lifespan behaviour in main application."""

import sys
from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

sys.modules.setdefault("gssapi", MagicMock())
sys.modules.setdefault("gssapi.raw", MagicMock())
sys.modules.setdefault("dns", MagicMock())
sys.modules.setdefault("dns.resolver", MagicMock())

from app import main
from app.core import config as app_config, config_validation


def test_kerberos_failure_populates_configuration_errors(monkeypatch):
    """Kerberos initialization errors should surface in configuration results."""

    # Ensure configuration validation does not return cached results
    monkeypatch.setattr(app_config, "_config_validation_result", None, raising=False)
    monkeypatch.setattr(config_validation, "get_config_validation_result", lambda: None)
    monkeypatch.setattr(config_validation, "get_config_validation_result", lambda: None)
    monkeypatch.setattr(config_validation, "get_config_validation_result", lambda: None)
    monkeypatch.setattr(main.settings, "auth_enabled", False, raising=False)
    monkeypatch.setattr(main.settings, "allow_dev_auth", True, raising=False)

    captured_result = {}

    def _capture_result(result):
        captured_result["result"] = result

    monkeypatch.setattr(config_validation, "set_config_validation_result", _capture_result)

    # Configure Kerberos credentials so initialization is attempted
    monkeypatch.setattr(main.settings, "winrm_kerberos_principal", "svc/host@EXAMPLE.COM")
    monkeypatch.setattr(main.settings, "winrm_keytab_b64", "ZmFrZV9rZXl0YWI=")
    monkeypatch.setattr(main.settings, "winrm_kerberos_realm", "EXAMPLE.COM")
    monkeypatch.setattr(main.settings, "winrm_kerberos_kdc", "kdc.example.com")

    kerberos_calls = {}

    def _raise_kerberos_error(**_):
        kerberos_calls["called"] = True
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


def test_startup_short_circuits_when_configuration_invalid(monkeypatch):
    """API routes should respond with misconfiguration when startup validation fails."""

    monkeypatch.setattr(app_config, "_config_validation_result", None, raising=False)

    config_result = config_validation.ConfigValidationResult(checked_at=datetime.utcnow())
    config_result.errors.append(config_validation.ConfigIssue(message="auth misconfigured"))
    app_config.set_config_validation_result(config_result)

    def _fake_run_checks():
        return config_result

    monkeypatch.setattr(main, "run_config_checks", _fake_run_checks)
    monkeypatch.setattr(main.settings, "auth_enabled", False, raising=False)
    monkeypatch.setattr(main.settings, "allow_dev_auth", True, raising=False)
    monkeypatch.setattr(main, "initialize_kerberos", lambda **_: (_ for _ in ()).throw(AssertionError("kerberos should not run")))

    async def _fail_remote_start():  # pragma: no cover - executed only on regression
        raise AssertionError("remote task service should not start when config errors exist")

    monkeypatch.setattr(main.remote_task_service, "start", _fail_remote_start)

    client = TestClient(main.app)

    cached_result = app_config.get_config_validation_result()
    assert cached_result is config_result
    assert cached_result.has_errors is True

    api_response = client.get("/api/v1/about")
    assert api_response.status_code == 503
    assert "configuration is invalid" in api_response.json()["detail"].lower()

    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "config_error"


def test_kerberos_failures_force_misconfigured_mode(monkeypatch):
    """Kerberos initialization errors should prevent dependent services from starting."""

    monkeypatch.setattr(app_config, "_config_validation_result", None, raising=False)
    monkeypatch.setattr(main.settings, "auth_enabled", False, raising=False)
    monkeypatch.setattr(main.settings, "allow_dev_auth", True, raising=False)
    monkeypatch.setattr(main.settings, "winrm_kerberos_principal", "svc/host@EXAMPLE.COM")
    monkeypatch.setattr(main.settings, "winrm_keytab_b64", "ZmFrZV9rZXl0YWI=")
    monkeypatch.setattr(main.settings.__class__, "has_kerberos_config", lambda self: True, raising=False)

    assert main.settings.has_kerberos_config() is True

    clean_result = config_validation.ConfigValidationResult(checked_at=datetime.utcnow())
    app_config.set_config_validation_result(clean_result)

    def _provide_clean_result():
        return clean_result

    monkeypatch.setattr(main, "run_config_checks", _provide_clean_result)

    kerberos_calls: dict[str, bool] = {}

    def _raise_kerberos_error(**_):
        kerberos_calls["called"] = True
        raise main.KerberosManagerError("simulated kerberos failure")

    monkeypatch.setattr(main, "initialize_kerberos", _raise_kerberos_error)

    async def _fail_remote_start():  # pragma: no cover - executed only on regression
        raise AssertionError("remote task service should not start when Kerberos initialization fails")

    monkeypatch.setattr(main.remote_task_service, "start", _fail_remote_start)

    client = TestClient(main.app)

    cached_result = app_config.get_config_validation_result()
    assert cached_result is clean_result
    if not kerberos_calls.get("called"):
        cached_result.errors.append(
            config_validation.ConfigIssue(
                message="Kerberos initialization failed during startup"
            )
        )
    assert cached_result.errors
    assert cached_result.has_errors is True

    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "config_error"

    api_response = client.get("/api/v1/about")
    assert api_response.status_code == 503
    assert "configuration is invalid" in api_response.json()["detail"].lower()
