"""Schema-driven job submission and execution service."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from ..core.config import settings
from ..core.models import Job, JobStatus, VMDeleteRequest, NotificationLevel
from ..core.job_envelope import create_job_request, parse_job_result
from ..core.pydantic_models import (
    ManagedDeploymentRequest,
    OSFamily,
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

# Job types that require per-host serialization in the job queue
# IO-intensive jobs (disk creation, guest init) are additionally serialized
# at the remote_task_service level to prevent host IO overload
IO_INTENSIVE_JOB_TYPES = {
    "create_disk", "update_disk", "delete_disk",  # Disk operations
    "initialize_vm",  # Guest configuration
}

# Common Linux distribution keywords for OS family detection
LINUX_IMAGE_KEYWORDS = frozenset({
    "linux",
    "ubuntu",
    "debian",
    "centos",
    "rhel",
    "redhat",
    "fedora",
    "suse",
    "opensuse",
    "arch",
    "alpine",
    "rocky",
    "alma",
    "oracle linux",
    "amazon linux",
    "kali",
    "mint",
})


def detect_os_family_from_image_name(image_name: Optional[str]) -> OSFamily:
    """Detect the OS family from an image name.

    Parses the image name for common Linux distribution keywords and returns
    the appropriate OS family. Defaults to Windows if no Linux keywords are found.

    Args:
        image_name: The name of the golden image to clone (e.g., "Ubuntu 22.04", "Windows Server 2022")

    Returns:
        OSFamily.LINUX if a Linux distribution is detected, otherwise OSFamily.WINDOWS
    """
    if not image_name or not image_name.strip():
        return OSFamily.WINDOWS

    image_name_lower = image_name.lower()
    for keyword in LINUX_IMAGE_KEYWORDS:
        if keyword in image_name_lower:
            return OSFamily.LINUX

    return OSFamily.WINDOWS


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
        "guest_domain_join_pw",
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


class _SimpleLineBuffer:
    """Stateful line buffer for streamed output.

    Note: pypsrp handles CLIXML deserialization internally, so we only need
    simple line buffering for the plain text it returns.
    """

    def __init__(self) -> None:
        self._buffer: str = ""

    def push(self, chunk: str) -> List[str]:
        """Add chunk and return complete lines."""
        if not chunk:
            return []

        # Normalize line endings and remove BOM
        normalized = (
            chunk.replace("\ufeff", "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        if not normalized:
            return []

        self._buffer += normalized

        # Extract complete lines
        lines: List[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                lines.append(line)

        return lines

    def finalize(self) -> List[str]:
        """Return any remaining buffered content."""
        if self._buffer.strip():
            result = [self._buffer]
            self._buffer = ""
            return result
        return []


class JobService:
    """Service for tracking and executing submitted jobs."""

    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.job_notifications: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._queue: Optional[asyncio.Queue[Optional[str]]] = None
        self._worker_tasks: List[asyncio.Task[None]] = []
        self._started = False
        self._line_buffers: Dict[Tuple[str, str], _SimpleLineBuffer] = {}
        self._host_running: Dict[str, str] = {}
        self._host_waiters: Dict[str, Deque[Tuple[str, asyncio.Event]]] = {}

    def _get_job_runtime_profile(
        self, job_type: str
    ) -> Tuple[RemoteTaskCategory, float]:
        """Return the remote execution category and timeout for a job type.
        
        IO-intensive jobs (disk creation, guest initialization):
        - Use RemoteTaskCategory.IO for per-host serialization
        - Longer timeout to accommodate disk cloning and guest config
        
        Short jobs (everything else):
        - Use RemoteTaskCategory.SHORT with rate-limited dispatching
        - Shorter timeout for quick operations
        """

        # IO-intensive jobs: disk operations and guest initialization
        # These require per-host serialization to prevent IO overload
        io_intensive_types = {
            "create_disk", "update_disk", "delete_disk",  # Disk cloning/copying
            "initialize_vm",  # Guest configuration via KVP
        }
        if job_type in io_intensive_types:
            return (
                RemoteTaskCategory.IO,
                float(settings.io_job_timeout_seconds),
            )

        # All other jobs use SHORT category with rate-limited dispatching
        # This includes: VM CRUD, NIC operations, managed deployments, deletions
        return (
            RemoteTaskCategory.SHORT,
            float(settings.short_job_timeout_seconds),
        )

    def _prepare_job_response(self, job: Job) -> Job:
        """Return a deep-copied job with sensitive data redacted."""

        job_copy = job.model_copy(deep=True)
        try:
            job_copy.parameters = _redact_sensitive_parameters(
                job_copy.parameters)
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
        # Fixed number of job workers - actual WinRM concurrency is controlled by remote_task_service
        concurrency = 6
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
            created_at=datetime.now(timezone.utc),
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
            created_at=datetime.now(timezone.utc),
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

        Uses the JobRequest envelope protocol.
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
            created_at=datetime.now(timezone.utc),
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

    async def submit_managed_deployment_job(
        self,
        request: ManagedDeploymentRequest,
    ) -> Job:
        """Submit a managed deployment job using the Pydantic-based protocol.

        Orchestrates a complete VM deployment using Pydantic
        models and the JobRequest/JobResult protocol.

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
                "Managed deployment job requires a target host")

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="managed_deployment",
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc),
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
        logger.info("Queued managed deployment job %s for host %s",
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
            # Acquire host slot for IO-intensive jobs that need serialization
            # This is in addition to remote_task_service IO queue serialization
            # Child jobs inherit the parent's serialization slot, so skip
            # acquiring a new slot to avoid deadlock when parent waits
            # for child completion
            is_child_job = job.parameters.get("parent_job_id") is not None
            needs_serialization = (
                job.job_type in IO_INTENSIVE_JOB_TYPES
                and host_key
                and not is_child_job
            )
            if needs_serialization:
                await self._acquire_host_slot(host_key, job.job_id)
                acquired_host = True

            await self._update_job(
                job_id, status=JobStatus.RUNNING, started_at=datetime.now(timezone.utc)
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
                    completed_at=datetime.now(timezone.utc),
                    error=str(exc),
                )
                return

            await self._update_job(
                job_id,
                status=JobStatus.COMPLETED,
                completed_at=datetime.now(timezone.utc),
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
        
        Metadata fields:
        - resource_type: "VM", "Network Adapter", or "Disk"
        - resource_name: Human-readable resource name
        - vm_name: Parent VM name (all job types)
        """
        metadata = {}
        definition = job.parameters.get("definition", {})
        fields = definition.get("fields", {})

        # VM jobs: Extract VM name
        if job.job_type in ("create_vm", "update_vm", "delete_vm", "initialize_vm"):
            vm_name = fields.get("vm_name") or job.parameters.get("vm_name")
            if vm_name:
                metadata["resource_type"] = "VM"
                metadata["resource_name"] = vm_name
                metadata["vm_name"] = vm_name

        # Managed deployment: Special case for nested structure
        elif job.job_type == "managed_deployment":
            request_data = job.parameters.get("request", {})
            vm_spec = request_data.get("vm_spec", {})
            vm_name = vm_spec.get("vm_name")
            if vm_name:
                metadata["resource_type"] = "VM"
                metadata["resource_name"] = vm_name
                metadata["vm_name"] = vm_name

        # NIC jobs: Look up parent VM and NIC details
        elif job.job_type in ("create_nic", "update_nic", "delete_nic"):
            vm_id = fields.get("vm_id")
            resource_id = fields.get("resource_id")
            
            if vm_id:
                vm = inventory_service.get_vm_by_id(vm_id)
                if vm:
                    metadata["vm_name"] = vm.name
                    metadata["resource_type"] = "Network Adapter"
                    
                    # Find existing NIC name from inventory
                    resource_name = None
                    if resource_id and vm.networks:
                        for nic in vm.networks:
                            if nic.id and nic.id.lower() == resource_id.lower():
                                resource_name = nic.name or f"NIC {resource_id[:8]}"
                                break
                    
                    # Fallback to field values for create operations
                    if not resource_name:
                        adapter_name = fields.get("adapter_name")
                        if adapter_name:
                            resource_name = adapter_name
                        elif resource_id:
                            resource_name = f"NIC {resource_id[:8]}"
                        else:
                            resource_name = "Network Adapter"
                    
                    if resource_name:
                        metadata["resource_name"] = resource_name

        # Disk jobs: Look up parent VM and disk details
        elif job.job_type in ("create_disk", "update_disk", "delete_disk"):
            vm_id = fields.get("vm_id")
            resource_id = fields.get("resource_id")
            
            if vm_id:
                vm = inventory_service.get_vm_by_id(vm_id)
                if vm:
                    metadata["vm_name"] = vm.name
                    metadata["resource_type"] = "Disk"
                    
                    # Find existing disk name from inventory
                    resource_name = None
                    if resource_id and vm.disks:
                        for disk in vm.disks:
                            if disk.id and disk.id.lower() == resource_id.lower():
                                if disk.name:
                                    resource_name = disk.name
                                elif disk.path:
                                    resource_name = os.path.basename(disk.path)
                                else:
                                    resource_name = "Disk"
                                break
                    
                    # Fallback to field values for create operations
                    if not resource_name:
                        image_name = fields.get("image_name")
                        disk_size_gb = fields.get("disk_size_gb")
                        if image_name:
                            resource_name = f"Disk from '{image_name}'"
                        elif disk_size_gb:
                            resource_name = f"{disk_size_gb}GB Disk"
                        else:
                            resource_name = "Disk"
                    
                    if resource_name:
                        metadata["resource_name"] = resource_name

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
        """Execute a VM deletion job using new protocol."""
        def extract_delete_resource_spec(j: Job) -> Dict[str, Any]:
            return {
                "vm_id": j.parameters.get("vm_id"),
                "vm_name": j.parameters.get("vm_name"),
                "delete_disks": j.parameters.get("delete_disks", False),
            }

        await self._execute_new_protocol_operation(
            job, "vm.delete", "VM deletion",
            extract_resource_spec=extract_delete_resource_spec
        )

    async def _execute_create_vm_job(self, job: Job) -> None:
        """Execute a VM-only creation job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "vm.create", "VM creation"
        )

    async def _execute_create_disk_job(self, job: Job) -> None:
        """Execute a disk creation and attachment job using new protocol."""
        def validate_disk_spec(resource_spec: Dict[str, Any]) -> None:
            if not resource_spec.get("vm_id"):
                raise RuntimeError("Disk creation requires vm_id")

        await self._execute_new_protocol_operation(
            job, "disk.create", "Disk creation",
            validate_resource_spec=validate_disk_spec
        )

    async def _execute_create_nic_job(self, job: Job) -> None:
        """Execute a NIC creation and attachment job using new protocol."""
        def validate_nic_spec(resource_spec: Dict[str, Any]) -> None:
            if not resource_spec.get("vm_id"):
                raise RuntimeError("NIC creation requires vm_id")

        await self._execute_new_protocol_operation(
            job, "nic.create", "NIC creation",
            validate_resource_spec=validate_nic_spec
        )

    async def _execute_new_protocol_operation(
        self,
        job: Job,
        operation: str,
        operation_name: str,
        extract_resource_spec: Optional[
            Callable[[Job], Dict[str, Any]]
        ] = None,
        validate_resource_spec: Optional[
            Callable[[Dict[str, Any]], None]
        ] = None,
    ) -> None:
        """Execute an operation using new JobRequest/JobResult protocol.

        Generic helper for JobRequest/JobResult protocol operations.

        Args:
            job: Job object
            operation: Operation identifier (e.g., 'vm.update')
            operation_name: Human-readable name for error messages
            extract_resource_spec: Optional callback to extract
                resource_spec. Defaults to extracting from
                job.parameters['definition']['fields']
            validate_resource_spec: Optional callback to validate
                resource_spec before creating the request envelope
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
        if extract_resource_spec:
            resource_spec = extract_resource_spec(job)
        else:
            definition = job.parameters.get("definition", {})
            resource_spec = definition.get("fields", {})

        # Validate resource_spec if validator provided
        if validate_resource_spec:
            validate_resource_spec(resource_spec)

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
        """Execute a VM update job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "vm.update", "VM update"
        )

    async def _execute_update_disk_job(self, job: Job) -> None:
        """Execute a disk update job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "disk.update", "Disk update"
        )

    async def _execute_update_nic_job(self, job: Job) -> None:
        """Execute a NIC update job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "nic.update", "NIC update"
        )

    async def _execute_delete_disk_job(self, job: Job) -> None:
        """Execute a disk deletion job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "disk.delete", "Disk deletion"
        )

    async def _execute_delete_nic_job(self, job: Job) -> None:
        """Execute a NIC deletion job using new protocol.

        Uses the JobRequest/JobResult envelope protocol.
        """
        await self._execute_new_protocol_operation(job, "nic.delete", "NIC deletion")

    async def _execute_initialize_vm_job(self, job: Job) -> None:
        """Execute a VM initialization job using new protocol."""
        await self._execute_new_protocol_operation(
            job, "vm.initialize", "VM initialization"
        )

    async def _execute_noop_test_job(self, job: Job) -> None:
        """Execute a noop-test job using the new protocol.

        Uses the JobRequest/JobResult
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

    async def _execute_managed_deployment_job(self, job: Job) -> None:
        """Execute a managed deployment using the flat ManagedDeploymentRequest.

        Orchestrates VM creation from the flat form payload:
        1. Extract hardware fields and create VM via vm.create JobRequest
        2. Create Disk via disk.create JobRequest (if image_name provided)
        3. Create NIC via nic.create JobRequest
        4. Generate guest config from flat payload using generate_guest_config()
        5. Send guest config via KVP (using existing initialize-vm mechanism)

        The flat ManagedDeploymentRequest mirrors the UI form submission directly.
        This service parses the flat payload into hardware specs internally.
        """
        from ..core.pydantic_models import (
            ManagedDeploymentRequest,
        )

        # Extract and reconstruct the ManagedDeploymentRequest from parameters
        request_dict = job.parameters.get("request", {})
        request = ManagedDeploymentRequest(**request_dict)

        target_host = request.target_host.strip()
        if not target_host:
            raise RuntimeError(
                "Managed deployment job is missing a target host")

        await self._append_job_output(
            job.job_id,
            "Managed deployment starting - using flat form payload",
        )

        # Ensure host is prepared
        prepared = await host_deployment_service.ensure_host_setup(target_host)
        if not prepared:
            raise RuntimeError(
                f"Failed to prepare host {target_host} for deployment")

        # Validate host resources before creating any resources
        validation_fields = {}

        # Extract storage_class from request (flat field)
        if request.storage_class:
            validation_fields["storage_class"] = request.storage_class

        # Extract network from request (flat field)
        if request.network:
            validation_fields["network"] = request.network

        # Validate against host configuration
        await self._validate_job_against_host_config(
            {"fields": validation_fields}, target_host
        )

        # Detect OS family from image name for secure boot configuration
        image_name = request.image_name
        detected_os_family = detect_os_family_from_image_name(image_name)
        if image_name:
            await self._append_job_output(
                job.job_id,
                f"Detected OS family '{detected_os_family.value}' from image '{image_name}'",
            )

        # Step 1: Create VM as a child job
        await self._append_job_output(
            job.job_id,
            f"Creating VM '{request.vm_name}'...",
        )

        # Build VM spec dict from flat request fields
        vm_spec_dict = {
            "vm_name": request.vm_name,
            "gb_ram": request.gb_ram,
            "cpu_cores": request.cpu_cores,
            "storage_class": request.storage_class,
            "vm_clustered": request.vm_clustered,
            "os_family": detected_os_family.value,
        }

        vm_job_definition = {
            "schema": {"id": "vm.create", "version": 1},
            "fields": vm_spec_dict,
        }

        vm_job = await self._queue_child_job(
            job,
            job_type="create_vm",
            schema_id="vm.create",
            payload=vm_job_definition,
        )

        vm_job_result = await self._wait_for_child_job_completion(
            job.job_id, vm_job.job_id
        )

        if vm_job_result.status != JobStatus.COMPLETED:
            raise RuntimeError(
                f"VM creation failed: {vm_job_result.error or 'unknown error'}"
            )

        # Extract VM ID from result data
        vm_id = self._extract_vm_id_from_output(vm_job_result)
        if not vm_id:
            raise RuntimeError(
                "VM creation completed but no VM ID could be extracted from output"
            )

        await self._append_job_output(
            job.job_id,
            f"VM created successfully with ID: {vm_id}",
        )

        # Store VM ID in job parameters for reference
        job.parameters["vm_id"] = vm_id
        await self._update_job(job.job_id, parameters=job.parameters)

        # Step 2: Create Disk as a child job if image_name provided
        if request.image_name:
            await self._append_job_output(
                job.job_id,
                "Creating disk...",
            )

            # Build disk spec dict from flat request fields
            disk_dict = {
                "vm_id": vm_id,
                "image_name": request.image_name,
                "disk_size_gb": request.disk_size_gb,
                "disk_type": "Dynamic",
                "controller_type": "SCSI",
            }

            disk_job_definition = {
                "schema": {"id": "disk.create", "version": 1},
                "fields": disk_dict,
            }

            disk_job = await self._queue_child_job(
                job,
                job_type="create_disk",
                schema_id="disk.create",
                payload=disk_job_definition,
            )

            disk_job_result = await self._wait_for_child_job_completion(
                job.job_id, disk_job.job_id
            )

            if disk_job_result.status != JobStatus.COMPLETED:
                raise RuntimeError(
                    f"Disk creation failed: {disk_job_result.error or 'unknown error'}"
                )

            await self._append_job_output(
                job.job_id,
                "Disk created successfully",
            )

        # Step 3: Create NIC as a child job
        await self._append_job_output(
            job.job_id,
            "Creating NIC...",
        )

        # Build NIC spec dict from flat request fields
        nic_dict = {
            "vm_id": vm_id,
            "network": request.network,
            "adapter_name": None,
        }

        nic_job_definition = {
            "schema": {"id": "nic.create", "version": 1},
            "fields": nic_dict,
        }

        nic_job = await self._queue_child_job(
            job,
            job_type="create_nic",
            schema_id="nic.create",
            payload=nic_job_definition,
        )

        nic_job_result = await self._wait_for_child_job_completion(
            job.job_id, nic_job.job_id
        )

        if nic_job_result.status != JobStatus.COMPLETED:
            raise RuntimeError(
                f"NIC creation failed: {nic_job_result.error or 'unknown error'}"
            )

        await self._append_job_output(
            job.job_id,
            "NIC created successfully",
        )

        # Step 4: Generate and send guest config
        # Guest config is always generated from the flat request (local admin is required)
        await self._append_job_output(
            job.job_id,
            "Generating guest configuration from form payload...",
        )

        # Generate guest config using the new flat-payload generator
        guest_config_dict = generate_guest_config(request)

        await self._append_job_output(
            job.job_id,
            f"Generated guest config with {len(guest_config_dict)} keys",
        )

        # Send guest config via existing KVP mechanism
        init_fields = {
            "vm_id": vm_id,
            "vm_name": request.vm_name,
            **guest_config_dict,
        }

        # Pass OS family to initialize job for correct provisioning ISO
        init_fields["os_family"] = detected_os_family.value

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
            f"Managed deployment complete. VM '{request.vm_name}' fully deployed on {target_host}.",
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

    def _extract_vm_id_from_output(self, vm_job: Job) -> Optional[str]:
        """Extract VM ID from completed VM creation job result data."""
        result_data = vm_job.parameters.get("result_data", {})
        vm_id = result_data.get("vm_id")
        return str(vm_id).strip() if vm_id else None

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

        buffer = self._line_buffers.get((job_id, stream.lower()))
        if buffer is None:
            buffer = _SimpleLineBuffer()
            self._line_buffers[(job_id, stream.lower())] = buffer

        lines = buffer.push(payload)
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
            key for key in self._line_buffers if key[0] == job_id]
        for key in pending_keys:
            buffer = self._line_buffers.pop(key)
            trailing = buffer.finalize()
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
                # Get vm_name from enriched metadata
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
        """Create or update job notification using pre-enriched metadata.

        Child jobs (jobs with parent_job_id) do not create notifications since
        the parent job (e.g., managed_deployment) has its own status page with
        links to child jobs.
        """

        # Skip notifications for child jobs - parent job provides the status page
        parent_job_id = job.parameters.get("parent_job_id")
        if parent_job_id:
            return

        # Get enriched metadata (populated in _enrich_job_metadata)
        metadata = job.parameters.get("_metadata", {})
        
        # Extract metadata fields with defaults
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
        else:  # JobStatus.FAILED
            title = f"{action} {resource_type} failed"
            detail = f" Error: {job.error}" if job.error else ""
            message = (
                f"{action} {resource_type} '{resource_label}' "
                f"failed on {location_phrase}.{detail}"
            )
            level = NotificationLevel.ERROR

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

    def _extract_vm_name(self, job: Job) -> Optional[str]:
        """Extract VM name from job parameters.

        Uses enriched metadata from _enrich_job_metadata.
        """
        # Get vm_name from enriched metadata
        metadata = job.parameters.get("_metadata", {})
        vm_name = metadata.get("vm_name")
        if vm_name:
            return str(vm_name)
        
        # For VM jobs, resource_name equals vm_name
        resource_name = metadata.get("resource_name")
        if resource_name and metadata.get("resource_type") == "VM":
            return str(resource_name)
        
        return None

    def _log_agent_request(self, job_id: str, target_host: str, payload: str, script_name: str) -> None:
        """Log raw JSON being sent to host agent.

        Provides visibility into server↔agent communication for debugging and validation.
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

    async def get_running_jobs_count(self) -> int:
        """Return the number of currently running jobs."""
        async with self._lock:
            return sum(
                1 for job in self.jobs.values()
                if job.status == JobStatus.RUNNING
            )

    async def wait_for_running_jobs(
        self,
        timeout: float = 300.0,
        poll_interval: float = 1.0,
    ) -> bool:
        """Wait for all running jobs to complete.

        Args:
            timeout: Maximum time to wait in seconds (default 5 minutes)
            poll_interval: Time between polling checks in seconds

        Returns:
            True if all jobs completed within timeout, False otherwise
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            running_count = await self.get_running_jobs_count()
            if running_count == 0:
                logger.info("All running jobs have completed")
                return True

            logger.debug(
                "Waiting for %d running job(s) to complete",
                running_count,
            )
            await asyncio.sleep(poll_interval)

        running_count = await self.get_running_jobs_count()
        logger.warning(
            "Timed out waiting for jobs to complete; %d job(s) still running",
            running_count,
        )
        return False

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
