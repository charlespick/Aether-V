import sys
from unittest import IsolatedAsyncioTestCase, skipIf

try:
    from server.app.services.notification_service import NotificationService
    from server.app.core.models import NotificationLevel, NotificationCategory
    IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    NotificationService = None  # type: ignore[assignment]
    NotificationLevel = None  # type: ignore[assignment]
    NotificationCategory = None  # type: ignore[assignment]
    IMPORT_ERROR = exc


@skipIf(NotificationService is None, "Server dependencies not installed")
class NotificationServiceAgentDeploymentTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        assert NotificationService is not None
        assert NotificationLevel is not None
        assert NotificationCategory is not None

        self.service = NotificationService()
        # Prevent background broadcast tasks during tests
        self.service._schedule_broadcast = lambda notification, action='updated': None  # type: ignore[assignment]
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()

    async def test_agent_deployment_notification_create_and_update(self):
        assert NotificationLevel is not None
        assert NotificationCategory is not None

        created = self.service.upsert_agent_deployment_notification(
            status='running',
            message='Deploying agents',
            level=NotificationLevel.INFO,
            provisioning_available=False,
            metadata={'total_hosts': 2, 'completed_hosts': 1},
        )

        self.assertIsNotNone(created)
        assert created  # for type checkers
        self.assertEqual(created.category, NotificationCategory.SYSTEM)
        self.assertEqual(created.related_entity, 'agent-deployment')
        self.assertFalse(created.metadata.get('provisioning_available'))
        self.assertEqual(created.metadata.get('status'), 'running')

        updated = self.service.upsert_agent_deployment_notification(
            status='successful',
            message='Agents ready',
            level=NotificationLevel.SUCCESS,
            provisioning_available=True,
            metadata={'total_hosts': 2, 'completed_hosts': 2},
        )

        self.assertIsNotNone(updated)
        assert updated
        self.assertEqual(updated.id, created.id)
        self.assertTrue(updated.metadata.get('provisioning_available'))
        self.assertEqual(updated.metadata.get('status'), 'successful')
        self.assertEqual(updated.level, NotificationLevel.SUCCESS)
