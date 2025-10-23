"""Schema-driven job submission and execution service."""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from datetime import datetime
from functools import partial
from pathlib import PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..core.config import settings
from ..core.models import Job, JobStatus, JobSubmission, VMDeleteRequest, NotificationLevel
from .host_deployment_service import host_deployment_service
from .notification_service import notification_service
from .websocket_service import websocket_manager
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


class JobService:
    """Service for tracking and executing submitted jobs."""

    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.job_notifications: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._queue: Optional[asyncio.Queue[Optional[str]]] = None
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._started = False

    async def start(self) -> None:
        """Initialise the job queue worker."""

        if self._started:
            return

        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker())
        self._started = True
        logger.info("Job service initialised (schema-driven queue)")

    async def stop(self) -> None:
        """Stop the job queue worker."""

        if not self._started:
            return

        assert self._queue is not None
        await self._queue.put(None)
        if self._worker_task is not None:
            try:
                await self._worker_task
            finally:
                self._worker_task = None

        self._queue = None
        self._started = False
        logger.info("Job service stopped")

    async def submit_provisioning_job(
        self, submission: JobSubmission, payload: Dict[str, Any], target_host: Optional[str]
    ) -> Job:
        """Persist and enqueue a provisioning job."""

        if not self._started or self._queue is None:
            raise RuntimeError("Job service is not running")

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="provision_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=target_host,
            parameters={
                "schema_version": submission.schema_version,
                "definition": payload,
            },
        )

        async with self._lock:
            self.jobs[job_id] = job

        await self._sync_job_notification(job)
        await self._broadcast_job_status(job.model_copy(deep=True))

        await self._queue.put(job_id)
        logger.info("Queued provisioning job %s for host %s", job_id, target_host or "<unspecified>")
        return job.model_copy(deep=True)

    async def submit_delete_job(self, request: VMDeleteRequest) -> Job:
        """Persist a VM deletion job request for future orchestration."""

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="delete_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=request.hyperv_host,
            parameters=request.model_dump(),
        )

        async with self._lock:
            self.jobs[job_id] = job

        logger.info("Queued delete job %s for VM %s", job_id, request.vm_name)
        return job.model_copy(deep=True)

    async def get_job(self, job_id: str) -> Optional[Job]:
        """Return a previously submitted job."""

        async with self._lock:
            job = self.jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def get_all_jobs(self) -> List[Job]:
        """Return all tracked jobs."""

        async with self._lock:
            return [job.model_copy(deep=True) for job in self.jobs.values()]

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            if job_id is None:
                self._queue.task_done()
                break

            try:
                await self._process_job(job_id)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Unhandled exception while processing job %s", job_id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        async with self._lock:
            job = self.jobs.get(job_id)
        if not job:
            logger.warning("Received unknown job id %s", job_id)
            return

        await self._update_job(job_id, status=JobStatus.RUNNING, started_at=datetime.utcnow())

        try:
            if job.job_type == "provision_vm":
                await self._execute_provisioning_job(job)
            else:
                raise NotImplementedError(f"Job type '{job.job_type}' is not supported")
        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc)
            await self._append_job_output(job_id, f"ERROR: {exc}")
            await self._update_job(
                job_id,
                status=JobStatus.FAILED,
                completed_at=datetime.utcnow(),
                error=str(exc),
            )
            return

        await self._update_job(
            job_id,
            status=JobStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )

    async def _execute_provisioning_job(self, job: Job) -> None:
        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Provisioning job is missing a target host")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for provisioning")

        yaml_payload = await asyncio.to_thread(yaml.safe_dump, definition, sort_keys=False)
        command = self._build_master_invocation_command(yaml_payload)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[Tuple[str, str]]] = asyncio.Queue()

        def publish_chunk(stream: str, chunk: str) -> None:
            asyncio.run_coroutine_threadsafe(queue.put((stream, chunk)), loop)

        def run_command() -> int:
            try:
                return winrm_service.stream_ps_command(target_host, command, publish_chunk)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        command_future = loop.run_in_executor(None, run_command)

        while True:
            item = await queue.get()
            if item is None:
                break
            stream_type, payload = item
            await self._handle_stream_chunk(job.job_id, stream_type, payload)

        exit_code = await command_future
        if exit_code != 0:
            raise RuntimeError(f"Provisioning script exited with code {exit_code}")

    async def _handle_stream_chunk(self, job_id: str, stream: str, payload: str) -> None:
        if not payload:
            return

        normalized = payload.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line for line in normalized.split("\n") if line]
        if not lines:
            return

        if stream.lower() == "stderr":
            lines = [f"STDERR: {line}" for line in lines]

        await self._append_job_output(job_id, *lines)

    async def _after_job_update(
        self,
        job: Job,
        previous_status: JobStatus,
        changes: Dict[str, Any],
    ) -> None:
        status_changed = "status" in changes and job.status != previous_status
        if status_changed:
            await self._sync_job_notification(job)

        await self._broadcast_job_status(job)

    async def _sync_job_notification(self, job: Job) -> None:
        vm_name = self._extract_vm_name(job)
        job_label = self._job_type_label(job)
        target_label = f'"{vm_name}"' if vm_name else job.job_id
        host_phrase = f"host {job.target_host}" if job.target_host else "an unspecified host"

        if job.status == JobStatus.PENDING:
            title = f"{job_label} queued"
            message = f"{job_label} request for {target_label} queued for {host_phrase}."
            level = NotificationLevel.INFO
        elif job.status == JobStatus.RUNNING:
            title = f"{job_label} running"
            message = f"{job_label} for {target_label} is running on {host_phrase}."
            level = NotificationLevel.INFO
        elif job.status == JobStatus.COMPLETED:
            title = f"{job_label} completed"
            message = f"{job_label} for {target_label} completed successfully on {host_phrase}."
            level = NotificationLevel.SUCCESS
        elif job.status == JobStatus.FAILED:
            title = f"{job_label} failed"
            detail = f" Details: {job.error}" if job.error else ""
            message = f"{job_label} for {target_label} failed on {host_phrase}.{detail}"
            level = NotificationLevel.ERROR
        else:
            title = f"{job_label} update"
            message = f"{job_label} for {target_label} updated."
            level = NotificationLevel.INFO

        notification = notification_service.upsert_job_notification(
            job.job_id,
            title=title,
            message=message,
            level=level,
            status=job.status,
            metadata={
                "job_type": job.job_type,
                "vm_name": vm_name,
                "target_host": job.target_host,
            },
        )

        if notification:
            async with self._lock:
                stored = self.jobs.get(job.job_id)
                if stored:
                    stored.notification_id = notification.id
                self.job_notifications[job.job_id] = notification.id
            job.notification_id = notification.id

    async def _broadcast_job_status(self, job: Job) -> None:
        payload = job.model_dump(mode="json")
        await self._broadcast_job_event(job.job_id, "status", payload)

    async def _broadcast_job_output(self, job_id: str, lines: List[str]) -> None:
        if not lines:
            return
        await self._broadcast_job_event(job_id, "output", {"lines": lines})

    async def _broadcast_job_event(self, job_id: str, action: str, data: Dict[str, Any]) -> None:
        message = {"type": "job", "action": action, "job_id": job_id, "data": data}
        try:
            await websocket_manager.broadcast(message, topic=f"jobs:{job_id}")
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to broadcast job event for %s", job_id)

        try:
            await websocket_manager.broadcast(message, topic="jobs")
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to broadcast aggregate job event for %s", job_id)

    def _job_type_label(self, job: Job) -> str:
        if job.job_type == "provision_vm":
            return "Create VM"
        if job.job_type == "delete_vm":
            return "Delete VM"
        return job.job_type.replace("_", " ").title()

    def _extract_vm_name(self, job: Job) -> Optional[str]:
        definition = job.parameters.get("definition") or {}
        fields = definition.get("fields") or {}
        value = fields.get("vm_name")
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        return None

    def _build_master_invocation_command(self, yaml_payload: str) -> str:
        payload_bytes = yaml_payload.encode("utf-8")
        encoded = base64.b64encode(payload_bytes).decode("ascii")
        script_path = PureWindowsPath(settings.host_install_directory) / "Invoke-ProvisioningJob.ps1"
        script_literal = self._ps_literal(str(script_path))
        return (
            "$ErrorActionPreference = 'Stop'; "
            f"$scriptPath = {script_literal}; "
            f"$payload = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded}')); "
            "$payload | & $scriptPath"
        )

    @staticmethod
    def _ps_literal(value: str) -> str:
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    async def _update_job(self, job_id: str, **changes: Any) -> Optional[Job]:
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            previous_status = job.status
            for field, value in changes.items():
                setattr(job, field, value)
            job_copy = job.model_copy(deep=True)

        await self._after_job_update(job_copy, previous_status, changes)
        return job_copy

    async def _append_job_output(self, job_id: str, *messages: Optional[str]) -> List[str]:
        lines: List[str] = []
        for message in messages:
            if not message:
                continue
            normalized = message.replace("\r\n", "\n").replace("\r", "\n")
            for line in normalized.split("\n"):
                if line:
                    lines.append(line)

        if not lines:
            return []

        async with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job.output.extend(lines)

        await self._broadcast_job_output(job_id, lines)
        return lines


default_job_service = JobService()
job_service = default_job_service
