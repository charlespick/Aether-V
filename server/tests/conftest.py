"""Test configuration for server test suite."""

try:  # Ensure PyYAML is loaded before tests stub it out
    import yaml  # noqa: F401
except Exception:
    # When PyYAML is unavailable we silently continue; individual tests
    # provide lightweight fallbacks that satisfy their expectations.
    pass
