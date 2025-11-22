"""Test configuration for server test suite."""

import os
import subprocess
from pathlib import Path

import pytest

# Disable Kerberos configuration in test environment
# This must happen before any imports that might trigger Kerberos initialization
os.environ.setdefault('WINRM_KERBEROS_PRINCIPAL', '')
os.environ.setdefault('WINRM_KEYTAB_B64', '')

try:  # Ensure PyYAML is loaded before tests stub it out
    import yaml  # noqa: F401
except Exception:
    # When PyYAML is unavailable we silently continue; individual tests
    # provide lightweight fallbacks that satisfy their expectations.
    pass


# Shared fixtures for PowerShell-based tests
@pytest.fixture(scope="session")
def script_path():
    """Get path to Main-NewProtocol.ps1.
    
    This fixture is shared across Phase 3 and Phase 4 tests.
    """
    repo_root = Path(__file__).parent.parent.parent
    script_path = repo_root / "Powershell" / "Main-NewProtocol.ps1"
    
    if not script_path.exists():
        pytest.skip(f"Script not found at {script_path}")
    
    return script_path


@pytest.fixture(scope="session")
def pwsh_available():
    """Check if pwsh is available.
    
    This fixture is shared across Phase 3 and Phase 4 tests.
    """
    try:
        result = subprocess.run(
            ["pwsh", "-Version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            pytest.skip("PowerShell (pwsh) not available")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("PowerShell (pwsh) not available")
