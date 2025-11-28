"""Build metadata loader for runtime introspection."""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .config import settings


logger = logging.getLogger(__name__)


class BuildMetadata(BaseModel):
    """Metadata describing how the container image was produced."""

    version: str = Field("unknown", description="Semantic version of the application build")
    source_control: str = Field(
        "unknown",
        description="Source control system detected during the build process",
    )
    git_commit: Optional[str] = Field(
        default=None, description="Full commit SHA if available"
    )
    git_ref: Optional[str] = Field(
        default=None,
        description="Branch name or reference that was built",
    )
    git_state: Optional[str] = Field(
        default=None,
        description="State of the Git repository (branch, detached, or unknown)",
    )
    github_repository: Optional[str] = Field(
        default=None,
        description="GitHub repository URL if built in GitHub Actions",
    )
    build_time: Optional[datetime] = Field(
        default=None, description="Timestamp when the container image was built"
    )
    build_host: Optional[str] = Field(
        default=None, description="Hostname of the builder that produced the image"
    )

    @property
    def build_time_iso(self) -> Optional[str]:
        """Return the build time formatted as an ISO 8601 string."""

        if not self.build_time:
            return None
        return self.build_time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_build_time(raw_value: Optional[str]) -> Optional[datetime]:
    if not raw_value:
        return None

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw_value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    logger.warning("Unable to parse build timestamp '%s'", raw_value)
    return None


def _load_build_metadata() -> BuildMetadata:
    """Load build metadata and version information from container artifacts."""

    version_path = Path(settings.version_file_path)
    metadata_path = version_path.with_name("build-info.json")
    metadata: dict = {}

    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid build metadata JSON: %s", exc)
        except OSError as exc:
            logger.error("Failed to read build metadata file %s: %s", metadata_path, exc)
    else:
        logger.warning("Build metadata file not found at %s", metadata_path)

    version_value = "unknown"
    try:
        version_value = version_path.read_text(encoding="utf-8").strip() or "unknown"
    except FileNotFoundError:
        logger.error(
            "Version file missing at %s; container version will be reported as 'unknown'",
            version_path,
        )
    except OSError as exc:
        logger.error("Failed to read version file %s: %s", version_path, exc)

    build_time = _parse_build_time(metadata.get("build_time"))

    if not metadata.get("build_host"):
        metadata["build_host"] = socket.gethostname()

    return BuildMetadata(
        version=version_value,
        source_control=metadata.get("source_control", "unknown"),
        git_commit=metadata.get("git_commit"),
        git_ref=metadata.get("git_ref"),
        git_state=metadata.get("git_state"),
        github_repository=metadata.get("github_repository"),
        build_time=build_time,
        build_host=metadata.get("build_host"),
    )


build_metadata = _load_build_metadata()


def refresh_build_metadata() -> BuildMetadata:
    """Reload build metadata from disk. Primarily useful for tests."""

    global build_metadata
    build_metadata = _load_build_metadata()
    return build_metadata

