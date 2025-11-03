import sys
import types
import uuid
from datetime import datetime
from typing import List, Tuple
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import patch


yaml_stub = types.ModuleType("yaml")
yaml_stub.safe_dump = lambda data, sort_keys=False: ""
sys.modules.setdefault("yaml", yaml_stub)

try:
    import server.app.services.job_service as job_service_module
    from server.app.core.models import (
        Job,
        JobStatus,
        Notification,
        NotificationCategory,
        NotificationLevel,
    )
    from server.app.services.job_service import JobService
    IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    job_service_module = None
    JobService = None
    Job = None
    JobStatus = None
    Notification = None
    NotificationCategory = None
    NotificationLevel = None
    IMPORT_ERROR = exc


class StubNotificationService:
    def __init__(self):
        self.calls = []

    def upsert_job_notification(self, job_id, **kwargs):
        self.calls.append((job_id, kwargs))
        return Notification(
            id=str(uuid.uuid4()),
            title=kwargs.get("title", ""),
            message=kwargs.get("message", ""),
            level=kwargs.get("level", NotificationLevel.INFO),
            category=NotificationCategory.JOB,
            created_at=datetime.utcnow(),
            read=False,
            related_entity=job_id,
            metadata=kwargs.get("metadata", {}),
        )


class StubWebSocketManager:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, message, topic=None):
        self.broadcasts.append((message, topic))


