"""Configuration management using Pydantic settings."""
from typing import List, Optional, TYPE_CHECKING

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application settings
    app_name: str = "Aether-V Orchestrator"
    debug: bool = False
    environment_name: str = "Production Environment"

    # Authentication settings
    auth_enabled: bool = True
    # Explicit flag required to enable dev mode (no auth)
    allow_dev_auth: bool = False

    # OIDC Authentication settings (when auth_enabled=True)
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_role_name: str = "vm-admin"
    oidc_redirect_uri: Optional[str] = None
    oidc_force_https: bool = True  # Always use HTTPS for OIDC callbacks

    # API settings - for non-interactive authentication
    api_token: Optional[str] = None  # Optional static token for automation
    session_secret_key: Optional[str] = None  # Session middleware secret key

    # Security settings
    jwks_cache_ttl: int = 300  # JWKS cache TTL in seconds
    max_token_age: int = 3600  # Maximum token age in seconds
    session_max_age: int = 3600  # Session cookie max age in seconds (1 hour)

    # Cookie security settings (when using session-based auth)
    cookie_secure: bool = True  # Require HTTPS for cookies
    cookie_samesite: str = "lax"  # CSRF protection
    # Note: httponly is always True by default in SessionMiddleware for security

    # Hyper-V Host settings
    hyperv_hosts: str = ""  # Comma-separated list of hosts
    winrm_username: Optional[str] = None
    winrm_password: Optional[str] = None
    winrm_transport: str = "ntlm"  # ntlm, basic, or credssp
    winrm_port: int = 5985

    # Inventory settings
    inventory_refresh_interval: int = 60  # seconds

    # Job execution settings
    job_worker_concurrency: int = 3  # Maximum concurrent provisioning jobs

    # WebSocket settings
    # WebSocket connection timeout in seconds (30 minutes)
    websocket_timeout: int = 1800
    websocket_ping_interval: int = 30  # Ping interval in seconds
    # Client refresh time in seconds (25 minutes)
    websocket_refresh_time: int = 1500

    # Development settings
    dummy_data: bool = False  # Enable dummy data for development/testing

    # Host deployment settings
    host_install_directory: str = "C:\\Program Files\\Home Lab Virtual Machine Manager"
    agent_startup_concurrency: int = 4  # Parallel host deployments during startup

    # Agent artifact settings
    agent_artifacts_path: str = "/app/agent"
    agent_http_mount_path: str = "/agent"
    agent_download_base_url: Optional[AnyHttpUrl] = None
    agent_download_max_attempts: int = 5
    agent_download_retry_interval: float = 2.0  # seconds between retries

    def get_agent_download_base_url(self) -> Optional[str]:
        """Return the configured agent download base URL if provided."""

        if not self.agent_download_base_url:
            return None

        return str(self.agent_download_base_url).rstrip("/")

    @property
    def version_file_path(self) -> str:
        """Get path to version file in container."""
        return f"{self.agent_artifacts_path}/version"

    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_hyperv_hosts_list(self) -> List[str]:
        """Parse comma-separated host list."""
        if not self.hyperv_hosts:
            return []
        return [h.strip() for h in self.hyperv_hosts.split(",") if h.strip()]


settings = Settings()


# Module-level storage for the actual session secret being used
# This is set by main.py during application initialization
_actual_session_secret: Optional[str] = None

if TYPE_CHECKING:  # pragma: no cover - only for type hints
    from .config_validation import ConfigValidationResult

# Cache of the configuration validation result so it can be reused across modules
_config_validation_result: Optional["ConfigValidationResult"] = None


def set_session_secret(secret: str) -> None:
    """
    Set the actual session secret being used by the application.
    
    This should be called once during application initialization in main.py
    with either the configured secret or a generated temporary secret.
    
    Args:
        secret: The session secret string
    """
    global _actual_session_secret
    _actual_session_secret = secret


def get_session_secret() -> Optional[str]:
    """
    Get the actual session secret being used by the application.
    
    This allows WebSocket authentication to decrypt session cookies using the same
    secret as the session middleware, whether it's from configuration or generated.
    
    Returns:
        The session secret string, or None if not yet initialized
    """
    return _actual_session_secret


def set_config_validation_result(result: "ConfigValidationResult") -> None:
    """Persist the configuration validation result for reuse."""

    global _config_validation_result
    _config_validation_result = result


def get_config_validation_result() -> Optional["ConfigValidationResult"]:
    """Return the cached configuration validation result, if available."""

    return _config_validation_result
