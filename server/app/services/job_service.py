"""Schema-driven job submission and execution service."""

from __future__ import annotations

import asyncio
import base64
import copy
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
from ..core.models import Job, JobStatus, VMDeleteRequest, NotificationLevel
from ..core.job_envelope import create_job_request, parse_job_result
from ..core.pydantic_models import (
    ManagedDeploymentRequest,
    JobRequest,
    JobResultEnvelope,
    JobResultStatus,
)
from ..core.guest_config_generator import generate_guest_config
from .host_deployment_service import host_deployment_service
from .host_resources_service import host_resources_service
from .notification_service import notification_service
from .remote_task_service import remote_task_service, RemoteTaskCategory
from .websocket_service import websocket_manager
from .winrm_service import winrm_service
from .inventory_service import inventory_service

logger = logging.getLogger(__name__)

# Job type constants for categorization
LONG_RUNNING_JOB_TYPES = {
    "delete_vm", "create_vm", "managed_deployment_v2", "initialize_vm"
}

SERIALIZED_JOB_TYPES = {
    "delete_vm", "create_vm", "create_disk",
    "create_nic", "update_vm", "update_disk",
    "update_nic", "delete_disk", "delete_nic", "initialize_vm",
    "managed_deployment_v2"
}


def _redact_sensitive_parameters(
    parameters: Optional[Dict[str, Any]],
    replacement: str = "••••••",
) -> Dict[str, Any]:
    """Return a copy of job parameters with sensitive values redacted.
    
    This replaces the schema-based redaction with a simple list of known
    sensitive field names.
    """
    if parameters is None:
        return {}
    
    # Known sensitive field names from Pydantic models
    sensitive_fields = {
        "guest_la_pw",
        "guest_domain_joinpw",
        "cnf_ansible_ssh_key",
    }
    
    sanitized = copy.deepcopy(parameters)
    
    def _redact(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in sensitive_fields and item is not None:
                    value[key] = replacement
                else:
                    _redact(item)
        elif isinstance(value, list):
            for element in value:
                _redact(element)
    
    _redact(sanitized)
    return sanitized


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
            chunk.replace("\ufeff", "").replace(
                "\r\n", "\n").replace("\r", "\n")
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
            self._plain_buffer = self._plain_buffer[newline_index + 1:]
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
        self._stream_decoders: Dict[Tuple[str, str],
                                    _PowerShellStreamDecoder] = {}
        self._host_running: Dict[str, str] = {}
        self._host_waiters: Dict[str, Deque[Tuple[str, asyncio.Event]]] = {}

    def _get_job_runtime_profile(
        self, job_type: str
    ) -> Tuple[RemoteTaskCategory, float]:
        """Return the remote execution category and timeout for a job type."""

        # Long-running jobs that create/modify VMs
        if job_type in LONG_RUNNING_JOB_TYPES:
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
            job_copy.parameters = _redact_sensitive_parameters(job_copy.parameters)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to redact job parameters for %s", job.job_id)
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

        # Wait for workers with timeout to prevent infinite hangs
        for task in self._worker_tasks:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:  # pragma: no cover - defensive handling
                logger.warning(
                    "Job worker task did not complete within timeout, cancelling")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
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

    async def submit_noop_test_job(
        self,
        target_host: str,
        resource_spec: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Job:
        """Submit a noop-test job using the new protocol.

        Phase 3: This is the first job type to use the new JobRequest envelope.
        It validates the round-trip communication without performing actual operations.
        """
        if not self._started or self._queue is None:
            raise RuntimeError("Job service is not running")

        if not target_host:
            raise RuntimeError("Noop-test job requires a target host")

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="noop_test",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=target_host,
            parameters={
                "resource_spec": resource_spec,
                "correlation_id": correlation_id or job_id,
            },
        )

        async with self._lock:
            self.jobs[job_id] = job

        await self._sync_job_notification(job)
        await self._broadcast_job_status(job)

        await self._queue.put(job_id)
        logger.info("Queued noop-test job %s for host %s", job_id, target_host)
        return self._prepare_job_response(job)

    async def submit_managed_deployment_v2_job(
        self,
        request: ManagedDeploymentRequest,
    ) -> Job:
        """Submit a managed deployment job using the new Pydantic-based protocol.

        Phase 6: This replaces the schema-driven managed deployment with Pydantic
        models and the new JobRequest/JobResult protocol.

        The deployment will orchestrate:
        1. VM creation via vm.create operation
        2. Disk creation via disk.create operation
        3. NIC creation via nic.create operation
        4. Guest configuration via generate_guest_config() and KVP
        """
        if not self._started or self._queue is None:
            raise RuntimeError("Job service is not running")

        target_host = request.target_host.strip()
        if not target_host:
            raise RuntimeError(
                "Managed deployment v2 job requires a target host")

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="managed_deployment_v2",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=target_host,
            parameters={
                "request": request.model_dump(),
            },
        )

        async with self._lock:
            self.jobs[job_id] = job

        await self._sync_job_notification(job)
        await self._broadcast_job_status(job)

        await self._queue.put(job_id)
        logger.info("Queued managed deployment v2 job %s for host %s",
                    job_id, target_host)
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
                logger.exception(
                    "Unhandled exception while processing job %s", job_id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        async with self._lock:
            job = self.jobs.get(job_id)
        if not job:
            logger.warning("Received unknown job id %s", job_id)
            return

        # Enrich job with resource metadata before execution
        await self._enrich_job_metadata(job)

        host_key = self._normalise_host(job.target_host)
        acquired_host = False

        try:
            # Acquire host slot for jobs that need serialization
            if job.job_type in SERIALIZED_JOB_TYPES and host_key:
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
                elif job.job_type == "managed_deployment_v2":
                    await self._execute_managed_deployment_v2_job(job)
                elif job.job_type == "initialize_vm":
                    await self._execute_initialize_vm_job(job)
                elif job.job_type == "noop_test":
                    await self._execute_noop_test_job(job)
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

    async def _enrich_job_metadata(self, job: Job) -> None:
        """Collect and store resource metadata in job parameters for logging/notifications.

        This runs before job execution to capture current state from inventory.
        Metadata is stored in job.parameters['_metadata'] for use in notifications.
        """
        metadata = {}

        definition = job.parameters.get("definition", {})
        fields = definition.get("fields", {})

        # Extract resource information based on job type
        vm_jobs = (
            "create_vm", "update_vm", "delete_vm",
            "managed_deployment", "initialize_vm"
        )
        nic_jobs = ("create_nic", "update_nic", "delete_nic")
        disk_jobs = ("create_disk", "update_disk", "delete_disk")

        if job.job_type in vm_jobs:
            # For VM jobs, get VM name from parameters
            if job.job_type == "delete_vm":
                vm_name = job.parameters.get("vm_name")
            else:
                vm_name = fields.get("vm_name")

            if vm_name:
                metadata["resource_type"] = "VM"
                metadata["resource_name"] = vm_name
                metadata["vm_name"] = vm_name

        elif job.job_type in nic_jobs or job.job_type in disk_jobs:
            # For NIC/Disk jobs, look up parent VM and resource names
            vm_id = fields.get("vm_id")
            resource_id = fields.get("resource_id")

            if vm_id:
                vm = inventory_service.get_vm_by_id(vm_id)
                if vm:
                    metadata["vm_name"] = vm.name
                    metadata["vm_id"] = vm.id

                    if job.job_type in nic_jobs:
                        metadata["resource_type"] = "Network Adapter"
                        # Try to find NIC name
                        if resource_id and vm.networks:
                            for nic in vm.networks:
                                if nic.id and nic.id.lower() == resource_id.lower():
                                    metadata["resource_name"] = nic.name or f"NIC {resource_id[:8]}"
                                    metadata["resource_id"] = resource_id
                                    break
                        # For create, use adapter_name from fields
                        if not metadata.get("resource_name"):
                            adapter_name = fields.get("adapter_name")
                            if adapter_name:
                                metadata["resource_name"] = adapter_name
                            elif resource_id:
                                metadata["resource_name"] = f"NIC {resource_id[:8]}"
                            else:
                                metadata["resource_name"] = "Network Adapter"

                    elif job.job_type in disk_jobs:
                        metadata["resource_type"] = "Disk"
                        # Try to find disk name
                        if resource_id and vm.disks:
                            for disk in vm.disks:
                                if disk.id and disk.id.lower() == resource_id.lower():
                                    # Use the actual disk filename
                                    if disk.name:
                                        metadata["resource_name"] = disk.name
                                    elif disk.path:
                                        import os
                                        metadata["resource_name"] = os.path.basename(
                                            disk.path)
                                    else:
                                        metadata["resource_name"] = "Disk"
                                    metadata["resource_id"] = resource_id
                                    break
                        # For create, use image_name or disk_size_gb
                        if not metadata.get("resource_name"):
                            image_name = fields.get("image_name")
                            disk_size_gb = fields.get("disk_size_gb")
                            if image_name:
                                metadata["resource_name"] = f"Disk from '{image_name}'"
                            elif disk_size_gb:
                                metadata["resource_name"] = f"{disk_size_gb}GB Disk"
                            else:
                                metadata["resource_name"] = "Disk"

        # Store metadata in job parameters
        if metadata:
            async with self._lock:
                job.parameters["_metadata"] = metadata

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
        """Execute a VM deletion job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Delete job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for deletion")

        # Extract VM info from job parameters
        vm_id = job.parameters.get("vm_id")
        vm_name = job.parameters.get("vm_name")

        # Create resource_spec for the delete operation
        resource_spec = {
            "vm_id": vm_id,
            "vm_name": vm_name,
        }

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation="vm.delete",
            resource_spec=resource_spec,
            correlation_id=job.job_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"VM deletion script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                "No JSON result returned from vm.delete operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"VM deletion failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"VM deletion completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data

        # Append result data as JSON to job output for compatibility
        if envelope.data:
            await self._append_job_output(
                job.job_id,
                json.dumps(envelope.data),
            )

    async def _execute_create_vm_job(self, job: Job) -> None:
        """Execute a VM-only creation job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("VM creation job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for VM creation")

        # Extract resource_spec from job parameters
        # The definition contains the Pydantic VmSpec fields
        definition = job.parameters.get("definition", {})
        resource_spec = definition.get("fields", {})

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation="vm.create",
            resource_spec=resource_spec,
            correlation_id=job.job_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"VM creation script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                "No JSON result returned from vm.create operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"VM creation failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"VM creation completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data

        # Append result data as JSON to job output for managed deployment compatibility
        # Managed deployments use _extract_vm_id_from_output to parse the vm_id
        if envelope.data:
            await self._append_job_output(
                job.job_id,
                json.dumps(envelope.data),
            )

    async def _execute_create_disk_job(self, job: Job) -> None:
        """Execute a disk creation and attachment job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Disk creation job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for disk creation")

        # Extract resource_spec from job parameters
        definition = job.parameters.get("definition", {})
        resource_spec = definition.get("fields", {})

        # Validate that VM exists
        vm_id = resource_spec.get("vm_id")
        if not vm_id:
            raise RuntimeError("Disk creation requires vm_id")

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation="disk.create",
            resource_spec=resource_spec,
            correlation_id=job.job_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"Disk creation script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                "No JSON result returned from disk.create operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"Disk creation failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"Disk creation completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data

        # Append result data as JSON to job output for managed deployment compatibility
        if envelope.data:
            await self._append_job_output(
                job.job_id,
                json.dumps(envelope.data),
            )

    async def _execute_create_nic_job(self, job: Job) -> None:
        """Execute a NIC creation and attachment job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("NIC creation job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for NIC creation")

        # Extract resource_spec from job parameters
        definition = job.parameters.get("definition", {})
        resource_spec = definition.get("fields", {})

        # Validate that VM exists
        vm_id = resource_spec.get("vm_id")
        if not vm_id:
            raise RuntimeError("NIC creation requires vm_id")

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation="nic.create",
            resource_spec=resource_spec,
            correlation_id=job.job_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"NIC creation script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                "No JSON result returned from nic.create operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"NIC creation failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"NIC creation completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data

        # Append result data as JSON to job output for managed deployment compatibility
        if envelope.data:
            await self._append_job_output(
                job.job_id,
                json.dumps(envelope.data),
            )

    async def _execute_new_protocol_operation(
        self,
        job: Job,
        operation: str,
        operation_name: str,
    ) -> None:
        """Execute an operation using the new JobRequest/JobResult protocol.

        Phase 4: Generic helper for all new protocol operations.

        Args:
            job: Job object
            operation: Operation identifier (e.g., 'vm.update', 'disk.delete')
            operation_name: Human-readable operation name for error messages
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError(
                f"{operation_name} job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for {operation_name}")

        # Extract resource_spec from job parameters
        definition = job.parameters.get("definition", {})
        resource_spec = definition.get("fields", {})

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation=operation,
            resource_spec=resource_spec,
            correlation_id=job.job_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"{operation_name} script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                f"No JSON result returned from {operation} operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"{operation_name} failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"{operation_name} completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data

        # Append result data as JSON to job output for compatibility
        # (e.g., managed deployments may parse output for resource IDs)
        if envelope.data:
            await self._append_job_output(
                job.job_id,
                json.dumps(envelope.data),
            )

    async def _execute_update_vm_job(self, job: Job) -> None:
        """Execute a VM update job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "vm.update", "VM update")

    async def _execute_update_disk_job(self, job: Job) -> None:
        """Execute a disk update job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "disk.update", "Disk update")

    async def _execute_update_nic_job(self, job: Job) -> None:
        """Execute a NIC update job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "nic.update", "NIC update")

    async def _execute_delete_disk_job(self, job: Job) -> None:
        """Execute a disk deletion job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "disk.delete", "Disk deletion")

    async def _execute_delete_nic_job(self, job: Job) -> None:
        """Execute a NIC deletion job using new protocol.

        Phase 4: Converted to use JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "nic.delete", "NIC deletion")

    async def _execute_initialize_vm_job(self, job: Job) -> None:
        """Execute a VM initialization job that applies guest configuration."""

        definition = job.parameters.get("definition", {})
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError(
                "VM initialization job is missing a target host")

        fields = definition.get("fields", {})
        vm_id = fields.get("vm_id")
        if not vm_id:
            raise RuntimeError("VM initialization requires vm_id")

        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for initialization")

        json_payload = await asyncio.to_thread(
            json.dumps, fields, ensure_ascii=False, separators=(",", ":")
        )
        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Invoke-InitializeVmJob.ps1")
        command = self._build_agent_invocation_command(
            "Invoke-InitializeVmJob.ps1", json_payload
        )

        exit_code = await self._execute_agent_command(job, target_host, command)
        if exit_code != 0:
            raise RuntimeError(
                f"VM initialization script exited with code {exit_code}")

    async def _execute_noop_test_job(self, job: Job) -> None:
        """Execute a noop-test job using the new protocol.

        Phase 3: This is the first operation to use the new JobRequest/JobResult
        envelope protocol. It validates the round-trip communication between
        server and host agent without performing any actual operations.
        """
        target_host = (job.target_host or "").strip()
        if not target_host:
            raise RuntimeError("Noop-test job is missing a target host")

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for noop-test")

        # Extract resource_spec from job parameters
        # For noop-test, resource_spec should be in parameters
        resource_spec = job.parameters.get("resource_spec", {})
        correlation_id = job.parameters.get("correlation_id") or job.job_id

        # Create JobRequest envelope using the new protocol
        job_request = create_job_request(
            operation="noop-test",
            resource_spec=resource_spec,
            correlation_id=correlation_id,
            metadata={
                "job_id": job.job_id,
                "job_type": job.job_type,
                "target_host": target_host,
            }
        )

        # Serialize the envelope to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"Noop-test script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                "No JSON result returned from noop-test operation")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(f"Failed to parse job result: {error}")

        if not envelope:
            raise RuntimeError("Job result envelope is None")

        # Check the result status
        if envelope.status == "error":
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(f"Noop-test failed ({error_code}): {error_msg}")

        # Log success with result data
        await self._append_job_output(
            job.job_id,
            f"Noop-test completed: {envelope.message}",
            f"Result status: {envelope.status}",
        )

        # Store result data in job parameters for later retrieval
        job.parameters["result_data"] = envelope.data
        job.parameters["result_status"] = envelope.status
        await self._update_job(job.job_id, parameters=job.parameters)

    async def _execute_managed_deployment_v2_job(self, job: Job) -> None:
        """Execute a managed deployment using the new Pydantic-based protocol.

        Phase 6: This method orchestrates VM creation using the new protocol:
        1. Create VM via vm.create JobRequest
        2. Create Disk via disk.create JobRequest
        3. Create NIC via nic.create JobRequest
        4. Generate guest config using generate_guest_config()
        5. Send guest config via KVP (using existing initialize-vm mechanism)

        This completely bypasses schemas and uses Pydantic models throughout.
        """
        from ..core.pydantic_models import (
            VmSpec,
            DiskSpec,
            NicSpec,
            GuestConfigSpec,
            ManagedDeploymentRequest,
        )

        # Extract and reconstruct the ManagedDeploymentRequest from parameters
        request_dict = job.parameters.get("request", {})
        request = ManagedDeploymentRequest(**request_dict)

        target_host = request.target_host.strip()
        if not target_host:
            raise RuntimeError(
                "Managed deployment v2 job is missing a target host")

        await self._append_job_output(
            job.job_id,
            "Managed deployment v2 starting - using new Pydantic protocol",
        )

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for deployment")

        # Validate host resources before creating any resources
        # Build a fields dict from Pydantic models for validation
        validation_fields = {}

        # Extract storage_class from VM spec
        if request.vm_spec.storage_class:
            validation_fields["storage_class"] = request.vm_spec.storage_class

        # Extract storage_class from disk spec (takes precedence if specified)
        if request.disk_spec and request.disk_spec.storage_class:
            validation_fields["storage_class"] = (
                request.disk_spec.storage_class
            )

        # Extract network from NIC spec
        if request.nic_spec and request.nic_spec.network:
            validation_fields["network"] = request.nic_spec.network

        # Validate against host configuration
        await self._validate_job_against_host_config(
            {"fields": validation_fields}, target_host
        )

        # Step 1: Create VM using new protocol
        await self._append_job_output(
            job.job_id,
            f"Creating VM '{request.vm_spec.vm_name}' via new protocol...",
        )

        vm_job_request = create_job_request(
            operation="vm.create",
            resource_spec=request.vm_spec.model_dump(),
            correlation_id=f"{job.job_id}-vm",
        )

        vm_result = await self._execute_managed_deployment_protocol_operation(
            job, target_host, vm_job_request, "VM creation"
        )

        # Extract VM ID from result
        vm_id = vm_result.data.get("vm_id") or vm_result.data.get(
            "vmId") or vm_result.data.get("id")
        if not vm_id:
            raise RuntimeError(
                f"VM creation succeeded but no VM ID returned: {vm_result.data}")

        await self._append_job_output(
            job.job_id,
            f"VM created successfully with ID: {vm_id}",
        )

        # Store VM ID in job parameters for reference
        job.parameters["vm_id"] = vm_id
        await self._update_job(job.job_id, parameters=job.parameters)

        # Step 2: Create Disk if specified
        if request.disk_spec:
            await self._append_job_output(
                job.job_id,
                "Creating disk via new protocol...",
            )

            # Add VM ID to disk spec
            disk_dict = request.disk_spec.model_dump()
            disk_dict["vm_id"] = vm_id

            disk_job_request = create_job_request(
                operation="disk.create",
                resource_spec=disk_dict,
                correlation_id=f"{job.job_id}-disk",
            )

            disk_result = await self._execute_managed_deployment_protocol_operation(
                job, target_host, disk_job_request, "Disk creation"
            )

            await self._append_job_output(
                job.job_id,
                "Disk created successfully",
            )

        # Step 3: Create NIC if specified
        if request.nic_spec:
            await self._append_job_output(
                job.job_id,
                "Creating NIC via new protocol...",
            )

            # Add VM ID to NIC spec
            nic_dict = request.nic_spec.model_dump()
            nic_dict["vm_id"] = vm_id

            nic_job_request = create_job_request(
                operation="nic.create",
                resource_spec=nic_dict,
                correlation_id=f"{job.job_id}-nic",
            )

            nic_result = await self._execute_managed_deployment_protocol_operation(
                job, target_host, nic_job_request, "NIC creation"
            )

            await self._append_job_output(
                job.job_id,
                "NIC created successfully",
            )

        # Step 4: Generate and send guest config if specified
        if request.guest_config:
            await self._append_job_output(
                job.job_id,
                "Generating guest configuration using Pydantic models...",
            )

            # Generate guest config using the new generator
            guest_config_dict = generate_guest_config(
                vm_spec=request.vm_spec,
                nic_spec=request.nic_spec,
                disk_spec=request.disk_spec,
                guest_config_spec=request.guest_config,
            )

            await self._append_job_output(
                job.job_id,
                f"Generated guest config with {len(guest_config_dict)} keys",
            )

            if guest_config_dict:
                # Send guest config via existing KVP mechanism
                # We reuse the initialize-vm job type for KVP transmission
                init_fields = {
                    "vm_id": vm_id,
                    "vm_name": request.vm_spec.vm_name,
                    **guest_config_dict,
                }

                init_job_definition = {
                    "schema": {"id": "initialize-vm", "version": 1},
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
                        f"Guest initialization failed: {init_job_result.error or 'unknown error'}"
                    )

                await self._append_job_output(
                    job.job_id,
                    "Guest configuration sent successfully",
                )

        await self._append_job_output(
            job.job_id,
            f"Managed deployment v2 complete. VM '{request.vm_spec.vm_name}' fully deployed on {target_host}.",
        )

    async def _execute_managed_deployment_protocol_operation(
        self,
        job: Job,
        target_host: str,
        job_request: JobRequest,
        operation_description: str,
    ) -> JobResultEnvelope:
        """Execute a single operation using the new JobRequest/JobResult protocol.

        This is a helper method for executing individual operations (VM, Disk, NIC)
        during managed deployment v2. This is separate from the Phase 4 
        _execute_new_protocol_operation method which has a different signature.

        Args:
            job: The parent job (for logging context)
            target_host: Target host for execution
            job_request: JobRequest envelope
            operation_description: Human-readable description for logging

        Returns:
            JobResultEnvelope with the operation result

        Raises:
            RuntimeError: If the operation fails
        """
        # Serialize the JobRequest to JSON
        json_payload = await asyncio.to_thread(
            job_request.model_dump_json,
        )

        self._log_agent_request(job.job_id, target_host,
                                json_payload, "Main-NewProtocol.ps1")

        # Build command to invoke Main-NewProtocol.ps1
        command = self._build_agent_invocation_command(
            "Main-NewProtocol.ps1", json_payload
        )

        # Storage for the result JSON
        result_json_lines: List[str] = []

        def capture_json_output(line: str) -> None:
            """Capture JSON output from the host agent."""
            stripped = line.strip()
            if stripped.startswith('{'):
                result_json_lines.append(stripped)

        # Execute the command with JSON capture
        exit_code = await self._execute_agent_command(
            job, target_host, command, line_callback=capture_json_output
        )

        if exit_code != 0:
            raise RuntimeError(
                f"{operation_description} script exited with code {exit_code}")

        # Parse the JobResult envelope
        if not result_json_lines:
            raise RuntimeError(
                f"No JSON result returned from {operation_description}")

        # Use the first (and should be only) JSON line
        result_json = result_json_lines[0]
        envelope, error = parse_job_result(result_json)

        if error:
            raise RuntimeError(
                f"Failed to parse {operation_description} result: {error}")

        if not envelope:
            raise RuntimeError(
                f"{operation_description} result envelope is None")

        # Check the result status
        if envelope.status == JobResultStatus.ERROR:
            error_msg = envelope.message or "Unknown error"
            error_code = envelope.code or "UNKNOWN"
            raise RuntimeError(
                f"{operation_description} failed ({error_code}): {error_msg}")

        return envelope

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
            existing_children = list(
                parent_job.child_jobs) if parent_job else []

        if not parent_job or not child_job:
            return

        summary = self._build_child_job_summary(child_job)
        updated_children = self._merge_child_job_list(
            existing_children, summary)
        await self._update_job(parent_job_id, child_jobs=updated_children)

    def _build_child_job_summary(self, child_job: Job) -> Dict[str, Any]:
        """Build a lightweight summary for UI consumption."""

        status_value = (
            child_job.status.value if isinstance(
                child_job.status, JobStatus) else child_job.status
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
                candidate = line[line.index("{"): line.rindex("}") + 1]
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

            id_match = re.search(
                r"vm[_\s-]?id\s*[:=]\s*([^\s]+)", line, flags=re.IGNORECASE)
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
            # Log raw JSON received from host agent (detect JSON by looking for leading '{')
            if stream.lower() == "stdout" and line.strip().startswith('{'):
                logger.debug(
                    "Received JSON from host agent for job %s: %s",
                    job_id,
                    line
                )

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
        pending_keys = [
            key for key in self._stream_decoders if key[0] == job_id]
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
                        logger.exception(
                            "line_callback failed for job %s", job_id)

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
            trimmed = trimmed[len(self._CLIXML_PREFIX):].lstrip()

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
                # Get vm_name from enriched metadata, or fallback to parameters
                metadata = job.parameters.get("_metadata", {})
                vm_name = metadata.get(
                    "vm_name") or metadata.get("resource_name")

                if not vm_name:
                    # Fallback for tests or when enrichment hasn't run
                    definition = job.parameters.get("definition") or {}
                    fields = definition.get("fields") or {}
                    vm_name = fields.get(
                        "vm_name") or job.parameters.get("vm_name")

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
        """Create or update job notification using pre-enriched metadata."""

        # Get enriched metadata (populated in _enrich_job_metadata)
        # If not enriched yet (e.g., in tests), extract basic info from parameters
        metadata = job.parameters.get("_metadata", {})

        if not metadata:
            # Fallback: extract vm_name from parameters for notification metadata
            definition = job.parameters.get("definition") or {}
            fields = definition.get("fields") or {}
            vm_name = fields.get("vm_name") or job.parameters.get("vm_name")

            # Set minimal metadata for notification purposes
            metadata = {
                "resource_type": "VM" if "vm" in job.job_type else "Resource",
                "resource_name": vm_name,
                "vm_name": vm_name,
            }

        resource_type = metadata.get("resource_type", "Resource")
        resource_name = metadata.get("resource_name")
        vm_name = metadata.get("vm_name")

        # Determine action verb
        is_create = (
            job.job_type.startswith("create_") or
            job.job_type == "managed_deployment"
        )
        if is_create:
            action = "Create"
        elif job.job_type.startswith("update_"):
            action = "Update"
        elif job.job_type.startswith("delete_"):
            action = "Delete"
        elif job.job_type == "initialize_vm":
            action = "Initialize"
        else:
            action = job.job_type.replace("_", " ").title()

        # Format resource name for display
        resource_label = resource_name if resource_name else job.job_id[:8]

        # Determine location phrase
        is_vm_job = resource_type == "VM"
        if is_vm_job:
            if job.target_host:
                location_phrase = f"host {job.target_host}"
            else:
                location_phrase = "unknown host"
        else:
            # For NICs and Disks, show the parent VM name
            if vm_name:
                location_phrase = f"VM '{vm_name}'"
            else:
                location_phrase = "unknown VM"

        # Build status-specific messages
        if job.status == JobStatus.PENDING:
            title = f"{action} {resource_type} queued"
            message = (
                f"{action} {resource_type} '{resource_label}' "
                f"queued for {location_phrase}."
            )
            level = NotificationLevel.INFO
        elif job.status == JobStatus.RUNNING:
            title = f"{action} {resource_type} running"
            message = (
                f"{action} {resource_type} '{resource_label}' "
                f"running on {location_phrase}."
            )
            level = NotificationLevel.INFO
        elif job.status == JobStatus.COMPLETED:
            title = f"{action} {resource_type} completed"
            message = (
                f"{action} {resource_type} '{resource_label}' "
                f"completed successfully on {location_phrase}."
            )
            level = NotificationLevel.SUCCESS
        elif job.status == JobStatus.FAILED:
            title = f"{action} {resource_type} failed"
            detail = f" Error: {job.error}" if job.error else ""
            message = (
                f"{action} {resource_type} '{resource_label}' "
                f"failed on {location_phrase}.{detail}"
            )
            level = NotificationLevel.ERROR
        else:
            title = f"{action} {resource_type} update"
            message = (
                f"{action} {resource_type} '{resource_label}' updated."
            )
            level = NotificationLevel.INFO

        # For notification metadata, use vm_name from enriched data
        notification_metadata = {
            "job_id": job.job_id,
            "status": job.status.value,
            "job_type": job.job_type,
            "vm_name": vm_name,
            "target_host": job.target_host,
        }

        notification = notification_service.upsert_job_notification(
            job.job_id,
            title=title,
            message=message,
            level=level,
            status=job.status,
            metadata=notification_metadata,
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
        message = {"type": "job", "action": action,
                   "job_id": job_id, "data": data}
        try:
            await websocket_manager.broadcast(message, topic=f"jobs:{job_id}")
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to broadcast job event for %s", job_id)

        try:
            await websocket_manager.broadcast(message, topic="jobs")
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to broadcast aggregate job event for %s", job_id)

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

    def _log_agent_request(self, job_id: str, target_host: str, payload: str, script_name: str) -> None:
        """Log raw JSON being sent to host agent.

        This logging is added as part of Phase 0 preparation for the schema-to-Pydantic refactor.
        It provides visibility into server↔agent communication for debugging and validation.
        """
        logger.debug(
            "Sending JSON to host agent - job=%s host=%s script=%s payload=%s",
            job_id,
            target_host,
            script_name,
            payload
        )

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
                available = host_resources_service.get_available_networks(
                    host_config)
                raise ValueError(
                    f"Network '{network_name}' not found on host {target_host}. "
                    f"Available networks: {', '.join(available) if available else 'none'}"
                )

        # Validate storage class if provided
        storage_class = fields.get("storage_class")
        if storage_class:
            if not host_resources_service.validate_storage_class(storage_class, host_config):
                available = host_resources_service.get_available_storage_classes(
                    host_config)
                raise ValueError(
                    f"Storage class '{storage_class}' not found on host {target_host}. "
                    f"Available storage classes: {', '.join(available) if available else 'none'}"
                )


default_job_service = JobService()
job_service = default_job_service
