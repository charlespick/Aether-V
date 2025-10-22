"""Configuration validation utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set

from .config import (
    settings,
    set_config_validation_result,
    get_config_validation_result,
)


@dataclass
class ConfigIssue:
    """Represents a single configuration issue."""

    message: str
    hint: Optional[str] = None


@dataclass
class ConfigValidationResult:
    """Outcome of running configuration checks."""

    checked_at: datetime
    errors: List[ConfigIssue] = field(default_factory=list)
    warnings: List[ConfigIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def _warn(result: ConfigValidationResult, message: str, hint: Optional[str] = None) -> None:
    result.warnings.append(ConfigIssue(message=message, hint=hint))


def _error(result: ConfigValidationResult, message: str, hint: Optional[str] = None) -> None:
    result.errors.append(ConfigIssue(message=message, hint=hint))


def _field_was_provided(provided_fields: Set[str], field_name: str) -> bool:
    """Return True if the setting was explicitly provided via environment variables."""

    return field_name in provided_fields


def run_config_checks(force: bool = False) -> ConfigValidationResult:
    """Validate configuration combinations and cache the result."""

    if not force:
        cached = get_config_validation_result()
        if cached is not None:
            return cached

    result = ConfigValidationResult(checked_at=datetime.utcnow())
    provided_fields = settings.model_fields_set

    # ENVIRONMENT_NAME should be explicitly provided and non-empty for clarity.
    if (
        not _field_was_provided(provided_fields, "environment_name")
        or not str(settings.environment_name).strip()
    ):
        _warn(
            result,
            "ENVIRONMENT_NAME is not set.",
            "Set ENVIRONMENT_NAME to the friendly display name for this deployment.",
        )

    # AUTH_ENABLED should be explicitly provided so operators know the mode.
    if not _field_was_provided(provided_fields, "auth_enabled"):
        _warn(
            result,
            "AUTH_ENABLED not provided; defaulting to authentication enabled.",
            "Set AUTH_ENABLED=true or false explicitly to document intent.",
        )

    # Allow dev auth is always a warning when set.
    if settings.allow_dev_auth:
        _warn(
            result,
            "ALLOW_DEV_AUTH is enabled.",
            "Disable ALLOW_DEV_AUTH in production environments.",
        )

    if settings.auth_enabled:
        # Required authentication related settings
        if not settings.oidc_issuer_url:
            _error(
                result,
                "OIDC_ISSUER_URL is required when authentication is enabled.",
                "Set OIDC_ISSUER_URL to your identity provider's issuer URL.",
            )
        if not settings.oidc_client_id:
            _error(
                result,
                "OIDC_CLIENT_ID is required when authentication is enabled.",
                "Set OIDC_CLIENT_ID to the registered application client ID.",
            )
        if not settings.oidc_redirect_uri:
            _error(
                result,
                "OIDC_REDIRECT_URI is required for interactive authentication.",
                "Set OIDC_REDIRECT_URI to the deployed callback URL.",
            )
        # Warn if HTTPS enforcement disabled while auth enabled.
        if not settings.oidc_force_https:
            _warn(
                result,
                "OIDC_FORCE_HTTPS is disabled while authentication is enabled.",
                "Only disable HTTPS enforcement for controlled local development.",
            )
    else:
        # Auth disabled requires explicit allow_dev_auth True.
        if not settings.allow_dev_auth:
            _error(
                result,
                "AUTH_ENABLED is false but ALLOW_DEV_AUTH is not true.",
                "Set ALLOW_DEV_AUTH=true before disabling authentication.",
            )

    # Session secret key recommended for persistence.
    if not settings.session_secret_key:
        _warn(
            result,
            "SESSION_SECRET_KEY is not configured; sessions will reset on restart.",
            "Provide SESSION_SECRET_KEY to persist authenticated sessions across restarts.",
        )

    # Hyper-V hosts - warn when empty.
    if not settings.get_hyperv_hosts_list():
        _warn(
            result,
            "No Hyper-V hosts configured (HYPERV_HOSTS).",
            "Set HYPERV_HOSTS to a comma-separated list so workloads can be managed.",
        )

    # WinRM credentials - warn when missing or partially configured.
    if settings.winrm_username and not settings.winrm_password:
        _warn(
            result,
            "WINRM_USERNAME is set but WINRM_PASSWORD is missing.",
            "Set WINRM_PASSWORD so hosts can be managed.",
        )
    elif settings.winrm_password and not settings.winrm_username:
        _warn(
            result,
            "WINRM_PASSWORD is set but WINRM_USERNAME is missing.",
            "Set WINRM_USERNAME so hosts can be managed.",
        )
    elif not settings.winrm_username and not settings.winrm_password:
        _warn(
            result,
            "WINRM credentials are not configured.",
            "Provide WINRM_USERNAME and WINRM_PASSWORD to manage Hyper-V hosts.",
        )

    set_config_validation_result(result)
    return result
