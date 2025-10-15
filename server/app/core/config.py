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
    
    # Paths (for future ISO/script deployment)
    script_path: str = "/app/scripts"
    iso_path: str = "/app/isos"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_hyperv_hosts_list(self) -> List[str]:
        """Parse comma-separated host list."""
        if not self.hyperv_hosts:
            return []
        return [h.strip() for h in self.hyperv_hosts.split(",") if h.strip()]


settings = Settings()
