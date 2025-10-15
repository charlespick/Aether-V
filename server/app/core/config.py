"""Configuration management using Pydantic settings."""
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application settings
    app_name: str = "Aether-V Orchestrator"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # OIDC Authentication settings
    oidc_enabled: bool = True
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_role_name: str = "vm-admin"
    oidc_redirect_uri: Optional[str] = None
    
    # API settings
    api_token: Optional[str] = None  # Optional static token for development
    
    # Hyper-V Host settings
    hyperv_hosts: str = ""  # Comma-separated list of hosts
    winrm_username: Optional[str] = None
    winrm_password: Optional[str] = None
    winrm_transport: str = "ntlm"  # ntlm, basic, or credssp
    winrm_port: int = 5985
    
    # Inventory settings
    inventory_refresh_interval: int = 60  # seconds
    
    # Host deployment settings
    development_install: bool = False  # Use development directories on hosts
    
    # Artifact paths (ISOs and scripts bundled in container)
    artifacts_base_path: str = "/app/artifacts"
    
    @property
    def iso_path(self) -> str:
        """Get path to ISOs in container."""
        return f"{self.artifacts_base_path}/isos"
    
    @property
    def script_path(self) -> str:
        """Get path to scripts in container."""
        return f"{self.artifacts_base_path}/scripts"
    
    @property
    def version_file_path(self) -> str:
        """Get path to version file in container."""
        return f"{self.artifacts_base_path}/version"
    
    @property
    def host_install_directory(self) -> str:
        """Get installation directory on Hyper-V hosts."""
        if self.development_install:
            return "C:\\Program Files\\Home Lab Virtual Machine Manager (Devel)"
        return "C:\\Program Files\\Home Lab Virtual Machine Manager"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_hyperv_hosts_list(self) -> List[str]:
        """Parse comma-separated host list."""
        if not self.hyperv_hosts:
            return []
        return [h.strip() for h in self.hyperv_hosts.split(",") if h.strip()]


settings = Settings()
