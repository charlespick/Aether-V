import asyncio
import sys
import types
import uuid
from datetime import datetime
from typing import List, Tuple
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import patch


yaml_stub = types.ModuleType("yaml")
yaml_stub.safe_dump = lambda data, sort_keys=False: ""
yaml_stub.safe_load = lambda stream: {
    "version": 1,
    "fields": [
        {"id": "vm_name", "type": "string"},
        {"id": "admin_password", "type": "secret"},
        {"id": "guest_la_pw", "secret": True},
    ],
}
sys.modules.setdefault("yaml", yaml_stub)

try:
    import server.app.services.job_service as job_service_module
    from server.app.core.models import (
        Job,
        JobStatus,
        Notification,
        NotificationCategory,
        NotificationLevel,
        JobSubmission,
        VMDeleteRequest,
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
        self.inventory_stub = self._build_inventory_stub()

        self.original_notification_service = job_service_module.notification_service
        self.original_websocket_manager = job_service_module.websocket_manager
        self.original_inventory_service = job_service_module.inventory_service

        job_service_module.notification_service = self.notification_stub
        job_service_module.websocket_manager = self.websocket_stub
        job_service_module.inventory_service = self.inventory_stub

    async def asyncTearDown(self):
        await self.job_service.stop()
        job_service_module.notification_service = self.original_notification_service
        job_service_module.websocket_manager = self.original_websocket_manager
        job_service_module.inventory_service = self.original_inventory_service

    @staticmethod
    def _build_inventory_stub():
        class _InventoryStub:
            def __init__(self):
                self.tracked: List[Tuple[str, str, str]] = []
                self.cleared: List[str] = []
                self.deleting: List[Tuple[str, str, str]] = []
                self.finalised: List[Tuple[str, str, str, bool]] = []

            def track_job_vm(self, job_id: str, vm_name: str, host: str) -> None:
                self.tracked.append((job_id, vm_name, host))

            def clear_job_vm(self, job_id: str) -> None:
                self.cleared.append(job_id)

            def mark_vm_deleting(self, job_id: str, vm_name: str, host: str) -> None:
                self.deleting.append((job_id, vm_name, host))

            def finalize_vm_deletion(
                self, job_id: str, vm_name: str, host: str, success: bool
            ) -> None:
                self.finalised.append((job_id, vm_name, host, success))

        return _InventoryStub()

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

    async def test_submit_delete_job_enqueues_job(self):
        await self.job_service.start()

        original_process = self.job_service._process_job
        processed: List[str] = []

        async def fake_process(job_id: str) -> None:
            processed.append(job_id)

        self.job_service._process_job = fake_process  # type: ignore[assignment]

        request = VMDeleteRequest(vm_name="vm-to-remove", hyperv_host="hyperv01", force=False)
        try:
            job = await self.job_service.submit_delete_job(request)
            await asyncio.wait_for(asyncio.sleep(0), timeout=1)

            self.assertIn(job.job_id, processed)
            async with self.job_service._lock:
                stored = self.job_service.jobs[job.job_id]
                self.assertEqual(stored.job_type, "delete_vm")
                self.assertEqual(stored.target_host, "hyperv01")
        finally:
            self.job_service._process_job = original_process

    async def test_after_job_update_tracks_vm_deletion_lifecycle(self):
        job = Job(
            job_id="job-delete-1",
            job_type="delete_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host="hyperv01",
            parameters={"vm_name": "app-server"},
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        await self.job_service._update_job(
            job.job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        self.assertIn((job.job_id, "app-server", "hyperv01"), self.inventory_stub.deleting)

        await self.job_service._update_job(
            job.job_id,
            status=JobStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )
        self.assertIn((job.job_id, "app-server", "hyperv01", True), self.inventory_stub.finalised)

    async def test_after_job_update_restores_inventory_on_failed_delete(self):
        job = Job(
            job_id="job-delete-2",
            job_type="delete_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host="hyperv02",
            parameters={"vm_name": "db-server"},
            output=[],
        )

        async with self.job_service._lock:
            self.job_service.jobs[job.job_id] = job

        await self.job_service._update_job(
            job.job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        await self.job_service._update_job(
            job.job_id,
            status=JobStatus.FAILED,
            error="boom",
            completed_at=datetime.utcnow(),
        )

        self.assertIn((job.job_id, "db-server", "hyperv02", False), self.inventory_stub.finalised)

    async def test_only_one_provisioning_job_runs_per_host(self):
        await self.job_service.start()

        original_execute = self.job_service._execute_provisioning_job

        first_job_started = asyncio.Event()
        second_job_started = asyncio.Event()
        release_first_job = asyncio.Event()
        start_order: List[str] = []

        async def fake_execute(job):
            start_order.append(job.job_id)
            if not first_job_started.is_set():
                first_job_started.set()
                await release_first_job.wait()
            else:
                second_job_started.set()

        self.job_service._execute_provisioning_job = fake_execute  # type: ignore[assignment]

        submission = JobSubmission(schema_version=1, values={})
        payload = {
            "schema": {"id": "vm-provisioning", "version": 1},
            "fields": {"vm_name": "vm-a"},
        }

        job1 = await self.job_service.submit_provisioning_job(
            submission, payload, "hyperv01"
        )

        payload2 = {
            "schema": {"id": "vm-provisioning", "version": 1},
            "fields": {"vm_name": "vm-b"},
        }

        job2 = await self.job_service.submit_provisioning_job(
            submission, payload2, "HYPERV01"
        )

        try:
            await asyncio.wait_for(first_job_started.wait(), timeout=1)
            self.assertEqual(start_order, [job1.job_id])

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(second_job_started.wait(), timeout=0.2)

            release_first_job.set()

            await asyncio.wait_for(second_job_started.wait(), timeout=1)
            self.assertEqual(start_order, [job1.job_id, job2.job_id])
        finally:
            self.job_service._execute_provisioning_job = original_execute

    async def test_only_one_delete_job_runs_per_host(self):
        await self.job_service.start()

        original_execute = self.job_service._execute_delete_job

        first_job_started = asyncio.Event()
        second_job_started = asyncio.Event()
        release_first_job = asyncio.Event()
        start_order: List[str] = []

        async def fake_execute(job):
            start_order.append(job.job_id)
            if not first_job_started.is_set():
                first_job_started.set()
                await release_first_job.wait()
            else:
                second_job_started.set()

        self.job_service._execute_delete_job = fake_execute  # type: ignore[assignment]

        request1 = VMDeleteRequest(vm_name="vm-alpha", hyperv_host="hyperv01", force=False)
        request2 = VMDeleteRequest(vm_name="vm-beta", hyperv_host="HYPERV01", force=False)

        try:
            job1 = await self.job_service.submit_delete_job(request1)
            job2 = await self.job_service.submit_delete_job(request2)

            await asyncio.wait_for(first_job_started.wait(), timeout=1)
            self.assertEqual(start_order, [job1.job_id])

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(second_job_started.wait(), timeout=0.2)

            release_first_job.set()

            await asyncio.wait_for(second_job_started.wait(), timeout=1)
            self.assertEqual(start_order, [job1.job_id, job2.job_id])
        finally:
            self.job_service._execute_delete_job = original_execute

