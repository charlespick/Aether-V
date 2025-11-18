"""Schema-driven job submission and execution service."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import PureWindowsPath
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from ..core.config import settings
from ..core.job_schema import redact_job_parameters
from ..core.models import (
    Job,
    JobStatus,
    JobSubmission,
    VMDeleteRequest,
    NotificationLevel,
)
from .host_deployment_service import host_deployment_service
from .host_resources_service import host_resources_service
from .notification_service import notification_service
from .remote_task_service import remote_task_service, RemoteTaskCategory
from .websocket_service import websocket_manager
from .winrm_service import winrm_service
from .inventory_service import inventory_service

logger = logging.getLogger(__name__)


class _PowerShellStreamDecoder:
    """Stateful normaliser for streamed PowerShell output."""

    _CLIXML_PREFIX = "#< CLIXML"
    _CLIXML_END_TAG = "</Objs>"

    def __init__(
        self,
        parse_clixml: Callable[[str], Optional[str]],
        strip_clixml: Callable[[str], str],
        decode_hex: Callable[[str], str],
    ) -> None:
        self._parse_clixml = parse_clixml
        self._strip_clixml = strip_clixml
        self._decode_hex = decode_hex
        self._plain_buffer: str = ""
        self._clixml_buffer: Optional[str] = None

    def push(self, chunk: str) -> List[str]:
        if not chunk:
            return []

        sanitized = (
            chunk.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        )
        if not sanitized:
            return []

        lines: List[str] = []

        if self._clixml_buffer is not None:
            self._clixml_buffer += sanitized
            remaining = ""
        else:
            remaining = sanitized

        while True:
            if self._clixml_buffer is not None:
                closing_index = self._clixml_buffer.find(self._CLIXML_END_TAG)
                if closing_index == -1:
                    break

                end_index = closing_index + len(self._CLIXML_END_TAG)
                payload = self._clixml_buffer[:end_index]
                leftover = self._clixml_buffer[end_index:]

                decoded = self._parse_clixml(payload)
                if decoded is None:
                    decoded = self._strip_clixml(payload)
                if decoded:
                    lines.extend(self._append_plain(decoded))

                self._clixml_buffer = None
                remaining = leftover
                continue

            if not remaining:
                break

            tail_length = max(0, len(self._CLIXML_PREFIX) - 1)
            tail = self._plain_buffer[-tail_length:] if tail_length else ""
            combined = tail + remaining
            combined_index = combined.find(self._CLIXML_PREFIX)
            if combined_index == -1:
                lines.extend(self._append_plain(remaining))
                break

            if combined_index < len(tail):
                sentinel_start_in_plain = (
                    len(self._plain_buffer) - len(tail) + combined_index
                )
                sentinel_plain_part = self._plain_buffer[sentinel_start_in_plain:]
                self._plain_buffer = self._plain_buffer[:sentinel_start_in_plain]
                lines.extend(self._drain_plain_lines())
                self._clixml_buffer = sentinel_plain_part + remaining
                remaining = ""
                continue

            sentinel_index = combined_index - len(tail)
            before = remaining[:sentinel_index]
            if before:
                lines.extend(self._append_plain(before))

            self._clixml_buffer = remaining[sentinel_index:]
            remaining = ""

        return lines

    def finalize(self) -> List[str]:
        lines: List[str] = []

        if self._clixml_buffer:
            decoded = self._parse_clixml(self._clixml_buffer)
            if decoded is None:
                decoded = self._strip_clixml(self._clixml_buffer)
            if decoded:
                lines.extend(self._append_plain(decoded))
            self._clixml_buffer = None

        lines.extend(self._drain_plain_lines(final=True))
        return lines

    def _append_plain(self, text: str) -> List[str]:
        if not text:
            return []
        normalized = self._decode_hex(text)
        self._plain_buffer += normalized
        return self._drain_plain_lines()

    def _drain_plain_lines(self, final: bool = False) -> List[str]:
        lines: List[str] = []
        while True:
            newline_index = self._plain_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._plain_buffer[:newline_index]
            self._plain_buffer = self._plain_buffer[newline_index + 1 :]
            if line.strip():
                lines.append(line)

        if final:
            tail = self._plain_buffer
            self._plain_buffer = ""
            if tail.strip():
                lines.append(tail)

        return lines


class JobService:
    """Service for tracking and executing submitted jobs."""

    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.job_notifications: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._queue: Optional[asyncio.Queue[Optional[str]]] = None
        self._worker_tasks: List[asyncio.Task[None]] = []
        self._started = False
        self._stream_decoders: Dict[Tuple[str, str], _PowerShellStreamDecoder] = {}
        self._host_running: Dict[str, str] = {}
        self._host_waiters: Dict[str, Deque[Tuple[str, asyncio.Event]]] = {}

    def _get_job_runtime_profile(
        self, job_type: str
    ) -> Tuple[RemoteTaskCategory, float]:
        """Return the remote execution category and timeout for a job type."""

        # Long-running jobs that create/modify VMs
        if job_type in {"delete_vm", "create_vm", "managed_deployment", "initialize_vm"}:
            return (
                RemoteTaskCategory.JOB,
                float(settings.job_long_timeout_seconds),
            )

        # Shorter jobs for component creation
        if job_type in {"create_disk", "create_nic", "update_vm", "update_disk", "update_nic", "delete_disk", "delete_nic"}:
            return (
                RemoteTaskCategory.GENERAL,
                float(settings.job_short_timeout_seconds),
            )

        return (
            RemoteTaskCategory.GENERAL,
            float(settings.job_short_timeout_seconds),
        )

    def _prepare_job_response(self, job: Job) -> Job:
        """Return a deep-copied job with sensitive data redacted."""

        job_copy = job.model_copy(deep=True)
        try:
            job_copy.parameters = redact_job_parameters(job_copy.parameters)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to redact job parameters for %s", job.job_id)
            job_copy.parameters = {}
        return job_copy

    async def start(self) -> None:
        """Initialise the job queue worker."""

        if self._started:
            return

        self._queue = asyncio.Queue()
        concurrency = max(1, settings.job_worker_concurrency)
        self._worker_tasks = [
            asyncio.create_task(self._worker()) for _ in range(concurrency)
        ]
        self._started = True
        logger.info(
            "Job service initialised (schema-driven queue, concurrency=%d)", concurrency
        )

    async def stop(self) -> None:
        """Stop the job queue worker."""

        if not self._started:
            return

        assert self._queue is not None
        for _ in range(len(self._worker_tasks) or 1):
            await self._queue.put(None)
        for task in self._worker_tasks:
            try:
                await task
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Job worker terminated with exception")
        self._worker_tasks = []

        self._queue = None
        self._started = False
        logger.info("Job service stopped")

    async def submit_delete_job(self, request: VMDeleteRequest) -> Job:
        """Persist a VM deletion job request for future orchestration."""

        if not self._started or self._queue is None:
            raise RuntimeError("Job service is not running")

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

        await self._sync_job_notification(job)
        await self._broadcast_job_status(job)

        await self._queue.put(job_id)
        logger.info("Queued delete job %s for VM %s", job_id, request.vm_name)
        return self._prepare_job_response(job)

    async def submit_resource_job(
        self,
        job_type: str,
        schema_id: str,
        payload: Dict[str, Any],
        target_host: str,
        parent_job_id: Optional[str] = None,
    ) -> Job:
        """Submit a resource creation/update/delete job."""
        
        if not self._started or self._queue is None:
            raise RuntimeError("Job service is not running")
        
        if not target_host:
            raise RuntimeError(f"{job_type} job requires a target host")
        
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=target_host,
            parameters={
                "definition": payload,
                "schema_id": schema_id,
                **({"parent_job_id": parent_job_id} if parent_job_id else {}),
            },
        )
        
        async with self._lock:
            self.jobs[job_id] = job
        
        await self._sync_job_notification(job)
        await self._broadcast_job_status(job)
        
        await self._queue.put(job_id)
        logger.info(
            "Queued %s job %s for host %s",
            job_type,
            job_id,
            target_host,
        )
        return self._prepare_job_response(job)

    async def get_job(self, job_id: str) -> Optional[Job]:
        """Return a previously submitted job."""

        async with self._lock:
            job = self.jobs.get(job_id)
            return self._prepare_job_response(job) if job else None

    async def get_all_jobs(self) -> List[Job]:
        """Return all tracked jobs."""

        async with self._lock:
            return [self._prepare_job_response(job) for job in self.jobs.values()]

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

        host_key = self._normalise_host(job.target_host)
        acquired_host = False

        try:
            # Acquire host slot for jobs that need serialization
            job_types_needing_serialization = {
                "delete_vm", "create_vm", "create_disk",
                "create_nic", "update_vm", "update_disk",
                "update_nic", "delete_disk", "delete_nic", "initialize_vm"
            }
            if job.job_type in job_types_needing_serialization and host_key:
                await self._acquire_host_slot(host_key, job.job_id)
                acquired_host = True

            await self._update_job(
                job_id, status=JobStatus.RUNNING, started_at=datetime.utcnow()
            )

            try:
                if job.job_type == "delete_vm":
                    await self._execute_delete_job(job)
                elif job.job_type == "create_vm":
                    await self._execute_create_vm_job(job)
                elif job.job_type == "create_disk":
                    await self._execute_create_disk_job(job)
                elif job.job_type == "create_nic":
                    await self._execute_create_nic_job(job)
                elif job.job_type == "update_vm":
                    await self._execute_update_vm_job(job)
                elif job.job_type == "update_disk":
                    await self._execute_update_disk_job(job)
                elif job.job_type == "update_nic":
                    await self._execute_update_nic_job(job)
                elif job.job_type == "delete_disk":
                    await self._execute_delete_disk_job(job)
                elif job.job_type == "delete_nic":
                    await self._execute_delete_nic_job(job)
                elif job.job_type == "managed_deployment":
                    await self._execute_managed_deployment_job(job)
                elif job.job_type == "initialize_vm":
                    await self._execute_initialize_vm_job(job)
                else:
                    raise NotImplementedError(
                        f"Job type '{job.job_type}' is not supported"
                    )
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
        finally:
            if acquired_host:
                await self._release_host_slot(host_key, job.job_id)

    @staticmethod
    def _normalise_host(value: Optional[str]) -> str:
        if not value:
            return ""
        return value.strip().lower()

    async def _acquire_host_slot(self, host: str, job_id: str) -> None:
        """Serialise provisioning jobs so only one runs per host."""

        waiter: Optional[asyncio.Event] = None
        enqueued = False

        try:
            while True:
                async with self._lock:
                    current_owner = self._host_running.get(host)
                    if current_owner is None:
                        self._host_running[host] = job_id
                        return
                    if current_owner == job_id:
                        return

                    if not enqueued:
                        waiter = asyncio.Event()
                        queue = self._host_waiters.setdefault(host, deque())
                        queue.append((job_id, waiter))
                        enqueued = True
                        logger.info(
                            "Job %s waiting for host slot on %s",
                            job_id,
                            host,
                        )

                assert waiter is not None
                await waiter.wait()
                waiter = None
                enqueued = False
        except Exception:
            if enqueued and waiter is not None:
                async with self._lock:
                    pending = self._host_waiters.get(host)
                    if pending:
                        try:
                            pending.remove((job_id, waiter))
                        except ValueError:
                            # It's possible the (job_id, waiter) tuple was already removed from the queue.
                            pass
                        if not pending:
                            self._host_waiters.pop(host, None)
            raise

    async def _release_host_slot(self, host: str, job_id: str) -> None:
        if not host:
            return

        next_waiter: Optional[asyncio.Event] = None
        async with self._lock:
            owner = self._host_running.get(host)
            if owner != job_id:
                return

            queue = self._host_waiters.get(host)
            if queue:
                next_job_id, next_waiter = queue.popleft()
                if not queue:
                    self._host_waiters.pop(host, None)

                self._host_running[host] = next_job_id
                logger.info(
                    "Job %s released host slot on %s; waking job %s",
                    job_id,
                    host,
                    next_job_id,
                )
            else:
                self._host_running.pop(host, None)
                logger.info("Job %s released host slot on %s", job_id, host)

        if next_waiter is not None:
            next_waiter.set()

    async def _execute_delete_job(self, job: Job) -> None:
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Delete job is missing a target host")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for deletion")

        json_payload = await asyncio.to_thread(
            json.dumps,
            job.parameters,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        command = self._build_agent_invocation_command(
            "Invoke-DeleteVmJob.ps1", json_payload
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[Tuple[str, str]]] = asyncio.Queue()

        def publish_chunk(stream: str, chunk: str) -> None:
            asyncio.run_coroutine_threadsafe(queue.put((stream, chunk)), loop)

        def run_command() -> int:
            try:
                return winrm_service.stream_ps_command(
                    target_host, command, publish_chunk
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        category, timeout = self._get_job_runtime_profile(job.job_type)

        command_task = asyncio.create_task(
            remote_task_service.run_blocking(
                target_host,
                run_command,
                description=f"delete job {job.job_id}",
                category=category,
                timeout=timeout,
            )
        )

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                stream_type, payload = item
                await self._handle_stream_chunk(job.job_id, stream_type, payload)
        finally:
            await self._finalize_job_streams(job.job_id, line_callback=line_callback)

        exit_code = await command_task
        if exit_code != 0:
            raise RuntimeError(f"Delete script exited with code {exit_code}")

    async def _execute_create_vm_job(self, job: Job) -> None:
        """Execute a VM-only creation job."""
        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("VM creation job is missing a target host")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for VM creation")

        json_payload = await asyncio.to_thread(
            json.dumps,
            definition,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        command = self._build_agent_invocation_command(
            "Invoke-CreateVmJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"VM creation script exited with code {exit_code}")

    async def _execute_create_disk_job(self, job: Job) -> None:
        """Execute a disk creation and attachment job."""
        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Disk creation job is missing a target host")

        # Validate that VM exists
        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("Disk creation requires vm_id")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for disk creation")

        json_payload = await asyncio.to_thread(
            json.dumps,
            definition,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        command = self._build_agent_invocation_command(
            "Invoke-CreateDiskJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"Disk creation script exited with code {exit_code}")

    async def _execute_create_nic_job(self, job: Job) -> None:
        """Execute a NIC creation and attachment job."""
        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("NIC creation job is missing a target host")

        # Validate that VM exists
        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("NIC creation requires vm_id")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for NIC creation")

        json_payload = await asyncio.to_thread(
            json.dumps,
            definition,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        command = self._build_agent_invocation_command(
            "Invoke-CreateNicJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"NIC creation script exited with code {exit_code}")

    async def _execute_update_vm_job(self, job: Job) -> None:
        """Execute a VM update job."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("VM update job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("VM update requires vm_id")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for VM update")

        json_payload = await asyncio.to_thread(
            json.dumps, definition, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-UpdateVmJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"VM update script exited with code {exit_code}")

    async def _execute_update_disk_job(self, job: Job) -> None:
        """Execute a disk update job."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Disk update job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("Disk update requires vm_id")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for disk update")

        json_payload = await asyncio.to_thread(
            json.dumps, definition, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-UpdateDiskJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"Disk update script exited with code {exit_code}")

    async def _execute_update_nic_job(self, job: Job) -> None:
        """Execute a NIC update job."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("NIC update job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("NIC update requires vm_id")

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for NIC update")

        json_payload = await asyncio.to_thread(
            json.dumps, definition, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-UpdateNicJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"NIC update script exited with code {exit_code}")

    async def _execute_delete_disk_job(self, job: Job) -> None:
        """Execute a disk deletion job."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Disk deletion job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        resource_id = fields.get("resource_id")
        if not vm_id or not resource_id:
            raise RuntimeError("Disk deletion requires vm_id and resource_id")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for disk deletion")

        json_payload = await asyncio.to_thread(
            json.dumps, fields, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-DeleteDiskJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"Disk deletion script exited with code {exit_code}")

    async def _execute_delete_nic_job(self, job: Job) -> None:
        """Execute a NIC deletion job."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("NIC deletion job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        resource_id = fields.get("resource_id")
        if not vm_id or not resource_id:
            raise RuntimeError("NIC deletion requires vm_id and resource_id")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for NIC deletion")

        json_payload = await asyncio.to_thread(
            json.dumps, fields, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-DeleteNicJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"NIC deletion script exited with code {exit_code}")

    async def _execute_initialize_vm_job(self, job: Job) -> None:
        """Execute a VM initialization job that applies guest configuration."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("VM initialization job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("VM initialization requires vm_id")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for initialization")

        json_payload = await asyncio.to_thread(
            json.dumps, fields, ensure_ascii=False, separators=(",", ":")
        )
        command = self._build_agent_invocation_command(
            "Invoke-InitializeVmJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(f"VM initialization script exited with code {exit_code}")

    async def _execute_managed_deployment_job(self, job: Job) -> None:
        """Execute a managed deployment via component sub-jobs instead of direct scripts."""

        from ..core.job_schema import load_schema_by_id

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Managed deployment job is missing a target host")

        fields = definition.get("fields", {})
        schema_info = definition.get("schema", {})
        schema_version = schema_info.get("version", 1)
        component_versions = schema_info.get("components", {})
        vm_schema_version = component_versions.get("vm-create", schema_version)
        disk_schema_version = component_versions.get("disk-create", schema_version)
        nic_schema_version = component_versions.get("nic-create", schema_version)

        await self._append_job_output(
            job.job_id,
            "Managed deployment is orchestrating component jobs. See sub-job list for progress.",
        )

        await self._validate_job_against_host_config(definition, target_host)
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(f"Failed to prepare host {target_host} for deployment")

        vm_schema = load_schema_by_id("vm-create")
        disk_schema = load_schema_by_id("disk-create")
        nic_schema = load_schema_by_id("nic-create")

        vm_hardware_fields: Dict[str, Any] = {}
        vm_guest_config_fields: Dict[str, Any] = {}
        for field in vm_schema.get("fields", []):
            field_id = field.get("id")
            if field_id in fields:
                if field.get("guest_config", False):
                    vm_guest_config_fields[field_id] = fields[field_id]
                else:
                    vm_hardware_fields[field_id] = fields[field_id]

        nic_hardware_fields: Dict[str, Any] = {}
        nic_guest_config_fields: Dict[str, Any] = {}
        for field in nic_schema.get("fields", []):
            field_id = field.get("id")
            if field_id in fields:
                if field.get("guest_config", False):
                    nic_guest_config_fields[field_id] = fields[field_id]
                elif field_id != "vm_id":
                    nic_hardware_fields[field_id] = fields[field_id]

        vm_definition = {
            "schema": {"id": "vm-create", "version": vm_schema_version},
            "fields": vm_hardware_fields,
        }

        vm_job = await self._queue_child_job(
            job,
            job_type="create_vm",
            schema_id="vm-create",
            payload=vm_definition,
        )
        vm_job_result = await self._wait_for_child_job_completion(job.job_id, vm_job.job_id)
        if vm_job_result.status != JobStatus.COMPLETED:
            raise RuntimeError(
                f"VM creation job {vm_job.job_id} failed: {vm_job_result.error or 'unknown error'}"
            )

        vm_id = self._extract_vm_id_from_output(vm_job_result.output)
        if not vm_id:
            raise RuntimeError("Unable to parse VM ID from VM creation output")

        job.parameters["vm_id"] = vm_id
        await self._update_job(job.job_id, parameters=job.parameters)

        vm_name = vm_hardware_fields.get("vm_name")

        disk_fields: Dict[str, Any] = {}
        for field in disk_schema.get("fields", []):
            field_id = field.get("id")
            if field_id == "vm_id":
                continue
            if field_id in fields:
                disk_fields[field_id] = fields[field_id]

        if disk_fields.get("disk_size_gb") is not None:
            disk_fields["vm_id"] = vm_id

            disk_definition = {
                "schema": {"id": "disk-create", "version": disk_schema_version},
                "fields": disk_fields,
            }

            disk_job = await self._queue_child_job(
                job,
                job_type="create_disk",
                schema_id="disk-create",
                payload=disk_definition,
            )
            disk_job_result = await self._wait_for_child_job_completion(
                job.job_id, disk_job.job_id
            )
            if disk_job_result.status != JobStatus.COMPLETED:
                raise RuntimeError(
                    f"Disk creation job {disk_job.job_id} failed: {disk_job_result.error or 'unknown error'}"
                )

        if nic_hardware_fields.get("network"):
            nic_hardware_fields["vm_id"] = vm_id

            nic_definition = {
                "schema": {"id": "nic-create", "version": nic_schema_version},
                "fields": nic_hardware_fields,
            }

            nic_job = await self._queue_child_job(
                job,
                job_type="create_nic",
                schema_id="nic-create",
                payload=nic_definition,
            )
            nic_job_result = await self._wait_for_child_job_completion(
                job.job_id, nic_job.job_id
            )
            if nic_job_result.status != JobStatus.COMPLETED:
                raise RuntimeError(
                    f"NIC creation job {nic_job.job_id} failed: {nic_job_result.error or 'unknown error'}"
                )

        all_guest_config_fields = {**vm_guest_config_fields, **nic_guest_config_fields}
        if all_guest_config_fields:
            init_fields = {
                "vm_id": vm_id,
                "vm_name": vm_name,
                **all_guest_config_fields,
            }

            init_job_definition = {
                "schema": {"id": "initialize-vm", "version": vm_schema_version},
                "fields": init_fields,
            }

            init_job = await self._queue_child_job(
                job,
                job_type="initialize_vm",
                schema_id="initialize-vm",
                payload=init_job_definition,
            )
            init_job_result = await self._wait_for_child_job_completion(
                job.job_id, init_job.job_id
            )
            if init_job_result.status != JobStatus.COMPLETED:
                raise RuntimeError(
                    f"VM initialization job {init_job.job_id} failed: {init_job_result.error or 'unknown error'}"
                )

        await self._append_job_output(
            job.job_id,
            f"Managed deployment complete. VM '{vm_name or vm_id}' fully deployed on {target_host}.",
        )

    async def _queue_child_job(
        self,
        parent_job: Job,
        job_type: str,
        schema_id: str,
        payload: Dict[str, Any],
    ) -> Job:
        """Queue a component job and track it against the parent deployment job."""

        child_job = await self.submit_resource_job(
            job_type=job_type,
            schema_id=schema_id,
            payload=payload,
            target_host=parent_job.target_host or "",
            parent_job_id=parent_job.job_id,
        )

        await self._update_child_job_summary(parent_job.job_id, child_job.job_id)
        return child_job

    async def _wait_for_child_job_completion(
        self, parent_job_id: str, child_job_id: str
    ) -> Job:
        """Poll for child job completion while syncing status to the parent job."""

        last_status: Optional[JobStatus] = None
        while True:
            async with self._lock:
                child_job = self.jobs.get(child_job_id)

            if not child_job:
                raise RuntimeError(f"Child job {child_job_id} not found")

            if child_job.status != last_status:
                await self._update_child_job_summary(parent_job_id, child_job_id)
                last_status = child_job.status

            if child_job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                await self._update_child_job_summary(parent_job_id, child_job_id)
                return self._prepare_job_response(child_job)

            await asyncio.sleep(1)

    async def _update_child_job_summary(
        self, parent_job_id: str, child_job_id: str
    ) -> None:
        """Update the parent job's child job list with the latest child status."""

        async with self._lock:
            parent_job = self.jobs.get(parent_job_id)
            child_job = self.jobs.get(child_job_id)
            existing_children = list(parent_job.child_jobs) if parent_job else []

        if not parent_job or not child_job:
            return

        summary = self._build_child_job_summary(child_job)
        updated_children = self._merge_child_job_list(existing_children, summary)
        await self._update_job(parent_job_id, child_jobs=updated_children)

    def _build_child_job_summary(self, child_job: Job) -> Dict[str, Any]:
        """Build a lightweight summary for UI consumption."""

        status_value = (
            child_job.status.value if isinstance(child_job.status, JobStatus) else child_job.status
        )
        return {
            "job_id": child_job.job_id,
            "job_type": child_job.job_type,
            "job_type_label": self._job_type_label(child_job),
            "status": status_value,
            "created_at": child_job.created_at,
            "started_at": child_job.started_at,
            "completed_at": child_job.completed_at,
            "target_host": child_job.target_host,
            "error": child_job.error,
            "vm_name": self._extract_vm_name(child_job),
        }

    @staticmethod
    def _merge_child_job_list(
        existing_children: List[Dict[str, Any]], new_child: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        replaced = False
        for child in existing_children:
            if child.get("job_id") == new_child.get("job_id"):
                merged.append(new_child)
                replaced = True
            else:
                merged.append(child)
        if not replaced:
            merged.append(new_child)
        return merged

    def _extract_vm_id_from_output(self, lines: List[str]) -> Optional[str]:
        """Parse a VM ID from the output of a child VM creation job."""

        for line in lines:
            parsed: Optional[Dict[str, Any]] = None
            try:
                candidate = line[line.index("{") : line.rindex("}") + 1]
                parsed = json.loads(candidate)
            except (ValueError, json.JSONDecodeError):
                try:
                    parsed = json.loads(line)
                except Exception:
                    parsed = None

            if isinstance(parsed, dict):
                for key in ("vm_id", "vmId", "id", "Id", "ID"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

                nested_vm = parsed.get("vm")
                if isinstance(nested_vm, dict):
                    for key in ("id", "vm_id", "vmId", "Id", "ID"):
                        value = nested_vm.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()

            id_match = re.search(r"vm[_\s-]?id\s*[:=]\s*([^\s]+)", line, flags=re.IGNORECASE)
            if id_match:
                return id_match.group(1).strip()

        return None

    async def _execute_agent_command(
        self,
        job: Job,
        target_host: str,
        command: str,
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> int:
        """Helper to execute an agent command with streaming output."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[Tuple[str, str]]] = asyncio.Queue()

        def publish_chunk(stream: str, chunk: str) -> None:
            asyncio.run_coroutine_threadsafe(queue.put((stream, chunk)), loop)

        def run_command() -> int:
            try:
                return winrm_service.stream_ps_command(
                    target_host, command, publish_chunk
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        category, timeout = self._get_job_runtime_profile(job.job_type)

        command_task = asyncio.create_task(
            remote_task_service.run_blocking(
                target_host,
                run_command,
                description=f"{job.job_type} job {job.job_id}",
                category=category,
                timeout=timeout,
            )
        )

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                stream_type, payload = item
                await self._handle_stream_chunk(
                    job.job_id, stream_type, payload, line_callback=line_callback
                )
        finally:
            await self._finalize_job_streams(job.job_id, line_callback=line_callback)

        return await command_task

    async def _handle_stream_chunk(
        self,
        job_id: str,
        stream: str,
        payload: str,
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        if not payload:
            return

        decoder = self._stream_decoders.get((job_id, stream.lower()))
        if decoder is None:
            decoder = _PowerShellStreamDecoder(
                parse_clixml=self._parse_clixml_payload,
                strip_clixml=self._strip_clixml_markup,
                decode_hex=self._decode_hex_escapes,
            )
            self._stream_decoders[(job_id, stream.lower())] = decoder

        lines = decoder.push(payload)
        if not lines:
            return

        formatted_lines: List[str] = []
        for line in lines:
            if stream.lower() == "stdout" and line_callback:
                try:
                    line_callback(line)
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception("line_callback failed for job %s", job_id)

            if stream.lower() == "stderr":
                line = f"STDERR: {line}"

            formatted_lines.append(line)

        await self._append_job_output(job_id, *formatted_lines)

    async def _finalize_job_streams(
        self,
        job_id: str,
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        pending_keys = [key for key in self._stream_decoders if key[0] == job_id]
        for key in pending_keys:
            decoder = self._stream_decoders.pop(key)
            trailing = decoder.finalize()
            if not trailing:
                continue
            formatted_lines: List[str] = []
            for line in trailing:
                if key[1] == "stdout" and line_callback:
                    try:
                        line_callback(line)
                    except Exception:  # pragma: no cover - defensive logging
                        logger.exception("line_callback failed for job %s", job_id)

                if key[1] == "stderr":
                    line = f"STDERR: {line}"

                formatted_lines.append(line)

            await self._append_job_output(job_id, *formatted_lines)

    _CLIXML_PREFIX = "#< CLIXML"
    _CLIXML_TEXT_TAGS = {"S", "AV"}
    _HEX_ESCAPE_PATTERN = re.compile(r"_x([0-9A-Fa-f]{4})_")

    def _parse_clixml_payload(self, payload: str) -> Optional[str]:
        """Attempt to decode PowerShell CLI XML output into plain text."""

        trimmed = payload.lstrip()
        if trimmed.startswith(self._CLIXML_PREFIX):
            trimmed = trimmed[len(self._CLIXML_PREFIX) :].lstrip()

        xml_start = trimmed.find("<Objs")
        if xml_start == -1:
            return None

        xml_data = trimmed[xml_start:]
        try:
            root = ElementTree.fromstring(xml_data)
        except ElementTree.ParseError:
            return None

        fragments: List[str] = []
        for element in root.iter():
            tag = element.tag.split("}")[-1]
            if tag in self._CLIXML_TEXT_TAGS and element.text:
                fragments.append(element.text)

        if not fragments:
            return None

        text = "\n".join(fragments)
        return self._decode_hex_escapes(text)

    def _strip_clixml_markup(self, payload: str) -> str:
        """Best-effort fallback for CLI XML payloads that cannot be parsed."""

        trimmed = payload
        xml_start = trimmed.find("<Objs")
        if xml_start != -1:
            trimmed = trimmed[xml_start:]

        stripped = re.sub(r"<[^>]+>", "", trimmed)
        return self._decode_hex_escapes(stripped)

    def _decode_hex_escapes(self, value: str) -> str:
        """Convert PowerShell _xHHHH_ sequences to their character equivalents."""

        def repl(match: re.Match[str]) -> str:
            try:
                return chr(int(match.group(1), 16))
            except ValueError:
                return match.group(0)

        return self._HEX_ESCAPE_PATTERN.sub(repl, value)

    async def _after_job_update(
        self,
        job: Job,
        previous_status: JobStatus,
        changes: Dict[str, Any],
    ) -> None:
        status_changed = "status" in changes and job.status != previous_status
        if status_changed:
            await self._sync_job_notification(job)

            if job.job_type == "delete_vm":
                vm_name = self._extract_vm_name(job)
                target_host = (job.target_host or "").strip()
                if vm_name and target_host:
                    if job.status == JobStatus.RUNNING:
                        inventory_service.mark_vm_deleting(
                            job.job_id, vm_name, target_host
                        )
                    elif job.status == JobStatus.COMPLETED:
                        inventory_service.finalize_vm_deletion(
                            job.job_id, vm_name, target_host, success=True
                        )
                    elif job.status == JobStatus.FAILED:
                        inventory_service.finalize_vm_deletion(
                            job.job_id, vm_name, target_host, success=False
                        )

        await self._broadcast_job_status(job)

    async def _sync_job_notification(self, job: Job) -> None:
        vm_name = self._extract_vm_name(job)
        job_label = self._job_type_label(job)
        target_label = f'"{vm_name}"' if vm_name else job.job_id
        host_phrase = (
            f"host {job.target_host}" if job.target_host else "an unspecified host"
        )

        if job.status == JobStatus.PENDING:
            title = f"{job_label} queued"
            message = (
                f"{job_label} request for {target_label} queued for {host_phrase}."
            )
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
                "job_id": job.job_id,
                "status": job.status.value,
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
        prepared = self._prepare_job_response(job)
        payload = prepared.model_dump(mode="json")
        await self._broadcast_job_event(prepared.job_id, "status", payload)

    async def _broadcast_job_output(self, job_id: str, lines: List[str]) -> None:
        if not lines:
            return
        await self._broadcast_job_event(job_id, "output", {"lines": lines})

    async def _broadcast_job_event(
        self, job_id: str, action: str, data: Dict[str, Any]
    ) -> None:
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
        if job.job_type == "delete_vm":
            return "Delete VM"
        if job.job_type == "create_vm":
            return "Create VM"
        if job.job_type == "create_disk":
            return "Create Disk"
        if job.job_type == "create_nic":
            return "Create Network Adapter"
        if job.job_type == "managed_deployment":
            return "Deploy VM"
        if job.job_type == "update_vm":
            return "Update VM"
        if job.job_type == "update_disk":
            return "Update Disk"
        if job.job_type == "update_nic":
            return "Update Network Adapter"
        if job.job_type == "delete_disk":
            return "Delete Disk"
        if job.job_type == "delete_nic":
            return "Delete Network Adapter"
        if job.job_type == "initialize_vm":
            return "Initialize VM"
        return job.job_type.replace("_", " ").title()

    def _extract_vm_name(self, job: Job) -> Optional[str]:
        if job.job_type == "delete_vm":
            value = job.parameters.get("vm_name")
            if isinstance(value, str):
                value = value.strip()
                if value:
                    return value

        definition = job.parameters.get("definition") or {}
        fields = definition.get("fields") or {}
        value = fields.get("vm_name")
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        return None

    def _build_agent_invocation_command(self, script_name: str, payload: str) -> str:
        payload_bytes = payload.encode("utf-8")
        encoded = base64.b64encode(payload_bytes).decode("ascii")
        script_path = (
            PureWindowsPath(settings.host_install_directory)
            / script_name
        )
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

        prepared = self._prepare_job_response(job_copy)
        await self._after_job_update(prepared, previous_status, changes)
        return prepared

    async def _append_job_output(
        self, job_id: str, *messages: Optional[str]
    ) -> List[str]:
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

    async def get_metrics(self) -> Dict[str, Any]:
        """Return diagnostic information about the job service."""

        queue_depth = self._queue.qsize() if self._queue else 0
        async with self._lock:
            jobs_snapshot = list(self.jobs.values())

        status_counts = {
            JobStatus.PENDING: 0,
            JobStatus.RUNNING: 0,
            JobStatus.COMPLETED: 0,
            JobStatus.FAILED: 0,
        }
        for job in jobs_snapshot:
            status_counts[job.status] = status_counts.get(job.status, 0) + 1

        return {
            "started": self._started,
            "queue_depth": queue_depth,
            "worker_count": len(self._worker_tasks),
            "configured_concurrency": max(1, settings.job_worker_concurrency),
            "pending_jobs": status_counts.get(JobStatus.PENDING, 0),
            "running_jobs": status_counts.get(JobStatus.RUNNING, 0),
            "completed_jobs": status_counts.get(JobStatus.COMPLETED, 0),
            "failed_jobs": status_counts.get(JobStatus.FAILED, 0),
            "total_tracked_jobs": len(jobs_snapshot),
        }

    async def _validate_job_against_host_config(
        self,
        payload: Dict[str, Any],
        target_host: str,
    ) -> None:
        """Validate job payload against host resources configuration.
        
        Args:
            payload: Job payload containing field definitions
            target_host: Target host FQDN or hostname
            
        Raises:
            ValueError: If validation fails
        """
        # Load host configuration
        host_config = await host_resources_service.get_host_configuration(target_host)
        if not host_config:
            # Host resources configuration is mandatory for provisioning
            raise ValueError(
                f"Host resources configuration not found on {target_host}. "
                f"Ensure C:\\ProgramData\\Aether-V\\hostresources.json or hostresources.yaml exists and is valid."
            )

        fields = payload.get("fields", {})
        if not isinstance(fields, dict):
            return

        # Validate network name if provided
        network_name = fields.get("network")
        if network_name:
            if not host_resources_service.validate_network_name(network_name, host_config):
                available = host_resources_service.get_available_networks(host_config)
                raise ValueError(
                    f"Network '{network_name}' not found on host {target_host}. "
                    f"Available networks: {', '.join(available) if available else 'none'}"
                )

        # Validate storage class if provided
        storage_class = fields.get("storage_class")
        if storage_class:
            if not host_resources_service.validate_storage_class(storage_class, host_config):
                available = host_resources_service.get_available_storage_classes(host_config)
                raise ValueError(
                    f"Storage class '{storage_class}' not found on host {target_host}. "
                    f"Available storage classes: {', '.join(available) if available else 'none'}"
                )


default_job_service = JobService()
job_service = default_job_service
