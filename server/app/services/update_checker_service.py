"""Service for checking GitHub releases for available updates."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx

from ..core.build_info import build_metadata
from ..core.config import settings
from ..core.models import NotificationLevel
from .notification_service import notification_service

logger = logging.getLogger(__name__)

# Check interval in seconds (1 hour)
UPDATE_CHECK_INTERVAL_SECONDS = 3600

# Notification key for update availability
UPDATE_NOTIFICATION_KEY = "application-update-available"


def _extract_owner_repo(github_url: Optional[str]) -> Optional[tuple[str, str]]:
    """Extract owner and repo from a GitHub repository URL.
    
    Supports URLs like:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo/
    """
    if not github_url:
        return None
    
    # Match GitHub repository URL pattern
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$",
        github_url.strip(),
    )
    if match:
        return match.group(1), match.group(2)
    
    return None


def _normalize_version(version: str) -> str:
    """Normalize version string by removing 'v' prefix and leading zeros in segments."""
    # Remove leading 'v' or 'V' prefix
    normalized = version.lstrip("vV").strip()
    
    # Normalize leading zeros in each segment (e.g., 2.4.000 -> 2.4.0)
    parts = normalized.split(".")
    normalized_parts = []
    for part in parts:
        # Try to convert to int to strip leading zeros, fall back to original
        try:
            normalized_parts.append(str(int(part)))
        except ValueError:
            normalized_parts.append(part)
    
    return ".".join(normalized_parts)


def _compare_versions(current: str, latest: str) -> int:
    """Compare two version strings.
    
    Returns:
        -1 if current < latest (update available)
        0 if current == latest (up to date)
        1 if current > latest (ahead of release)
    """
    current_normalized = _normalize_version(current)
    latest_normalized = _normalize_version(latest)
    
    # Split into parts for comparison
    current_parts = current_normalized.split(".")
    latest_parts = latest_normalized.split(".")
    
    # Pad to same length
    max_len = max(len(current_parts), len(latest_parts))
    while len(current_parts) < max_len:
        current_parts.append("0")
    while len(latest_parts) < max_len:
        latest_parts.append("0")
    
    for current_part, latest_part in zip(current_parts, latest_parts):
        try:
            curr_val = int(current_part)
            latest_val = int(latest_part)
            if curr_val < latest_val:
                return -1
            if curr_val > latest_val:
                return 1
        except ValueError:
            # Fall back to string comparison for non-numeric parts
            if current_part < latest_part:
                return -1
            if current_part > latest_part:
                return 1
    
    return 0


class UpdateCheckerService:
    """Service for checking GitHub releases for available updates."""

    def __init__(self):
        self._check_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._latest_version: Optional[str] = None
        self._update_available = False
        self._http_client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Start the update checker service."""
        logger.info("Starting update checker service")
        
        owner_repo = _extract_owner_repo(build_metadata.github_repository)
        if not owner_repo:
            logger.info(
                "GitHub repository URL not available; update checker disabled"
            )
            self._initialized = True
            return
        
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._initialized = True
        
        # Perform initial check at startup
        await self._check_for_updates()
        
        # Start periodic check loop
        loop = asyncio.get_running_loop()
        self._check_task = loop.create_task(self._check_loop())
        
        logger.info("Update checker service started")

    async def stop(self) -> None:
        """Stop the update checker service."""
        logger.info("Stopping update checker service")
        
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                logger.debug("Update check loop cancelled")
            self._check_task = None
        
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        
        notification_service.clear_system_notification(UPDATE_NOTIFICATION_KEY)
        self._initialized = False
        logger.info("Update checker service stopped")

    async def _check_loop(self) -> None:
        """Periodically check for updates."""
        while True:
            try:
                await asyncio.sleep(UPDATE_CHECK_INTERVAL_SECONDS)
                await self._check_for_updates()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in update check loop: %s", exc)

    async def _check_for_updates(self) -> None:
        """Check GitHub releases API for the latest version."""
        owner_repo = _extract_owner_repo(build_metadata.github_repository)
        if not owner_repo:
            return
        
        owner, repo = owner_repo
        current_version = build_metadata.version
        
        if current_version == "unknown":
            logger.debug("Current version is unknown; skipping update check")
            return
        
        try:
            latest_tag = await self._fetch_latest_release_tag(owner, repo)
            if not latest_tag:
                logger.debug("No releases found for %s/%s", owner, repo)
                return
            
            self._latest_version = latest_tag
            comparison = _compare_versions(current_version, latest_tag)
            
            if comparison < 0:
                # Update available
                self._update_available = True
                latest_normalized = _normalize_version(latest_tag)
                current_normalized = _normalize_version(current_version)
                
                logger.info(
                    "Update available: current=%s latest=%s",
                    current_normalized,
                    latest_normalized,
                )
                
                release_url = f"https://github.com/{owner}/{repo}/releases/tag/{latest_tag}"
                
                notification_service.upsert_system_notification(
                    UPDATE_NOTIFICATION_KEY,
                    title="Application update available",
                    message=(
                        f"A new version of {settings.app_name} is available: {latest_normalized}. "
                        f"You are currently running version {current_normalized}."
                    ),
                    level=NotificationLevel.INFO,
                    metadata={
                        "current_version": current_normalized,
                        "latest_version": latest_normalized,
                        "release_url": release_url,
                    },
                )
            else:
                # Up to date or ahead
                self._update_available = False
                notification_service.clear_system_notification(UPDATE_NOTIFICATION_KEY)
                logger.debug(
                    "No update needed: current=%s latest=%s",
                    current_version,
                    latest_tag,
                )
        except Exception as exc:
            logger.warning("Failed to check for updates: %s", exc)

    async def _fetch_latest_release_tag(
        self, owner: str, repo: str
    ) -> Optional[str]:
        """Fetch the latest release tag from GitHub API."""
        if not self._http_client:
            return None
        
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        
        try:
            response = await self._http_client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            
            if response.status_code == 404:
                logger.debug("No releases found for %s/%s", owner, repo)
                return None
            
            response.raise_for_status()
            data = response.json()
            
            tag_name = data.get("tag_name")
            if isinstance(tag_name, str) and tag_name:
                logger.debug("Latest release tag for %s/%s: %s", owner, repo, tag_name)
                return str(tag_name)
            
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "GitHub API returned error for %s/%s: %s",
                owner,
                repo,
                exc.response.status_code,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning("Network error checking releases for %s/%s: %s", owner, repo, exc)
            return None

    @property
    def is_update_available(self) -> bool:
        """Return whether an update is available."""
        return self._update_available

    @property
    def latest_version(self) -> Optional[str]:
        """Return the latest version from GitHub releases."""
        return self._latest_version


# Global service instance
update_checker_service = UpdateCheckerService()
