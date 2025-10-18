"""Notification management service for system events."""
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from ..core.models import (
    Notification, NotificationLevel, NotificationCategory
)
from ..core.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for managing system notifications."""

    def __init__(self):
        self.notifications: Dict[str, Notification] = {}
        self._initialized = False
        self._websocket_manager = None

    def set_websocket_manager(self, manager):
        """Set the WebSocket manager for broadcasting notifications."""
        self._websocket_manager = manager
        logger.info("WebSocket manager set for notification service")

    async def start(self):
        """Start the notification service."""
        logger.info("Starting notification service")

        if settings.dummy_data:
            logger.info("DUMMY_DATA enabled - using development notifications")
            await self._initialize_dummy_data()
        else:
            # Initialize with empty state
            self.notifications = {}

        self._initialized = True
        logger.info("Notification service started successfully")

    async def stop(self):
        """Stop the notification service."""
        logger.info("Stopping notification service")
        self._initialized = False

    async def _initialize_dummy_data(self):
        """Initialize with dummy notifications for development."""
        logger.info("Initializing dummy notifications for development")

        now = datetime.utcnow()
        dummy_notifications = [
            Notification(
                id=str(uuid.uuid4()),
                title="Job completed",
                message='VM deployment for "web-server-01" has finished successfully.',
                level=NotificationLevel.SUCCESS,
                category=NotificationCategory.JOB,
                created_at=now - timedelta(minutes=2),
                read=False,
                related_entity="web-server-01"
            ),
            Notification(
                id=str(uuid.uuid4()),
                title="Host disconnected",
                message='Host "hyperv-01.domain.local" has lost connection.',
                level=NotificationLevel.ERROR,
                category=NotificationCategory.HOST,
                created_at=now - timedelta(minutes=5),
                read=True,
                related_entity="hyperv-01.domain.local"
            ),
            Notification(
                id=str(uuid.uuid4()),
                title="Host reconnected",
                message='Host "hyperv-02.domain.local" is now online.',
                level=NotificationLevel.INFO,
                category=NotificationCategory.HOST,
                created_at=now - timedelta(minutes=8),
                read=False,
                related_entity="hyperv-02.domain.local"
            ),
            Notification(
                id=str(uuid.uuid4()),
                title="VM state changed",
                message='VM "db-server-01" has been powered off.',
                level=NotificationLevel.WARNING,
                category=NotificationCategory.VM,
                created_at=now - timedelta(minutes=15),
                read=True,
                related_entity="db-server-01"
            ),
            Notification(
                id=str(uuid.uuid4()),
                title="Authentication expired",
                message="Your session has expired. Please log in again.",
                level=NotificationLevel.WARNING,
                category=NotificationCategory.AUTHENTICATION,
                created_at=now - timedelta(hours=1),
                read=False,
                related_entity=None
            ),
            Notification(
                id=str(uuid.uuid4()),
                title="System maintenance",
                message="Scheduled maintenance completed successfully. All services are operational.",
                level=NotificationLevel.INFO,
                category=NotificationCategory.SYSTEM,
                created_at=now - timedelta(hours=2),
                read=True,
                related_entity=None
            )
        ]

        # Add dummy notifications to the state
        for notification in dummy_notifications:
            self.notifications[notification.id] = notification

        logger.info(
            f"Initialized {len(dummy_notifications)} dummy notifications")

    def create_notification(
        self,
        title: str,
        message: str,
        level: NotificationLevel,
        category: NotificationCategory,
        related_entity: Optional[str] = None
    ) -> Notification:
        """Create a new notification."""
        if not self._initialized:
            logger.warning(
                "Notification service not initialized, skipping notification creation")
            return None

        notification = Notification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            level=level,
            category=category,
            created_at=datetime.utcnow(),
            read=False,
            related_entity=related_entity
        )

        self.notifications[notification.id] = notification
        logger.info(
            f"Created notification: {notification.title} ({notification.level})")

        # Broadcast notification via WebSocket
        if self._websocket_manager:
            task = asyncio.create_task(
                self._broadcast_notification(notification))
            task.add_done_callback(self._handle_broadcast_task_exception)

        return notification

    async def _broadcast_notification(self, notification: Notification):
        """Broadcast a new notification via WebSocket."""
        try:
            await self._websocket_manager.broadcast({
                "type": "notification",
                "action": "created",
                "data": {
                    "id": notification.id,
                    "title": notification.title,
                    "message": notification.message,
                    "level": notification.level.value,
                    "category": notification.category.value,
                    "created_at": notification.created_at.isoformat(),
                    "read": notification.read,
                    "related_entity": notification.related_entity
                }
            }, topic="notifications")
        except Exception as e:
            logger.error(f"Error broadcasting notification via WebSocket: {e}")

    def _handle_broadcast_task_exception(self, task):
        """Handle exceptions from broadcast tasks."""
        try:
            exception = task.exception()
            if exception:
                logger.error(f"Exception in broadcast task: {exception}")
        except Exception as e:
            logger.error(f"Error handling broadcast task exception: {e}")

    def create_host_unreachable_notification(self, hostname: str, error: str) -> Notification:
        """Create a notification for when a host becomes unreachable."""
        return self.create_notification(
            title="Host unreachable",
            message=f'Host "{hostname}" is not responding. Error: {error}',
            level=NotificationLevel.ERROR,
            category=NotificationCategory.HOST,
            related_entity=hostname
        )

    def create_host_reconnected_notification(self, hostname: str) -> Notification:
        """Create a notification for when a host reconnects."""
        return self.create_notification(
            title="Host reconnected",
            message=f'Host "{hostname}" is now online and responding.',
            level=NotificationLevel.INFO,
            category=NotificationCategory.HOST,
            related_entity=hostname
        )

    def create_job_completed_notification(self, job_type: str, target: str, success: bool) -> Notification:
        """Create a notification for job completion."""
        if success:
            return self.create_notification(
                title="Job completed",
                message=f'{job_type.replace("_", " ").title()} for "{target}" completed successfully.',
                level=NotificationLevel.SUCCESS,
                category=NotificationCategory.JOB,
                related_entity=target
            )
        else:
            return self.create_notification(
                title="Job failed",
                message=f'{job_type.replace("_", " ").title()} for "{target}" failed.',
                level=NotificationLevel.ERROR,
                category=NotificationCategory.JOB,
                related_entity=target
            )

    def get_all_notifications(self, limit: Optional[int] = None) -> List[Notification]:
        """Get all notifications, ordered by creation date (newest first)."""
        notifications = sorted(
            self.notifications.values(),
            key=lambda n: n.created_at,
            reverse=True
        )

        if limit:
            notifications = notifications[:limit]

        return notifications

    def get_unread_notifications(self, limit: Optional[int] = None) -> List[Notification]:
        """Get unread notifications, ordered by creation date (newest first)."""
        unread = [n for n in self.notifications.values() if not n.read]
        unread = sorted(unread, key=lambda n: n.created_at, reverse=True)

        if limit:
            unread = unread[:limit]

        return unread

    def get_notification(self, notification_id: str) -> Optional[Notification]:
        """Get a specific notification by ID."""
        return self.notifications.get(notification_id)

    def mark_notification_read(self, notification_id: str) -> bool:
        """Mark a notification as read."""
        notification = self.notifications.get(notification_id)
        if notification:
            notification.read = True
            logger.info(f"Marked notification {notification_id} as read")

            # Broadcast update via WebSocket
            if self._websocket_manager:
                task = asyncio.create_task(
                    self._broadcast_notification_update(notification))
                task.add_done_callback(self._handle_broadcast_task_exception)

            return True
        return False

    async def _broadcast_notification_update(self, notification: Notification):
        """Broadcast a notification update via WebSocket."""
        try:
            await self._websocket_manager.broadcast({
                "type": "notification",
                "action": "updated",
                "data": {
                    "id": notification.id,
                    "read": notification.read
                }
            }, topic="notifications")
        except Exception as e:
            logger.error(
                f"Error broadcasting notification update via WebSocket: {e}")

    def mark_all_read(self) -> int:
        """Mark all notifications as read. Returns count of notifications marked."""
        count = 0
        for notification in self.notifications.values():
            if not notification.read:
                notification.read = True
                count += 1

        if count > 0:
            logger.info(f"Marked {count} notifications as read")

        return count

    def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification."""
        if notification_id in self.notifications:
            del self.notifications[notification_id]
            logger.info(f"Deleted notification {notification_id}")
            return True
        return False

    def cleanup_old_notifications(self, max_age_days: int = 30) -> int:
        """Clean up notifications older than specified days. Returns count of deleted notifications."""
        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)
        to_delete = []

        for notification_id, notification in self.notifications.items():
            if notification.created_at < cutoff_date:
                to_delete.append(notification_id)

        for notification_id in to_delete:
            del self.notifications[notification_id]

        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old notifications")

        return len(to_delete)

    def get_notification_count(self) -> int:
        """Get total notification count."""
        return len(self.notifications)

    def get_unread_count(self) -> int:
        """Get unread notification count."""
        return len([n for n in self.notifications.values() if not n.read])

    def clear_host_notifications(self, hostname: str) -> int:
        """Clear all notifications related to a specific host. Returns count of cleared notifications."""
        to_delete = []

        for notification_id, notification in self.notifications.items():
            if (notification.category == NotificationCategory.HOST and
                    notification.related_entity == hostname):
                to_delete.append(notification_id)

        for notification_id in to_delete:
            del self.notifications[notification_id]

        if to_delete:
            logger.info(
                f"Cleared {len(to_delete)} notifications for host {hostname}")

        return len(to_delete)


# Global notification service instance
notification_service = NotificationService()
