"""Tests for the update checker service."""

from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import AsyncMock, MagicMock, patch

# Try importing the service module
try:
    from server.app.services.update_checker_service import (
        UpdateCheckerService,
        _extract_owner_repo,
        _normalize_version,
        _compare_versions,
        UPDATE_NOTIFICATION_KEY,
    )
    from server.app.core.models import NotificationLevel
    IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    UpdateCheckerService = None  # type: ignore[assignment]
    _extract_owner_repo = None  # type: ignore[assignment]
    _normalize_version = None  # type: ignore[assignment]
    _compare_versions = None  # type: ignore[assignment]
    UPDATE_NOTIFICATION_KEY = None  # type: ignore[assignment]
    NotificationLevel = None  # type: ignore[assignment]
    IMPORT_ERROR = exc


@skipIf(UpdateCheckerService is None, "Server dependencies not installed")
class TestExtractOwnerRepo(IsolatedAsyncioTestCase):
    """Tests for GitHub URL parsing."""

    async def test_extract_owner_repo_standard_url(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("https://github.com/owner/repo")
        self.assertEqual(result, ("owner", "repo"))

    async def test_extract_owner_repo_with_git_suffix(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("https://github.com/owner/repo.git")
        self.assertEqual(result, ("owner", "repo"))

    async def test_extract_owner_repo_with_trailing_slash(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("https://github.com/owner/repo/")
        self.assertEqual(result, ("owner", "repo"))

    async def test_extract_owner_repo_http(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("http://github.com/owner/repo")
        self.assertEqual(result, ("owner", "repo"))

    async def test_extract_owner_repo_none_input(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo(None)
        self.assertIsNone(result)

    async def test_extract_owner_repo_empty_string(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("")
        self.assertIsNone(result)

    async def test_extract_owner_repo_invalid_url(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("not-a-url")
        self.assertIsNone(result)

    async def test_extract_owner_repo_non_github_url(self):
        assert _extract_owner_repo is not None
        result = _extract_owner_repo("https://gitlab.com/owner/repo")
        self.assertIsNone(result)


@skipIf(UpdateCheckerService is None, "Server dependencies not installed")
class TestNormalizeVersion(IsolatedAsyncioTestCase):
    """Tests for version normalization."""

    async def test_normalize_version_with_v_prefix(self):
        assert _normalize_version is not None
        result = _normalize_version("v1.2.3")
        self.assertEqual(result, "1.2.3")

    async def test_normalize_version_with_capital_v_prefix(self):
        assert _normalize_version is not None
        result = _normalize_version("V1.2.3")
        self.assertEqual(result, "1.2.3")

    async def test_normalize_version_without_prefix(self):
        assert _normalize_version is not None
        result = _normalize_version("1.2.3")
        self.assertEqual(result, "1.2.3")

    async def test_normalize_version_with_leading_zeros(self):
        assert _normalize_version is not None
        result = _normalize_version("2.4.000")
        self.assertEqual(result, "2.4.0")

    async def test_normalize_version_complex(self):
        assert _normalize_version is not None
        result = _normalize_version("v02.04.003")
        self.assertEqual(result, "2.4.3")


@skipIf(UpdateCheckerService is None, "Server dependencies not installed")
class TestCompareVersions(IsolatedAsyncioTestCase):
    """Tests for version comparison."""

    async def test_compare_versions_equal(self):
        assert _compare_versions is not None
        result = _compare_versions("1.2.3", "1.2.3")
        self.assertEqual(result, 0)

    async def test_compare_versions_equal_with_prefixes(self):
        assert _compare_versions is not None
        result = _compare_versions("v1.2.3", "1.2.3")
        self.assertEqual(result, 0)

    async def test_compare_versions_equal_with_leading_zeros(self):
        assert _compare_versions is not None
        result = _compare_versions("2.4.000", "v2.4.0")
        self.assertEqual(result, 0)

    async def test_compare_versions_current_less_than_latest(self):
        assert _compare_versions is not None
        result = _compare_versions("1.2.3", "1.2.4")
        self.assertEqual(result, -1)

    async def test_compare_versions_current_greater_than_latest(self):
        assert _compare_versions is not None
        result = _compare_versions("2.0.0", "1.9.9")
        self.assertEqual(result, 1)

    async def test_compare_versions_major_difference(self):
        assert _compare_versions is not None
        result = _compare_versions("1.0.0", "2.0.0")
        self.assertEqual(result, -1)

    async def test_compare_versions_minor_difference(self):
        assert _compare_versions is not None
        result = _compare_versions("1.1.0", "1.2.0")
        self.assertEqual(result, -1)

    async def test_compare_versions_different_length(self):
        assert _compare_versions is not None
        result = _compare_versions("1.2", "1.2.0")
        self.assertEqual(result, 0)

    async def test_compare_versions_different_length_not_equal(self):
        assert _compare_versions is not None
        result = _compare_versions("1.2", "1.2.1")
        self.assertEqual(result, -1)


@skipIf(UpdateCheckerService is None, "Server dependencies not installed")
class TestUpdateCheckerService(IsolatedAsyncioTestCase):
    """Integration tests for the UpdateCheckerService."""

    async def asyncSetUp(self):
        assert UpdateCheckerService is not None
        self.service = UpdateCheckerService()

    async def asyncTearDown(self):
        await self.service.stop()

    async def test_start_without_github_url(self):
        """Test that service starts but is disabled when no GitHub URL is configured."""
        with patch(
            "server.app.services.update_checker_service.build_metadata"
        ) as mock_metadata:
            mock_metadata.github_repository = None
            
            await self.service.start()
            
            self.assertTrue(self.service._initialized)
            self.assertIsNone(self.service._check_task)

    async def test_fetch_latest_release_tag(self):
        """Test fetching the latest release tag from GitHub API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tag_name": "v1.2.3"}
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        
        self.service._http_client = mock_client
        
        result = await self.service._fetch_latest_release_tag("owner", "repo")
        
        self.assertEqual(result, "v1.2.3")
        mock_client.get.assert_called_once()

    async def test_fetch_latest_release_tag_404(self):
        """Test handling of 404 response (no releases)."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        
        self.service._http_client = mock_client
        
        result = await self.service._fetch_latest_release_tag("owner", "repo")
        
        self.assertIsNone(result)

    async def test_check_for_updates_update_available(self):
        """Test that notification is posted when update is available."""
        with patch(
            "server.app.services.update_checker_service.build_metadata"
        ) as mock_metadata, patch(
            "server.app.services.update_checker_service.notification_service"
        ) as mock_notification:
            mock_metadata.github_repository = "https://github.com/owner/repo"
            mock_metadata.version = "1.0.0"
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"tag_name": "v2.0.0"}
            
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            
            self.service._http_client = mock_client
            
            await self.service._check_for_updates()
            
            self.assertTrue(self.service._update_available)
            self.assertEqual(self.service._latest_version, "v2.0.0")
            mock_notification.upsert_system_notification.assert_called_once()
            
            call_kwargs = mock_notification.upsert_system_notification.call_args[1]
            self.assertEqual(call_kwargs["title"], "Application update available")
            self.assertIn("2.0.0", call_kwargs["message"])
            self.assertIn("1.0.0", call_kwargs["message"])

    async def test_check_for_updates_up_to_date(self):
        """Test that notification is cleared when up to date."""
        with patch(
            "server.app.services.update_checker_service.build_metadata"
        ) as mock_metadata, patch(
            "server.app.services.update_checker_service.notification_service"
        ) as mock_notification:
            mock_metadata.github_repository = "https://github.com/owner/repo"
            mock_metadata.version = "2.0.0"
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"tag_name": "v2.0.0"}
            
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            
            self.service._http_client = mock_client
            
            await self.service._check_for_updates()
            
            self.assertFalse(self.service._update_available)
            mock_notification.clear_system_notification.assert_called_once()

    async def test_check_for_updates_unknown_version(self):
        """Test that check is skipped when current version is unknown."""
        with patch(
            "server.app.services.update_checker_service.build_metadata"
        ) as mock_metadata:
            mock_metadata.github_repository = "https://github.com/owner/repo"
            mock_metadata.version = "unknown"
            
            mock_client = AsyncMock()
            self.service._http_client = mock_client
            
            await self.service._check_for_updates()
            
            # Should not make any API calls
            mock_client.get.assert_not_called()

    async def test_is_update_available_property(self):
        """Test the is_update_available property."""
        self.assertFalse(self.service.is_update_available)
        
        self.service._update_available = True
        self.assertTrue(self.service.is_update_available)

    async def test_latest_version_property(self):
        """Test the latest_version property."""
        self.assertIsNone(self.service.latest_version)
        
        self.service._latest_version = "v1.2.3"
        self.assertEqual(self.service.latest_version, "v1.2.3")
