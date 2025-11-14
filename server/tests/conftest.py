"""Test configuration for server test suite."""

import os

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
