import json
from datetime import datetime, timezone

import pytest

from app.core import build_info
from app.core import config


@pytest.fixture(autouse=True)
def restore_agent_version_path(monkeypatch):
    original_path = config.AGENT_VERSION_PATH
    yield
    monkeypatch.setattr(config, "AGENT_VERSION_PATH", original_path, raising=False)


def test_refresh_build_metadata_loads_version_and_metadata(tmp_path, monkeypatch):
    version_path = tmp_path / "version"
    metadata_path = version_path.with_name("build-info.json")

    version_path.write_text("2.4.6\n", encoding="utf-8")
    metadata_payload = {
        "source_control": "git",
        "git_commit": "abc123",
        "git_ref": "main",
        "git_state": "clean",
        "github_repository": "https://github.com/testorg/testrepo",
        "build_time": "2024-01-02T03:04:05Z",
        "build_host": "builder-01",
    }
    metadata_path.write_text(json.dumps(metadata_payload), encoding="utf-8")

    monkeypatch.setattr(config, "AGENT_VERSION_PATH", version_path, raising=False)
    monkeypatch.setattr(build_info.socket, "gethostname", lambda: "fallback-host")

    metadata = build_info.refresh_build_metadata()

    assert metadata.version == "2.4.6"
    assert metadata.source_control == "git"
    assert metadata.git_commit == "abc123"
    assert metadata.git_ref == "main"
    assert metadata.git_state == "clean"
    assert metadata.github_repository == "https://github.com/testorg/testrepo"
    assert metadata.build_host == "builder-01"
    assert metadata.build_time == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert metadata.build_time_iso == "2024-01-02T03:04:05Z"


def test_refresh_build_metadata_handles_missing_metadata(tmp_path, monkeypatch):
    version_path = tmp_path / "version"
    version_path.write_text("\n", encoding="utf-8")
    metadata_path = version_path.with_name("build-info.json")
    metadata_path.write_text(json.dumps({"build_time": "invalid"}), encoding="utf-8")

    monkeypatch.setattr(config, "AGENT_VERSION_PATH", version_path, raising=False)
    monkeypatch.setattr(build_info.socket, "gethostname", lambda: "runtime-host")

    metadata = build_info.refresh_build_metadata()

    assert metadata.version == "unknown"
    assert metadata.build_host == "runtime-host"
    assert metadata.build_time is None
    assert metadata.build_time_iso is None
