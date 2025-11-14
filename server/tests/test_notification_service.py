import sys
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import patch

# Patch Kerberos configuration before importing services to prevent hanging subprocess calls
kerberos_config_patcher = patch('server.app.core.config.Settings.has_kerberos_config', return_value=False)
kerberos_config_patcher.start()
kerberos_principal_patcher = patch('server.app.core.config.Settings.winrm_kerberos_principal', None)
kerberos_principal_patcher.start()
kerberos_keytab_patcher = patch('server.app.core.config.Settings.winrm_keytab_b64', None)
kerberos_keytab_patcher.start()

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
        self.broadcast_calls = []

        def capture_broadcast(notification, action='updated', extra=None):
            self.broadcast_calls.append(
                {'notification': notification, 'action': action, 'extra': extra}
            )

        self.service._schedule_broadcast = capture_broadcast  # type: ignore[assignment]
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

    async def test_mark_all_read_triggers_broadcast_with_unread_count(self):
        assert NotificationLevel is not None
        assert NotificationCategory is not None

        self.service.create_notification(
            title='Unread 1',
            message='First unread notification',
            level=NotificationLevel.INFO,
            category=NotificationCategory.SYSTEM,
        )
        self.service.create_notification(
            title='Unread 2',
            message='Second unread notification',
            level=NotificationLevel.WARNING,
            category=NotificationCategory.SYSTEM,
        )

        # Clear broadcasts from creation events
        self.broadcast_calls.clear()

        updated_count = self.service.mark_all_read()

        self.assertEqual(updated_count, 2)
        self.assertGreaterEqual(len(self.broadcast_calls), 1)
        unread_counts = {
            call['extra']['unread_count']
            for call in self.broadcast_calls
            if call['extra'] and 'unread_count' in call['extra']
        }
        self.assertIn(0, unread_counts)
