from datetime import datetime

import pytest

from app.core import config_validation
from app.core.config import Settings


@pytest.fixture(autouse=True)
def restore_config_validation(monkeypatch):
    original_settings = config_validation.settings
    original_setter = config_validation.set_config_validation_result
    original_getter = config_validation.get_config_validation_result

    monkeypatch.setattr(config_validation, "settings", Settings(), raising=False)
    monkeypatch.setattr(
        config_validation,
        "set_config_validation_result",
        lambda result: None,
        raising=False,
    )
    monkeypatch.setattr(
        config_validation,
        "get_config_validation_result",
        lambda: None,
        raising=False,
    )
    yield
    monkeypatch.setattr(config_validation, "settings", original_settings, raising=False)
    monkeypatch.setattr(
        config_validation,
        "set_config_validation_result",
        original_setter,
        raising=False,
    )
    monkeypatch.setattr(
        config_validation,
        "get_config_validation_result",
        original_getter,
        raising=False,
    )


def test_run_config_checks_reports_auth_configuration_issues(monkeypatch):
    # Defaults leave critical auth configuration unset, which should surface errors
    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    warning_messages = {issue.message for issue in result.warnings}

    assert any("OIDC_ISSUER_URL" in message for message in error_messages)
    assert any("OIDC_CLIENT_ID" in message for message in error_messages)
    assert any("OIDC_REDIRECT_URI" in message for message in error_messages)
    assert any("ENVIRONMENT_NAME" in message for message in warning_messages)
    assert any("AGENT_DOWNLOAD_BASE_URL" in message for message in warning_messages)
    assert any("Kerberos credentials" in message for message in warning_messages)


def test_run_config_checks_requires_allow_dev_auth_when_auth_disabled(monkeypatch):
    custom_settings = Settings(auth_enabled=False, allow_dev_auth=False)
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    assert any("ALLOW_DEV_AUTH" in message for message in error_messages)


def test_run_config_checks_returns_cached_result(monkeypatch):
    cached_result = config_validation.ConfigValidationResult(
        checked_at=datetime.utcnow()
    )

    def fake_get_cached():
        return cached_result

    def fail_if_called(_):
        raise AssertionError("set_config_validation_result should not be called when cached")

    monkeypatch.setattr(config_validation, "get_config_validation_result", fake_get_cached, raising=False)
    monkeypatch.setattr(config_validation, "set_config_validation_result", fail_if_called, raising=False)

    result = config_validation.run_config_checks()
    assert result is cached_result
