import types
from datetime import datetime
from typing import List
from unittest import TestCase
from unittest.mock import patch

from server.app.core.config_validation import (
    ConfigIssue,
    ConfigValidationResult,
    run_config_checks,
)


class _StubSettings(types.SimpleNamespace):
    """Minimal stub for the Settings object used during validation tests."""

    def __init__(self, **kwargs):
        defaults = dict(
            environment_name="Aether",
            auth_enabled=True,
            allow_dev_auth=False,
            oidc_issuer_url=None,
            oidc_client_id=None,
            oidc_redirect_uri=None,
            oidc_force_https=True,
            cookie_secure=True,
            cookie_samesite="lax",
            session_secret_key="super-secret",
            agent_download_base_url=None,
            hyperv_hosts="",
            winrm_username=None,
            winrm_password=None,
        )
        defaults.update(kwargs)
        super().__init__(**defaults)
        provided = kwargs.pop("model_fields_set", None)
        if provided is None:
            provided = {key for key, value in defaults.items() if value is not None}
        self.model_fields_set = set(provided)

    # Settings helper methods used by the validator
    def get_agent_download_base_url(self):  # pragma: no cover - trivial wrapper
        return self.agent_download_base_url

    def get_hyperv_hosts_list(self) -> List[str]:  # pragma: no cover - trivial wrapper
        hosts = getattr(self, "hyperv_hosts", "")
        if not hosts:
            return []
        return [item.strip() for item in hosts.split(",") if item.strip()]


class ConfigValidationTests(TestCase):
    def setUp(self) -> None:
        patcher_cache = patch(
            "server.app.core.config_validation.get_config_validation_result",
            return_value=None,
        )
        patcher_set = patch("server.app.core.config_validation.set_config_validation_result")
        self.stub_settings = _StubSettings()
        patcher_settings = patch(
            "server.app.core.config_validation.settings",
            self.stub_settings,
        )

        self.addCleanup(patcher_cache.stop)
        self.addCleanup(patcher_set.stop)
        self.addCleanup(patcher_settings.stop)

        self.mock_get_cached = patcher_cache.start()
        self.mock_set_cached = patcher_set.start()
        patcher_settings.start()

    def test_cached_result_is_returned_without_running_checks(self):
        cached = ConfigValidationResult(
            checked_at=datetime.utcnow(),
            warnings=[ConfigIssue(message="cached warning")],
        )
        self.mock_get_cached.return_value = cached

        result = run_config_checks()

        self.assertIs(result, cached)
        self.mock_set_cached.assert_not_called()

    def test_missing_oidc_configuration_reports_errors(self):
        stub = _StubSettings(
            auth_enabled=True,
            allow_dev_auth=False,
            oidc_issuer_url=None,
            oidc_client_id=None,
            oidc_redirect_uri=None,
            cookie_secure=False,
            session_secret_key=None,
            agent_download_base_url=None,
            hyperv_hosts="",
            winrm_username=None,
            winrm_password=None,
            model_fields_set={"auth_enabled", "environment_name"},
        )
        self.stub_settings.__dict__.update(stub.__dict__)
        self.stub_settings.model_fields_set = stub.model_fields_set
        self.mock_get_cached.return_value = None

        result = run_config_checks(force=True)

        error_messages = {issue.message for issue in result.errors}
        self.assertIn(
            "OIDC_ISSUER_URL is required when authentication is enabled.",
            error_messages,
        )
        self.assertIn(
            "OIDC_CLIENT_ID is required when authentication is enabled.",
            error_messages,
        )
        self.assertIn(
            "OIDC_REDIRECT_URI is required for interactive authentication.",
            error_messages,
        )
        warning_messages = {issue.message for issue in result.warnings}
        self.assertIn(
            "SESSION_SECRET_KEY is not configured; sessions will reset on restart.",
            warning_messages,
        )
        self.assertIn(
            "AGENT_DOWNLOAD_BASE_URL is not configured; host deployments will be disabled.",
            warning_messages,
        )
        self.assertIn(
            "No Hyper-V hosts configured (HYPERV_HOSTS).",
            warning_messages,
        )
        self.assertIn(
            "WINRM credentials are not configured.",
            warning_messages,
        )

    def test_cookie_validation_identifies_invalid_combinations(self):
        stub = _StubSettings(
            cookie_samesite="invalid",
            cookie_secure=False,
            model_fields_set={"cookie_samesite", "cookie_secure", "environment_name"},
        )
        self.stub_settings.__dict__.update(stub.__dict__)
        self.stub_settings.model_fields_set = stub.model_fields_set
        self.mock_get_cached.return_value = None

        result = run_config_checks(force=True)

        warnings = {issue.message for issue in result.warnings}
        self.assertIn(
            "COOKIE_SAMESITE is set to an unsupported value.",
            warnings,
        )

        stub.cookie_samesite = "none"
        self.stub_settings.__dict__.update(stub.__dict__)

        result = run_config_checks(force=True)
        warnings = {issue.message for issue in result.warnings}
        self.assertIn(
            "COOKIE_SAMESITE is 'none' but COOKIE_SECURE is disabled.",
            warnings,
        )
