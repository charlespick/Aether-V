"""Configuration management using Pydantic settings."""

from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings


# Agent artifact locations are baked into the container at build time and do not
# need to be customised at runtime. They are provided here as module constants so
# other modules can reference the paths without duplicating literals.
AGENT_ARTIFACTS_DIR = Path("/app/agent")
AGENT_HTTP_MOUNT_PATH = "/agent"
AGENT_VERSION_PATH = AGENT_ARTIFACTS_DIR / "version"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application settings
    app_name: str = "Aether-V Server"
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
    oidc_api_audience: Optional[str] = None
    oidc_reader_permissions: str = "Aether.Reader"
    oidc_writer_permissions: str = "Aether.Writer"
    oidc_admin_permissions: str = "Aether.Admin"
    oidc_role_name: Optional[str] = None  # Legacy fallback
    oidc_redirect_uri: Optional[str] = None
    oidc_force_https: bool = True  # Always use HTTPS for OIDC callbacks
    oidc_end_session_endpoint: Optional[str] = None  # Optional override for OIDC single logout
    oidc_post_logout_redirect_uri: Optional[str] = None  # Where IdPs should return users after logout

    # Session management settings
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
    
    # WinRM Kerberos authentication settings
    winrm_kerberos_principal: Optional[str] = None  # Service principal (e.g., user@REALM)
    winrm_keytab_b64: Optional[str] = None  # Base64-encoded keytab file
    winrm_kerberos_realm: Optional[str] = None  # Optional Kerberos realm override
    winrm_kerberos_kdc: Optional[str] = None  # Optional KDC server override
    
    # WinRM connection settings
    winrm_port: int = 5985
    winrm_operation_timeout: float = 15.0  # seconds to wait for WinRM calls
    winrm_connection_timeout: float = 30.0  # network connect timeout in seconds
    winrm_read_timeout: float = 30.0  # HTTP read timeout in seconds
    winrm_poll_interval_seconds: float = 1.0  # how long to wait between poll cycles

    # Inventory settings
    inventory_refresh_interval: int = 60  # seconds

    # Job execution settings
    job_worker_concurrency: int = 6  # Maximum concurrent provisioning jobs
    job_long_timeout_seconds: float = 900.0  # 15 minutes for provisioning/deletion
    job_short_timeout_seconds: float = 60.0  # 1 minute for quick power actions

    # Remote task execution settings
    remote_task_min_concurrency: int = 6
    remote_task_max_concurrency: int = 24
    remote_task_scale_up_backlog: int = 2
    remote_task_idle_seconds: float = 30.0
    remote_task_scale_up_duration_threshold: float = 30.0
    remote_task_job_concurrency: int = 6
    remote_task_dynamic_ceiling: int = 48
    remote_task_resource_scale_interval_seconds: float = 15.0
    remote_task_resource_observation_window_seconds: float = 45.0
    remote_task_resource_cpu_threshold: float = 60.0
    remote_task_resource_memory_threshold: float = 70.0
    remote_task_resource_scale_increment: int = 2

    # WebSocket settings
    # WebSocket connection timeout in seconds (30 minutes)
    websocket_timeout: int = 1800
    websocket_ping_interval: int = 30  # Ping interval in seconds
    # Client refresh time in seconds (25 minutes)
    websocket_refresh_time: int = 1500

    # Development settings
    dummy_data: bool = False  # Enable dummy data for development/testing

    # Host deployment settings
    host_install_directory: str = "C:\\Program Files\\Aether-V"
    host_deployment_timeout: float = 60.0  # Seconds allowed for host deployment WinRM calls
    agent_startup_concurrency: int = 3  # Parallel host deployments during startup
    agent_startup_ingress_timeout: float = 120.0  # Seconds to wait for ingress readiness
    agent_startup_ingress_poll_interval: float = 3.0  # Seconds between readiness probes

    # Agent artifact download settings
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
        return str(AGENT_VERSION_PATH)

    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_hyperv_hosts_list(self) -> List[str]:
        """Parse comma-separated host list."""
        if not self.hyperv_hosts:
            return []
        return [h.strip() for h in self.hyperv_hosts.split(",") if h.strip()]

    def get_keytab_bytes(self) -> Optional[bytes]:
        """Decode base64-encoded keytab data if configured."""
        if not self.winrm_keytab_b64:
            return None
        
        import base64
        try:
            return base64.b64decode(self.winrm_keytab_b64)
        except Exception:
            return None

    def has_kerberos_config(self) -> bool:
        """Check if Kerberos authentication is configured."""
        return bool(self.winrm_kerberos_principal and self.winrm_keytab_b64)


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