@skipIf(job_service_module is None, "Server dependencies not installed")
class JobServiceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.job_service = JobService()
        self.notification_stub = StubNotificationService()
        self.websocket_stub = StubWebSocketManager()

        self.original_notification_service = job_service_module.notification_service
        self.original_websocket_manager = job_service_module.websocket_manager

        job_service_module.notification_service = self.notification_stub
        job_service_module.websocket_manager = self.websocket_stub

    async def asyncTearDown(self):
        job_service_module.notification_service = self.original_notification_service
        job_service_module.websocket_manager = self.original_websocket_manager

    async def test_sync_job_notification_tracks_metadata(self):
        job = Job(
            job_id="job-sync-1",
            job_type="provision_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            parameters={
                "definition": {
                    "schema": {"id": "vm-provisioning", "version": 1},
                    "fields": {"vm_name": "demo-vm"},
                }
            },
            output=[],
        )

        await self.job_service._sync_job_notification(job)

        self.assertIsNotNone(job.notification_id)
        self.assertIn(job.job_id, self.job_service.job_notifications)

        self.assertEqual(len(self.notification_stub.calls), 1)
        job_id, kwargs = self.notification_stub.calls[0]
        self.assertEqual(job_id, job.job_id)

        metadata = kwargs["metadata"]
        self.assertEqual(metadata["job_id"], job.job_id)
        self.assertEqual(metadata["status"], JobStatus.PENDING.value)
        self.assertEqual(metadata.get("vm_name"), "demo-vm")

    async def test_handle_stream_chunk_appends_output_and_broadcasts(self):
        job = Job(
            job_id="job-stream-1",
            job_type="provision_vm",
            status=JobStatus.RUNNING,
            created_at=datetime.utcnow(),
            parameters={"definition": {"schema": {"id": "vm-provisioning", "version": 1}}},
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        captured = []

        async def fake_broadcast(job_id, lines):
            captured.append((job_id, list(lines)))

        self.job_service._broadcast_job_output = fake_broadcast  # type: ignore[assignment]

        await self.job_service._handle_stream_chunk(job.job_id, "stdout", "line1\r\nline2\n")
        await self.job_service._handle_stream_chunk(job.job_id, "stderr", "error-line\r")

        async with self.job_service._lock:
            stored_output = list(self.job_service.jobs[job.job_id].output)

        self.assertEqual(
            stored_output,
            ["line1", "line2", "STDERR: error-line"],
        )

        self.assertEqual(
            captured,
            [
                (job.job_id, ["line1", "line2"]),
                (job.job_id, ["STDERR: error-line"]),
            ],
        )

    async def test_stream_decoder_handles_split_clixml_payloads(self):
        job = Job(
            job_id="job-stream-xml",
            job_type="provision_vm",
            status=JobStatus.RUNNING,
            created_at=datetime.utcnow(),
            parameters={"definition": {}},
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        captured: List[Tuple[str, List[str]]] = []

        async def fake_broadcast(job_id, lines):
            captured.append((job_id, list(lines)))

        self.job_service._broadcast_job_output = fake_broadcast  # type: ignore[assignment]

        chunk1 = "#< CLIXML\r\n"
        chunk2 = (
            "<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">"
            "<Obj><S>Line one</S><S>Line two</S></Obj></Objs>\r\nAfter XML line\n"
        )

        await self.job_service._handle_stream_chunk(job.job_id, "stdout", chunk1)
        await self.job_service._handle_stream_chunk(job.job_id, "stdout", chunk2)
        await self.job_service._finalize_job_streams(job.job_id)

        async with self.job_service._lock:
            stored_output = list(self.job_service.jobs[job.job_id].output)

        self.assertEqual(
            stored_output,
            ["Line one", "Line two", "After XML line"],
        )

        self.assertEqual(
            captured,
            [(job.job_id, ["Line one", "Line two", "After XML line"])],
        )

    async def test_stream_decoder_handles_split_sentinel_across_chunks(self):
        job = Job(
            job_id="job-stream-split",
            job_type="provision_vm",
            status=JobStatus.RUNNING,
            created_at=datetime.utcnow(),
            parameters={"definition": {"schema": {"id": "vm-provisioning", "version": 1}}},
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        captured: List[Tuple[str, List[str]]] = []

        async def fake_broadcast(job_id, lines):
            captured.append((job_id, list(lines)))

        self.job_service._broadcast_job_output = fake_broadcast  # type: ignore[assignment]

        chunk1 = "#< CLI"
        chunk2 = (
            "XML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">"
            "<Obj><S>Split payload</S></Obj></Objs>\n"
        )

        await self.job_service._handle_stream_chunk(job.job_id, "stdout", chunk1)
        await self.job_service._handle_stream_chunk(job.job_id, "stdout", chunk2)
        await self.job_service._finalize_job_streams(job.job_id)

        async with self.job_service._lock:
            stored_output = list(self.job_service.jobs[job.job_id].output)

        self.assertEqual(stored_output, ["Split payload"])
        self.assertEqual(captured, [(job.job_id, ["Split payload"])])

    async def test_get_job_redacts_sensitive_parameters(self):
        job = Job(
            job_id="job-secret-1",
            job_type="provision_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            parameters={
                "definition": {
                    "schema": {"id": "vm-provisioning", "version": 1},
                    "fields": {
                        "vm_name": "demo-vm",
                        "guest_la_pw": "super-secret",
                    }
                }
            },
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        redacted = await self.job_service.get_job(job.job_id)
        self.assertIsNotNone(redacted)
        self.assertEqual(
            redacted.parameters["definition"]["fields"]["guest_la_pw"],
            "••••••",
        )

        async with self.job_service._lock:
            stored = self.job_service.jobs[job.job_id]
            self.assertEqual(
                stored.parameters["definition"]["fields"]["guest_la_pw"],
                "super-secret",
            )

    async def test_broadcast_job_event_targets_specific_and_aggregate_topics(self):
        payload = {"example": True}
        await self.job_service._broadcast_job_event("job-topic-1", "status", payload)

        self.assertEqual(len(self.websocket_stub.broadcasts), 2)

        topics = [topic for _, topic in self.websocket_stub.broadcasts]
        self.assertCountEqual(topics, ["jobs:job-topic-1", "jobs"])

        for message, topic in self.websocket_stub.broadcasts:
            self.assertEqual(message["type"], "job")
            self.assertEqual(message["action"], "status")
            self.assertEqual(message["job_id"], "job-topic-1")
            self.assertEqual(message["data"], payload)

    async def test_prepare_job_response_clears_parameters_on_redaction_failure(self):
        job = Job(
            job_id="job-secret-fail",
            job_type="provision_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            parameters={
                "definition": {
                    "schema": {"id": "vm-provisioning", "version": 1},
                    "fields": {"guest_la_pw": "super-secret"},
                }
            },
            output=[],
        )

        with patch(
            "server.app.services.job_service.redact_job_parameters",
            side_effect=RuntimeError("boom"),
        ):
            safe_job = self.job_service._prepare_job_response(job)

        self.assertEqual(safe_job.parameters, {})
        self.assertEqual(
            job.parameters["definition"]["fields"]["guest_la_pw"],
            "super-secret",
        )

