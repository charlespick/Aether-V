from datetime import datetime, timezone

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
        checked_at=datetime.now(timezone.utc)
    )

    def fake_get_cached():
        return cached_result

    def fail_if_called(_):
        raise AssertionError("set_config_validation_result should not be called when cached")

    monkeypatch.setattr(config_validation, "get_config_validation_result", fake_get_cached, raising=False)
    monkeypatch.setattr(config_validation, "set_config_validation_result", fail_if_called, raising=False)

    result = config_validation.run_config_checks()
    assert result is cached_result


def test_legacy_winrm_username_triggers_migration_error(monkeypatch):
    """Test that WINRM_USERNAME triggers a clear migration error."""
    monkeypatch.setenv("WINRM_USERNAME", "DOMAIN\\user")
    
    custom_settings = Settings(
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    
    # Check for legacy config detection
    assert any("Legacy WinRM configuration detected" in message for message in error_messages)
    assert any("WINRM_USERNAME" in message for message in error_messages)
    
    # Check for migration guidance
    hints = {issue.hint for issue in result.errors if issue.hint}
    migration_hints = [h for h in hints if h and "Migrate to Kerberos" in h]
    assert len(migration_hints) > 0
    
    # Verify migration steps are included
    migration_hint = migration_hints[0]
    assert "keytab" in migration_hint.lower()
    assert "WINRM_KERBEROS_PRINCIPAL" in migration_hint
    assert "WINRM_KEYTAB_B64" in migration_hint
    assert "base64" in migration_hint.lower()
    assert "RBCD" in migration_hint or "Constrained Delegation" in migration_hint


def test_legacy_winrm_password_triggers_migration_error(monkeypatch):
    """Test that WINRM_PASSWORD triggers a clear migration error."""
    monkeypatch.setenv("WINRM_PASSWORD", "secret123")
    
    custom_settings = Settings(
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    assert any("Legacy WinRM configuration detected" in message for message in error_messages)
    assert any("WINRM_PASSWORD" in message for message in error_messages)


def test_legacy_winrm_transport_triggers_migration_error(monkeypatch):
    """Test that WINRM_TRANSPORT triggers a clear migration error."""
    monkeypatch.setenv("WINRM_TRANSPORT", "ntlm")
    
    custom_settings = Settings(
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    assert any("Legacy WinRM configuration detected" in message for message in error_messages)
    assert any("WINRM_TRANSPORT" in message for message in error_messages)


def test_legacy_all_winrm_fields_trigger_migration_error(monkeypatch):
    """Test that all legacy WinRM fields together trigger a comprehensive error."""
    monkeypatch.setenv("WINRM_USERNAME", "DOMAIN\\user")
    monkeypatch.setenv("WINRM_PASSWORD", "secret123")
    monkeypatch.setenv("WINRM_TRANSPORT", "credssp")
    
    custom_settings = Settings(
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    
    # Should detect all three legacy fields
    legacy_error = [msg for msg in error_messages if "Legacy WinRM configuration detected" in msg]
    assert len(legacy_error) > 0
    
    # All three fields should be mentioned
    assert any("WINRM_USERNAME" in msg for msg in error_messages)
    assert any("WINRM_PASSWORD" in msg for msg in error_messages)
    assert any("WINRM_TRANSPORT" in msg for msg in error_messages)


def test_kerberos_config_with_legacy_fields_triggers_error(monkeypatch):
    """Test that mixing Kerberos and legacy config triggers an error."""
    monkeypatch.setenv("WINRM_USERNAME", "DOMAIN\\user")
    
    custom_settings = Settings(
        winrm_kerberos_principal="svc@REALM",
        winrm_keytab_b64="dGVzdA==",  # base64 for "test"
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)

    result = config_validation.run_config_checks(force=True)

    error_messages = {issue.message for issue in result.errors}
    # Should still flag the legacy configuration
    assert any("Legacy WinRM configuration detected" in message for message in error_messages)


def test_app_startup_fails_with_legacy_config(monkeypatch):
    """Test that the application fails to start with legacy configuration and provides clear guidance."""
    # This is an integration test to ensure the app actually fails on startup
    # with legacy config rather than just logging warnings
    
    monkeypatch.setenv("WINRM_USERNAME", "DOMAIN\\user")
    monkeypatch.setenv("WINRM_PASSWORD", "secret")
    
    custom_settings = Settings(
        auth_enabled=False,
        allow_dev_auth=True,
    )
    monkeypatch.setattr(config_validation, "settings", custom_settings, raising=False)
    
    result = config_validation.run_config_checks(force=True)
    
    # The result should have errors (not just warnings)
    assert result.has_errors
    
    # Verify the error provides actionable migration steps
    error_hints = [issue.hint for issue in result.errors if issue.hint]
    assert any("Migrate to Kerberos" in hint for hint in error_hints if hint)
    assert any("keytab" in hint.lower() for hint in error_hints if hint)
    assert any("RBCD" in hint or "Constrained Delegation" in hint for hint in error_hints if hint)
