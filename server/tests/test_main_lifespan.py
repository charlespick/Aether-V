"""Tests for FastAPI lifespan behaviour in main application."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

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

    config_result = config_validation.ConfigValidationResult(checked_at=datetime.now(timezone.utc))
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
    assert readiness.status_code == 200
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

    clean_result = config_validation.ConfigValidationResult(checked_at=datetime.now(timezone.utc))
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
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "config_error"

    api_response = client.get("/api/v1/about")
    assert api_response.status_code == 503
    assert "configuration is invalid" in api_response.json()["detail"].lower()


def test_host_deployment_service_stops_during_shutdown(monkeypatch):
    """The lifespan shutdown should cancel startup deployments."""

    monkeypatch.setattr(app_config, "_config_validation_result", None, raising=False)

    clean_result = config_validation.ConfigValidationResult(checked_at=datetime.now(timezone.utc))
    monkeypatch.setattr(main, "run_config_checks", lambda: clean_result)

    # Avoid real external calls during the test
    monkeypatch.setattr(main.settings, "auth_enabled", False, raising=False)
    monkeypatch.setattr(main.settings, "allow_dev_auth", True, raising=False)
    monkeypatch.setattr(main, "initialize_kerberos", lambda **_: None)
    monkeypatch.setattr(main, "cleanup_kerberos", lambda: None)

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main.remote_task_service, "start", _noop)
    monkeypatch.setattr(main.remote_task_service, "stop", _noop)
    monkeypatch.setattr(main.notification_service, "start", _noop)
    monkeypatch.setattr(main.notification_service, "stop", _noop)
    monkeypatch.setattr(main.inventory_service, "start", _noop)
    monkeypatch.setattr(main.inventory_service, "stop", _noop)
    monkeypatch.setattr(main.job_service, "start", _noop)
    monkeypatch.setattr(main.job_service, "stop", _noop)
    monkeypatch.setattr(main.host_deployment_service, "start_startup_deployment", _noop)

    stop_called = {}

    async def _record_stop():
        stop_called["called"] = True

    monkeypatch.setattr(main.host_deployment_service, "stop", _record_stop)

    with TestClient(main.app):
        pass

    assert stop_called.get("called") is True
