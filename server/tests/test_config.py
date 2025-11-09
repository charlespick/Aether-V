"""
Tests for configuration module.
"""
import os
from unittest.mock import patch

import pytest

from app.core.config import Settings, AGENT_ARTIFACTS_DIR, AGENT_HTTP_MOUNT_PATH


@pytest.mark.unit
class TestSettings:
    """Test configuration settings."""

    def test_default_settings(self):
        """Test that default settings are loaded correctly."""
        settings = Settings()
        
        assert settings.app_name == "Aether-V Server"
        assert settings.debug is False
        assert settings.auth_enabled is True
        assert settings.allow_dev_auth is False

    def test_settings_from_env(self):
        """Test that settings can be loaded from environment variables."""
        env_vars = {
            "APP_NAME": "Test Server",
            "DEBUG": "true",
            "AUTH_ENABLED": "false",
            "HYPERV_HOSTS": "host1.example.com,host2.example.com",
            "WINRM_USERNAME": "testuser",
            "WINRM_PASSWORD": "testpass",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            
            assert settings.app_name == "Test Server"
            assert settings.debug is True
            assert settings.auth_enabled is False
            assert settings.hyperv_hosts == ["host1.example.com", "host2.example.com"]
            assert settings.winrm_username == "testuser"
            assert settings.winrm_password == "testpass"

    def test_oidc_settings(self):
        """Test OIDC configuration settings."""
        env_vars = {
            "AUTH_ENABLED": "true",
            "OIDC_ISSUER_URL": "https://login.example.com",
            "OIDC_CLIENT_ID": "test-client-id",
            "OIDC_CLIENT_SECRET": "test-secret",
            "OIDC_API_AUDIENCE": "api://test",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            
            assert settings.auth_enabled is True
            assert settings.oidc_issuer_url == "https://login.example.com"
            assert settings.oidc_client_id == "test-client-id"
            assert settings.oidc_client_secret == "test-secret"
            assert settings.oidc_api_audience == "api://test"

    def test_winrm_settings(self):
        """Test WinRM configuration settings."""
        env_vars = {
            "HYPERV_HOSTS": "host1.local,host2.local,host3.local",
            "WINRM_USERNAME": "admin",
            "WINRM_PASSWORD": "P@ssw0rd",
            "WINRM_TRANSPORT": "ntlm",
            "WINRM_PORT": "5986",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            
            assert len(settings.hyperv_hosts) == 3
            assert "host1.local" in settings.hyperv_hosts
            assert settings.winrm_username == "admin"
            assert settings.winrm_password == "P@ssw0rd"
            assert settings.winrm_transport == "ntlm"
            assert settings.winrm_port == 5986

    def test_inventory_refresh_interval(self):
        """Test inventory refresh interval setting."""
        env_vars = {
            "INVENTORY_REFRESH_INTERVAL": "600",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.inventory_refresh_interval == 600

    def test_agent_paths(self):
        """Test agent artifact path constants."""
        assert AGENT_ARTIFACTS_DIR.name == "agent"
        assert str(AGENT_ARTIFACTS_DIR).endswith("/app/agent")
        assert AGENT_HTTP_MOUNT_PATH == "/agent"

    def test_session_settings(self):
        """Test session management settings."""
        env_vars = {
            "SESSION_SECRET_KEY": "test-secret-key-12345",
            "SESSION_MAX_AGE": "7200",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            
            assert settings.session_secret_key == "test-secret-key-12345"
            assert settings.session_max_age == 7200

    def test_dev_auth_mode(self):
        """Test development authentication mode."""
        env_vars = {
            "AUTH_ENABLED": "false",
            "ALLOW_DEV_AUTH": "true",
        }
        
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            
            assert settings.auth_enabled is False
            assert settings.allow_dev_auth is True
