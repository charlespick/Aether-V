"""
Pytest configuration and shared fixtures for Aether-V Server tests.
"""
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config():
    """Mock configuration for tests."""
    config = Mock()
    config.DEBUG = True
    config.AUTH_ENABLED = False
    config.HYPERV_HOSTS = ["host1.example.com", "host2.example.com"]
    config.WINRM_USERNAME = "test_user"
    config.WINRM_PASSWORD = "test_password"
    config.WINRM_TRANSPORT = "ntlm"
    config.WINRM_PORT = 5985
    config.INVENTORY_REFRESH_INTERVAL = 300
    config.HOST_INSTALL_DIRECTORY = "C:\\Aether-V"
    config.AGENT_DOWNLOAD_BASE_URL = "http://localhost:8000"
    return config


@pytest.fixture
def mock_wsman():
    """Mock WSMan connection for WinRM tests."""
    mock = Mock()
    mock.close = Mock()
    return mock


@pytest.fixture
def mock_runspace_pool():
    """Mock RunspacePool for PowerShell tests."""
    mock = Mock()
    mock.close = Mock()
    return mock


@pytest.fixture
def mock_powershell():
    """Mock PowerShell for WinRM tests."""
    mock = Mock()
    mock.output = []
    mock.streams = Mock()
    mock.streams.error = []
    mock.close = Mock()
    return mock


@pytest.fixture
async def mock_async_client() -> AsyncGenerator:
    """Mock httpx AsyncClient for API tests."""
    client = AsyncMock()
    
    # Mock response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json = Mock(return_value={"status": "ok"})
    
    client.get = AsyncMock(return_value=mock_response)
    client.post = AsyncMock(return_value=mock_response)
    client.put = AsyncMock(return_value=mock_response)
    client.delete = AsyncMock(return_value=mock_response)
    
    yield client


@pytest.fixture
def sample_vm_data():
    """Sample VM data for testing."""
    return {
        "Name": "test-vm-01",
        "State": "Running",
        "Uptime": "01:23:45",
        "Status": "Operating normally",
        "CPUUsage": 10,
        "MemoryAssigned": 2048,
        "MemoryDemand": 1024,
        "Version": "9.0"
    }


@pytest.fixture
def sample_host_data():
    """Sample host data for testing."""
    return {
        "ComputerName": "host1.example.com",
        "TotalMemory": 32768,
        "AvailableMemory": 16384,
        "ProcessorCount": 8,
        "LogicalProcessorCount": 16,
        "OperatingSystem": "Microsoft Windows Server 2022",
        "Version": "10.0.20348.0"
    }


@pytest.fixture
def sample_job_data():
    """Sample job data for testing."""
    return {
        "job_id": "test-job-123",
        "type": "provision_vm",
        "status": "running",
        "host": "host1.example.com",
        "vm_name": "test-vm-01",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:01:00Z"
    }


# Markers documentation
pytest.mark.unit.__doc__ = "Unit tests - fast, no external dependencies"
pytest.mark.integration.__doc__ = "Integration tests - may require mocks"
pytest.mark.slow.__doc__ = "Slow-running tests"
pytest.mark.winrm.__doc__ = "Tests that interact with WinRM (mocked in CI)"
pytest.mark.powershell.__doc__ = "Tests that interact with PowerShell (mocked in CI)"
pytest.mark.requires_hosts.__doc__ = "Tests that require actual Hyper-V hosts (skip in CI)"
