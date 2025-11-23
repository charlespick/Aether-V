"""API route handlers."""
import asyncio
import base64
import copy
import json
import logging
import traceback
import secrets
import uuid
import zlib
from urllib.parse import urlencode, urlsplit, urlunsplit
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Awaitable, Callable, Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from ..core.models import (
    Host,
    VM,
    VMDisk,
    VMNetworkAdapter,
    Job,
    VMDeleteRequest,
    InventoryResponse,
    HealthResponse,
    NotificationsResponse,
    AboutResponse,
    BuildInfo,
    VMState,
    ServiceDiagnosticsResponse,
    ResourceCreateRequest,
    DiskCreateRequest,
    NicCreateRequest,
    ResourceUpdateRequest,
    VMInitializationRequest,
    NoopTestRequest,
    JobResult,
)
from ..core.pydantic_models import (
    ManagedDeploymentRequest,
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
)
from ..core.auth import (
    Permission,
    authenticate_with_token,
    enrich_identity,
    get_dev_user,
    get_identity_display_name,
    has_permission,
    oauth,
    require_permission,
    validate_oidc_token,
    validate_session_data,
    get_end_session_endpoint,
)
from ..core.config import settings, get_config_validation_result
from ..core.build_info import build_metadata
from ..services.inventory_service import inventory_service
from ..services.job_service import job_service
from ..services.host_deployment_service import host_deployment_service
from ..services.notification_service import notification_service
from ..services.vm_control_service import (
    vm_control_service,
    VMActionResult,
    VMControlError,
)
from ..services.websocket_service import websocket_manager
from ..services.remote_task_service import remote_task_service

logger = logging.getLogger(__name__)

_LOGOUT_TOKEN_PREFIX = "enc:"


def _encode_logout_token(id_token: str) -> str:
    """Compress and encode an ID token for compact session storage.

    Returns the compressed and base64-encoded token with a prefix if it's smaller
    than the original, otherwise returns the original token unmodified.
    """
    compressed = zlib.compress(id_token.encode("utf-8"))
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii")

    # Only use the encoded representation when it is smaller than the original
    if len(encoded) + len(_LOGOUT_TOKEN_PREFIX) < len(id_token):
        return f"{_LOGOUT_TOKEN_PREFIX}{encoded}"

    return id_token


def _decode_logout_token(packed_token: Optional[str]) -> Optional[str]:
    """Decode a previously encoded logout token, handling legacy formats."""

    if not packed_token:
        return None

    if packed_token.startswith(_LOGOUT_TOKEN_PREFIX):
        payload = packed_token[len(_LOGOUT_TOKEN_PREFIX):]
        try:
            compressed = base64.urlsafe_b64decode(payload.encode("ascii"))
            return zlib.decompress(compressed).decode("utf-8")
        except (ValueError, zlib.error, UnicodeDecodeError):
            logger.warning("Failed to decode stored logout token")
            return None

    return packed_token


router = APIRouter()


@dataclass(frozen=True)
class VMActionRule:
    """Definition for a VM lifecycle action."""

    executor: Callable[[str, str], Awaitable[VMActionResult]]
    allowed_states: tuple[VMState, ...]
    label: str
    success_message: str


VM_ACTION_RULES: Dict[str, VMActionRule] = {
    "start": VMActionRule(
        executor=vm_control_service.start_vm,
        allowed_states=(VMState.OFF, VMState.PAUSED, VMState.SAVED),
        label="start",
        success_message="Start command accepted for VM {vm_name}.",
    ),
    "shutdown": VMActionRule(
        executor=vm_control_service.shutdown_vm,
        allowed_states=(VMState.RUNNING,),
        label="shut down",
        success_message="Shutdown command accepted for VM {vm_name}.",
    ),
    "stop": VMActionRule(
        executor=vm_control_service.stop_vm,
        allowed_states=(VMState.RUNNING, VMState.PAUSED, VMState.SAVED),
        label="stop",
        success_message="Stop command accepted for VM {vm_name}.",
    ),
    "reset": VMActionRule(
        executor=vm_control_service.reset_vm,
        allowed_states=(VMState.RUNNING,),
        label="reset",
        success_message="Reset command accepted for VM {vm_name}.",
    ),
}


def _normalize_vm_state(state: Optional[object]) -> VMState:
    """Return a VMState enum for the provided value."""

    if isinstance(state, VMState):
        return state
    if isinstance(state, str):
        normalized = state.strip().lower()
        for candidate in VMState:
            if candidate.value.lower() == normalized:
                return candidate
    return VMState.UNKNOWN


def _ensure_connected_host(hostname: str) -> None:
    """Validate that the specified host is connected."""

    host_record = inventory_service.hosts.get(hostname)
    if not host_record or not host_record.connected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Host {hostname} is not currently connected",
        )


def _get_vm_or_404(vm_id: str) -> VM:
    """Return a VM by ID or raise a 404 error."""

    vm = inventory_service.get_vm_by_id(vm_id)
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM with ID {vm_id} not found",
        )
    return vm


def _find_vm_disk(vm: VM, disk_id: str) -> Optional[VMDisk]:
    """Locate a disk by ID on a VM."""

    return next((disk for disk in vm.disks if disk.id == disk_id), None)


def _find_vm_nic(vm: VM, nic_id: str) -> Optional[VMNetworkAdapter]:
    """Locate a NIC by ID on a VM."""

    return next((nic for nic in vm.networks if nic.id == nic_id), None)


async def _handle_vm_action(
    action: str, hostname: str, vm_name: str
) -> Dict[str, str]:
    """Execute a lifecycle action for the specified VM."""

    rule = VM_ACTION_RULES[action]
    vm = inventory_service.get_vm(hostname, vm_name)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": f"VM {vm_name} not found on host {hostname}",
            },
        )

    current_state = _normalize_vm_state(vm.state)
    if current_state not in rule.allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"Cannot {rule.label} VM {vm.name} while it is in state "
                    f"{current_state.value}."
                ),
                "vm_state": current_state.value,
            },
        )

    try:
        await rule.executor(hostname, vm_name)
    except VMControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": (
                    f"Failed to {rule.label} VM {vm.name}: {exc.message}"
                ),
            },
        ) from exc

    asyncio.create_task(inventory_service.refresh_inventory())

    return {
        "status": "accepted",
        "action": action,
        "message": rule.success_message.format(vm_name=vm.name),
        "previous_state": current_state.value,
    }


def _current_build_info() -> BuildInfo:
    """Return build metadata formatted for API responses."""

    return BuildInfo(
        version=build_metadata.version,
        source_control=build_metadata.source_control,
        git_commit=build_metadata.git_commit,
        git_ref=build_metadata.git_ref,
        git_state=build_metadata.git_state,
        build_time=build_metadata.build_time,
        build_host=build_metadata.build_host,
    )


def _application_base_url(request: Request) -> str:
    """Construct the base application URL respecting HTTPS enforcement settings."""

    scheme = "https" if settings.oidc_force_https else request.url.scheme
    host_header = request.headers.get("host")
    if host_header:
        return f"{scheme}://{host_header.rstrip('/')}"

    base_url = str(request.base_url).rstrip("/")
    if settings.oidc_force_https and base_url.startswith("http://"):
        parts = urlsplit(base_url)
        return urlunsplit(("https", parts.netloc, "", "", ""))
    return base_url


def _ensure_absolute_url(request: Request, target: Optional[str]) -> str:
    """Ensure the provided URL is absolute by using the current request context."""

    if not target:
        return f"{_application_base_url(request)}/"

    parsed = urlsplit(target)
    if parsed.scheme and parsed.netloc:
        return target

    base_url = _application_base_url(request)
    if target.startswith("/"):
        return f"{base_url}{target}"

    return f"{base_url}/{target}"


def _build_post_logout_redirect_url(request: Request) -> str:
    """Determine where users should be sent after a logout completes."""

    configured = settings.oidc_post_logout_redirect_uri
    if configured:
        return _ensure_absolute_url(request, configured)

    return f"{_application_base_url(request)}/"


def _build_idp_logout_url(
    request: Request,
    logout_context: Optional[Dict[str, str]],
    post_logout_redirect: str,
) -> Optional[str]:
    """Construct an IdP logout URL when single logout is supported."""

    context = logout_context or {}
    endpoint = context.get(
        "end_session_endpoint") or get_end_session_endpoint()
    if not endpoint:
        return None

    params: Dict[str, str] = {}
    id_token_hint = _decode_logout_token(context.get("id_token"))
    if not id_token_hint:
        legacy_value = context.get("id_token_ref")
        if legacy_value:
            id_token_hint = _decode_logout_token(legacy_value)
    if id_token_hint:
        params["id_token_hint"] = id_token_hint

    if post_logout_redirect:
        params["post_logout_redirect_uri"] = post_logout_redirect

    # Reuse any stored logout state where available to appease strict providers
    state = context.get("state") or context.get("session_state")
    if state:
        params["state"] = state

    if not params:
        return endpoint

    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


@router.get("/healthz", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=build_metadata.version,
        timestamp=datetime.now(timezone.utc),
        build=_current_build_info(),
    )


@router.get("/readyz", response_model=HealthResponse, tags=["Health"])
async def readiness_check(response: Response):
    """Readiness check endpoint."""

    # When startup detected configuration errors we still want the
    # readiness probe to succeed so that ingress routes requests to the
    # application and the user can see the configuration warning page.
    config_result = get_config_validation_result()
    if config_result and config_result.has_errors:
        response.status_code = status.HTTP_200_OK
        return HealthResponse(
            status="config_error",
            version=build_metadata.version,
            timestamp=datetime.now(timezone.utc),
            build=_current_build_info(),
        )

    readiness_status = "ready"

    response.status_code = status.HTTP_200_OK
    return HealthResponse(
        status=readiness_status,
        version=build_metadata.version,
        timestamp=datetime.now(timezone.utc),
        build=_current_build_info(),
    )


@router.get(
    "/api/v1/diagnostics/services",
    response_model=ServiceDiagnosticsResponse,
    tags=["Diagnostics"],
)
async def get_service_diagnostics(
    user: dict = Depends(require_permission(Permission.ADMIN)),
):
    """Return operational diagnostics for remote task and background services."""

    remote_metrics = remote_task_service.get_metrics()
    job_metrics = await job_service.get_metrics()
    inventory_metrics = inventory_service.get_metrics()
    host_metrics = await host_deployment_service.get_metrics()

    return ServiceDiagnosticsResponse(
        remote_tasks=remote_metrics,
        jobs=job_metrics,
        inventory=inventory_metrics,
        host_deployment=host_metrics,
    )


@router.get("/api/v1/about", response_model=AboutResponse, tags=["About"])
async def get_about(user: dict = Depends(require_permission(Permission.READER))):
    """Return metadata for the About screen."""

    return AboutResponse(
        name=settings.app_name,
        description="Hyper-V Virtual Machine Management Platform",
        build=_current_build_info(),
    )


@router.get("/api/v1/inventory", response_model=InventoryResponse, tags=["Inventory"])
async def get_inventory(user: dict = Depends(require_permission(Permission.READER))):
    """Get complete inventory of clusters, hosts and VMs."""
    clusters = inventory_service.get_all_clusters()
    hosts = inventory_service.get_connected_hosts()
    vms = inventory_service.get_all_vms()
    disconnected_hosts = inventory_service.get_disconnected_hosts()

    return InventoryResponse(
        clusters=clusters,
        hosts=hosts,
        vms=vms,
        disconnected_hosts=disconnected_hosts,
        total_hosts=len(hosts) + len(disconnected_hosts),
        total_vms=len(vms),
        total_clusters=len(clusters),
        disconnected_count=len(disconnected_hosts),
        last_refresh=inventory_service.last_refresh
    )


@router.get("/api/v1/hosts", response_model=List[Host], tags=["Hosts"])
async def list_hosts(user: dict = Depends(require_permission(Permission.READER))):
    """List all Hyper-V hosts."""
    return inventory_service.get_all_hosts()


@router.get("/api/v1/hosts/{hostname}/vms", response_model=List[VM], tags=["Hosts"])
async def list_host_vms(hostname: str, user: dict = Depends(require_permission(Permission.READER))):
    """List VMs on a specific host."""
    return inventory_service.get_host_vms(hostname)


@router.get("/api/v1/vms/by-id/{vm_id}", response_model=VM, tags=["VMs"])
async def get_vm_by_id(vm_id: str, user: dict = Depends(require_permission(Permission.READER))):
    """Get details of a specific VM by its ID."""
    vm = inventory_service.get_vm_by_id(vm_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM with ID {vm_id} not found"
        )

    return vm


@router.get("/api/v1/vms", response_model=List[VM], tags=["VMs"])
async def list_vms(user: dict = Depends(require_permission(Permission.READER))):
    """List all VMs across all hosts."""
    return inventory_service.get_all_vms()


@router.post(
    "/api/v1/vms/{hostname}/{vm_name}/start",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["VMs"],
)
async def start_vm_action(
    hostname: str,
    vm_name: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Start a powered-off virtual machine."""

    return await _handle_vm_action("start", hostname, vm_name)


@router.post(
    "/api/v1/vms/{hostname}/{vm_name}/shutdown",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["VMs"],
)
async def shutdown_vm_action(
    hostname: str,
    vm_name: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Shut down a running virtual machine via guest OS request."""

    return await _handle_vm_action("shutdown", hostname, vm_name)


@router.post(
    "/api/v1/vms/{hostname}/{vm_name}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["VMs"],
)
async def stop_vm_action(
    hostname: str,
    vm_name: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Immediately turn off a virtual machine."""

    return await _handle_vm_action("stop", hostname, vm_name)


@router.post(
    "/api/v1/vms/{hostname}/{vm_name}/reset",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["VMs"],
)
async def reset_vm_action(
    hostname: str,
    vm_name: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Reset (power cycle) a running virtual machine."""

    return await _handle_vm_action("reset", hostname, vm_name)


@router.post("/api/v1/vms/delete", response_model=Job, tags=["VMs"])
async def delete_vm(
    request: VMDeleteRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Delete a VM."""
    # Check if VM exists
    vm = inventory_service.get_vm(request.hyperv_host, request.vm_name)
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM {request.vm_name} not found on host {request.hyperv_host}"
        )

    if vm.host != request.hyperv_host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"VM {request.vm_name} is tracked on host {vm.host}, not {request.hyperv_host}"
            ),
        )

    host_record = inventory_service.hosts.get(request.hyperv_host)
    if not host_record or not host_record.connected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Host {request.hyperv_host} is not currently connected",
        )

    if vm.state != VMState.OFF and not request.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Virtual machine must be turned off before deletion. "
                "Set force=true to override when using the API."
            ),
        )

    # Create job
    job = await job_service.submit_delete_job(request)
    return job


@router.get("/api/v1/jobs", response_model=List[Job], tags=["Jobs"])
async def list_jobs(user: dict = Depends(require_permission(Permission.READER))):
    """List all jobs."""
    return await job_service.get_all_jobs()


@router.get("/api/v1/jobs/{job_id}", response_model=Job, tags=["Jobs"])
async def get_job(
    job_id: str,
    user: dict = Depends(require_permission(Permission.READER)),
):
    """Get job details."""
    job = await job_service.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    return job


# New Resource-based API endpoints

@router.get("/api/v1/resources/vms", response_model=List[VM], tags=["Resources"])
async def list_vm_resources(
    user: dict = Depends(require_permission(Permission.READER)),
):
    """List all VM resources."""

    return inventory_service.get_all_vms()


@router.get(
    "/api/v1/resources/vms/{vm_id}", response_model=VM, tags=["Resources"]
)
async def get_vm_resource(
    vm_id: str, user: dict = Depends(require_permission(Permission.READER))
):
    """Fetch a VM resource by its ID."""

    return _get_vm_or_404(vm_id)


@router.post("/api/v1/resources/vms", response_model=JobResult, tags=["Resources"])
async def create_vm_resource(
    request: ResourceCreateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Create a new virtual machine (without disk or NIC)."""

    # Validate using Pydantic instead of schema
    try:
        vm_spec = VmSpec(**request.values)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]}
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. VM creation is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    connected_hosts = inventory_service.get_connected_hosts()
    host_match = next(
        (host for host in connected_hosts if host.hostname == target_host), None)
    if not host_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {target_host} is not currently connected",
        )

    vm_name = vm_spec.vm_name
    if vm_name:
        existing_vm = inventory_service.get_vm(target_host, vm_name)
        if existing_vm:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"VM {vm_name} already exists on host {target_host}",
            )

    # Use the validated Pydantic model's dict for the job payload
    job_definition = {
        "schema": {
            "id": "vm-create",
            "version": 1,  # Static version, not schema-based
        },
        "fields": vm_spec.model_dump(),
    }

    job = await job_service.submit_resource_job(
        job_type="create_vm",
        schema_id="vm-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"VM creation job queued for host {target_host}",
    )


@router.put(
    "/api/v1/resources/vms/{vm_id}", response_model=JobResult, tags=["Resources"]
)
async def update_vm_resource(
    vm_id: str,
    request: ResourceUpdateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Update an existing virtual machine."""

    vm = _get_vm_or_404(vm_id)

    # Validate using Pydantic instead of schema
    try:
        vm_spec = VmSpec(**request.values)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]},
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. VM updates are temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    _ensure_connected_host(target_host)

    # Add vm_id to the validated values
    validated_values = vm_spec.model_dump()
    validated_values["vm_id"] = vm_id

    job_definition = {
        "schema": {
            "id": "vm-create",
            "version": 1,
        },
        "fields": validated_values,
    }

    job = await job_service.submit_resource_job(
        job_type="update_vm",
        schema_id="vm-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"VM update job queued for {vm.name}",
    )


@router.delete(
    "/api/v1/resources/vms/{vm_id}", response_model=JobResult, tags=["Resources"]
)
async def delete_vm_resource(
    vm_id: str,
    force: bool = False,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Delete a VM by ID using the job queue."""

    vm = _get_vm_or_404(vm_id)
    _ensure_connected_host(vm.host)

    normalized_state = _normalize_vm_state(vm.state)
    if normalized_state != VMState.OFF and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Virtual machine must be turned off before deletion. "
                "Set force=true to override when using the API."
            ),
        )

    delete_request = VMDeleteRequest(
        vm_name=vm.name, hyperv_host=vm.host, force=force
    )
    job = await job_service.submit_delete_job(delete_request)

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"VM deletion job queued for {vm.name}",
    )


@router.post("/api/v1/resources/disks", response_model=JobResult, tags=["Resources"])
async def create_disk_resource(
    request: DiskCreateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Create and attach a new disk to an existing VM."""

    # Validate using Pydantic instead of schema
    try:
        disk_spec = DiskSpec(**request.values)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]}
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. Disk creation is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    connected_hosts = inventory_service.get_connected_hosts()
    host_match = next(
        (host for host in connected_hosts if host.hostname == target_host), None)
    if not host_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {target_host} is not currently connected",
        )

    # Validate that VM exists
    vm_id = disk_spec.vm_id
    if not vm_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VM ID is required for disk creation",
        )

    vm = _get_vm_or_404(vm_id)
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    job_definition = {
        "schema": {
            "id": "disk-create",
            "version": 1,
        },
        "fields": disk_spec.model_dump(),
    }

    job = await job_service.submit_resource_job(
        job_type="create_disk",
        schema_id="disk-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Disk creation job queued for VM {vm_id}",
    )


@router.get(
    "/api/v1/resources/vms/{vm_id}/disks",
    response_model=List[VMDisk],
    tags=["Resources"],
)
async def list_vm_disks(
    vm_id: str, user: dict = Depends(require_permission(Permission.READER))
):
    """List disks attached to a VM."""

    vm = _get_vm_or_404(vm_id)
    return vm.disks


@router.get(
    "/api/v1/resources/vms/{vm_id}/disks/{disk_id}",
    response_model=VMDisk,
    tags=["Resources"],
)
async def get_vm_disk(
    vm_id: str,
    disk_id: str,
    user: dict = Depends(require_permission(Permission.READER)),
):
    """Get a specific disk attached to a VM."""

    vm = _get_vm_or_404(vm_id)
    disk = _find_vm_disk(vm, disk_id)
    if not disk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disk {disk_id} not found on VM {vm_id}",
        )
    return disk


@router.put(
    "/api/v1/resources/vms/{vm_id}/disks/{disk_id}",
    response_model=JobResult,
    tags=["Resources"],
)
async def update_disk_resource(
    vm_id: str,
    disk_id: str,
    request: ResourceUpdateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Update an existing disk resource."""

    vm = _get_vm_or_404(vm_id)
    disk = _find_vm_disk(vm, disk_id)
    if not disk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disk {disk_id} not found on VM {vm_id}",
        )

    if request.resource_id != disk_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resource ID in payload does not match disk in path",
        )

    # Validate using Pydantic instead of schema
    try:
        values_with_vm = {**request.values, "vm_id": vm_id}
        disk_spec = DiskSpec(**values_with_vm)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]},
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. Disk updates are temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    _ensure_connected_host(target_host)

    validated_values = disk_spec.model_dump()
    validated_values["resource_id"] = request.resource_id

    job_definition = {
        "schema": {
            "id": "disk-create",
            "version": 1,
        },
        "fields": validated_values,
    }

    job = await job_service.submit_resource_job(
        job_type="update_disk",
        schema_id="disk-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Disk update job queued for VM {vm_id}",
    )


@router.delete(
    "/api/v1/resources/vms/{vm_id}/disks/{disk_id}",
    response_model=JobResult,
    tags=["Resources"],
)
async def delete_disk_resource(
    vm_id: str,
    disk_id: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Delete a disk resource from a VM."""

    vm = _get_vm_or_404(vm_id)
    disk = _find_vm_disk(vm, disk_id)
    if not disk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disk {disk_id} not found on VM {vm_id}",
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. Disk deletion is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    _ensure_connected_host(vm.host)

    job_definition = {
        "schema": {"id": "disk-delete", "version": 1},
        "fields": {"vm_id": vm_id, "resource_id": disk_id},
    }

    job = await job_service.submit_resource_job(
        job_type="delete_disk",
        schema_id="disk-delete",
        payload=job_definition,
        target_host=vm.host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Disk deletion job queued for VM {vm_id}",
    )


@router.post("/api/v1/resources/nics", response_model=JobResult, tags=["Resources"])
async def create_nic_resource(
    request: NicCreateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Create and attach a new network adapter to an existing VM."""

    # Validate using Pydantic instead of schema
    try:
        nic_spec = NicSpec(**request.values)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]}
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. NIC creation is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    connected_hosts = inventory_service.get_connected_hosts()
    host_match = next(
        (host for host in connected_hosts if host.hostname == target_host), None)
    if not host_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {target_host} is not currently connected",
        )

    # Validate that VM exists
    vm_id = nic_spec.vm_id
    if not vm_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VM ID is required for NIC creation",
        )

    vm = _get_vm_or_404(vm_id)
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    job_definition = {
        "schema": {
            "id": "nic-create",
            "version": 1,
        },
        "fields": nic_spec.model_dump(),
    }

    job = await job_service.submit_resource_job(
        job_type="create_nic",
        schema_id="nic-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"NIC creation job queued for VM {vm_id}",
    )


@router.get(
    "/api/v1/resources/vms/{vm_id}/nics",
    response_model=List[VMNetworkAdapter],
    tags=["Resources"],
)
async def list_vm_nics(
    vm_id: str, user: dict = Depends(require_permission(Permission.READER))
):
    """List NICs attached to a VM."""

    vm = _get_vm_or_404(vm_id)
    return vm.networks


@router.get(
    "/api/v1/resources/vms/{vm_id}/nics/{nic_id}",
    response_model=VMNetworkAdapter,
    tags=["Resources"],
)
async def get_vm_nic(
    vm_id: str,
    nic_id: str,
    user: dict = Depends(require_permission(Permission.READER)),
):
    """Get a specific NIC attached to a VM."""

    vm = _get_vm_or_404(vm_id)
    nic = _find_vm_nic(vm, nic_id)
    if not nic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NIC {nic_id} not found on VM {vm_id}",
        )
    return nic


@router.put(
    "/api/v1/resources/vms/{vm_id}/nics/{nic_id}",
    response_model=JobResult,
    tags=["Resources"],
)
async def update_nic_resource(
    vm_id: str,
    nic_id: str,
    request: ResourceUpdateRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Update an existing NIC resource."""

    vm = _get_vm_or_404(vm_id)
    nic = _find_vm_nic(vm, nic_id)
    if not nic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NIC {nic_id} not found on VM {vm_id}",
        )

    if request.resource_id != nic_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resource ID in payload does not match NIC in path",
        )

    # Validate using Pydantic instead of schema
    try:
        values_with_vm = {**request.values, "vm_id": vm_id}
        nic_spec = NicSpec(**values_with_vm)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": [str(exc)]},
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. NIC updates are temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    _ensure_connected_host(target_host)

    validated_values = nic_spec.model_dump()
    validated_values["resource_id"] = request.resource_id

    job_definition = {
        "schema": {
            "id": "nic-create",
            "version": 1,
        },
        "fields": validated_values,
    }

    job = await job_service.submit_resource_job(
        job_type="update_nic",
        schema_id="nic-create",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"NIC update job queued for VM {vm_id}",
    )


@router.delete(
    "/api/v1/resources/vms/{vm_id}/nics/{nic_id}",
    response_model=JobResult,
    tags=["Resources"],
)
async def delete_nic_resource(
    vm_id: str,
    nic_id: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Delete a NIC resource from a VM."""

    vm = _get_vm_or_404(vm_id)
    nic = _find_vm_nic(vm, nic_id)
    if not nic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NIC {nic_id} not found on VM {vm_id}",
        )

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. NIC deletion is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    _ensure_connected_host(vm.host)

    job_definition = {
        "schema": {"id": "nic-delete", "version": 1},
        "fields": {"vm_id": vm_id, "resource_id": nic_id},
    }

    job = await job_service.submit_resource_job(
        job_type="delete_nic",
        schema_id="nic-delete",
        payload=job_definition,
        target_host=vm.host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"NIC deletion job queued for VM {vm_id}",
    )


@router.post(
    "/api/v1/resources/vms/{vm_id}/initialize",
    response_model=JobResult,
    tags=["Resources"],
)
async def initialize_vm_resource(
    vm_id: str,
    request: VMInitializationRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Trigger guest initialization for an existing VM."""

    vm = _get_vm_or_404(vm_id)

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. Initialization is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = request.target_host.strip()
    if target_host != vm.host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.name} is tracked on host {vm.host}, not {target_host}",
        )

    _ensure_connected_host(target_host)

    if not request.guest_configuration:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "guest_configuration is required for initialization and must not be empty"
            },
        )

    fields = {"vm_id": vm_id}
    fields.update(request.guest_configuration)
    fields["vm_id"] = vm_id

    if not fields.get("vm_name"):
        fields["vm_name"] = vm.name

    job_definition = {
        "schema": {
            "id": "initialize-vm",
        },
        "fields": fields,
    }

    job = await job_service.submit_resource_job(
        job_type="initialize_vm",
        schema_id="initialize-vm",
        payload=job_definition,
        target_host=target_host,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Initialization job queued for VM {vm_id}",
    )


@router.post("/api/v2/managed-deployments", response_model=JobResult, tags=["Managed Deployments"])
async def create_managed_deployment_v2(
    request: ManagedDeploymentRequest,
    user: dict = Depends(require_permission(Permission.WRITER))
):
    """Create a complete VM deployment using the Pydantic-based protocol.

    This endpoint orchestrates VM creation, disk attachment, NIC attachment, and guest 
    configuration using the JobRequest/JobResult protocol with strict Pydantic validation.

    The workflow:
    1. Validate input with Pydantic (ManagedDeploymentRequest)
    2. Create VM via vm.create operation
    3. Create Disk via disk.create operation
    4. Create NIC via nic.create operation
    5. Generate guest config dict using generate_guest_config()
    6. Send guest config through existing KVP mechanism

    This endpoint bypasses schemas entirely. The request is validated by Pydantic
    and the component operations are executed via the new protocol.
    """

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. VM provisioning is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    # Ensure the target host is connected
    target_host = request.target_host.strip()
    if not target_host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target host is required",
        )

    connected_hosts = inventory_service.get_connected_hosts()
    host_match = next(
        (host for host in connected_hosts if host.hostname == target_host), None)
    if not host_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {target_host} is not currently connected",
        )

    # Check if VM already exists
    vm_name = request.vm_spec.vm_name
    existing_vm = inventory_service.get_vm(target_host, vm_name)
    if existing_vm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm_name} already exists on host {target_host}",
        )

    # Submit the managed deployment job using new protocol
    job = await job_service.submit_managed_deployment_v2_job(
        request=request,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Managed deployment (v2) queued for host {target_host}",
    )


@router.post("/api/v1/noop-test", response_model=JobResult, tags=["Testing"])
async def submit_noop_test(
    request: NoopTestRequest,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Execute a noop-test operation using the JobRequest/JobResult protocol.

    This endpoint validates the round-trip communication between server and host agent
    without performing any actual operations. Useful for testing connectivity and
    protocol compatibility.
    """

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. Noop-test is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    # Ensure the target host is connected
    _ensure_connected_host(request.target_host)

    # Submit the noop-test job
    job = await job_service.submit_noop_test_job(
        target_host=request.target_host,
        resource_spec=request.resource_spec,
        correlation_id=request.correlation_id,
    )

    return JobResult(
        job_id=job.job_id,
        status="queued",
        message=f"Noop-test job queued for host {request.target_host}",
    )


@router.get("/api/v1/notifications", response_model=NotificationsResponse, tags=["Notifications"])
async def get_notifications(
    limit: Optional[int] = None,
    unread_only: bool = False,
    user: dict = Depends(require_permission(Permission.READER)),
):
    """Get notifications."""
    if unread_only:
        notifications = notification_service.get_unread_notifications(limit)
    else:
        notifications = notification_service.get_all_notifications(limit)

    return NotificationsResponse(
        notifications=notifications,
        total_count=notification_service.get_notification_count(),
        unread_count=notification_service.get_unread_count()
    )


@router.put("/api/v1/notifications/{notification_id}/read", tags=["Notifications"])
async def mark_notification_read(
    notification_id: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Mark a notification as read."""
    success = notification_service.mark_notification_read(notification_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )
    return {"message": "Notification marked as read"}


@router.put("/api/v1/notifications/mark-all-read", tags=["Notifications"])
async def mark_all_notifications_read(
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Mark all notifications as read."""
    count = notification_service.mark_all_read()
    return {"message": f"Marked {count} notifications as read"}


@router.delete("/api/v1/notifications/{notification_id}", tags=["Notifications"])
async def delete_notification(
    notification_id: str,
    user: dict = Depends(require_permission(Permission.WRITER)),
):
    """Delete a notification."""
    success = notification_service.delete_notification(notification_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )
    return {"message": "Notification deleted"}


# OIDC Authentication routes
@router.post("/auth/direct-login", tags=["Authentication"])
async def direct_login(request: Request):
    """Create a local session when authentication is disabled."""

    if settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication is enabled; use the identity provider",
        )

    if not settings.allow_dev_auth:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development authentication is not permitted",
        )

    dev_user = get_dev_user()
    now_iso = datetime.now().isoformat()

    request.session["user_info"] = {
        "preferred_username": dev_user.get("preferred_username", "dev-user"),
        "sub": dev_user.get("sub", "dev-user"),
        "name": dev_user.get("preferred_username", "dev-user"),
        "email": dev_user.get("email"),
        "roles": dev_user.get("roles", []),
        "permissions": dev_user.get("permissions", []),
        "identity_type": dev_user.get("identity_type", "user"),
        "auth_type": dev_user.get("auth_type", "dev"),
        "authenticated": True,
        "auth_timestamp": now_iso,
    }

    logger.info("Direct login session established for development access")

    return {"authenticated": True}


@router.get("/auth/login", tags=["Authentication"])
async def login(request: Request):
    """Initiate OIDC login flow."""
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication is disabled"
        )

    if not oauth.oidc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC not configured"
        )

    # Generate state parameter for security
    state = secrets.token_urlsafe(32)

    # Store state in session (you might want to use a more robust session store)
    request.session["oauth_state"] = state

    # Build redirect URI
    redirect_uri = settings.oidc_redirect_uri
    if not redirect_uri:
        # Auto-generate redirect URI
        host = request.headers.get("host", str(
            request.base_url).split("://")[1])
        scheme = "https" if settings.oidc_force_https else request.url.scheme
        redirect_uri = f"{scheme}://{host}/auth/callback"

    # Redirect to OIDC provider
    return await oauth.oidc.authorize_redirect(request, redirect_uri, state=state)


@router.get("/auth/callback", tags=["Authentication"])
async def auth_callback(request: Request):
    """Handle OIDC callback with secure token handling."""
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication is disabled"
        )

    if not oauth.oidc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC not configured"
        )

    try:
        # Get the token from the callback
        token = await oauth.oidc.authorize_access_token(request)

        # Verify state parameter (if stored in session)
        stored_state = request.session.get("oauth_state")
        received_state = request.query_params.get("state")

        if stored_state and stored_state != received_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )

        # Clear the state from session
        request.session.pop("oauth_state", None)

        # Extract both tokens - prefer the access token when present so we can inspect scopes/roles
        access_token = token.get("access_token")
        id_token = token.get("id_token")

        logger.info(
            "OAuth callback received - access_token: %s, id_token: %s",
            "present" if access_token else "missing",
            "present" if id_token else "missing",
        )

        client_ip = request.client.host if request.client else "unknown"
        user_info = None
        validation_errors: List[str] = []

        if access_token:
            try:
                user_info = await authenticate_with_token(access_token, client_ip)
                logger.debug(
                    "Access token provided sufficient permissions for session establishment")
            except HTTPException as exc:
                validation_errors.append(f"access_token:{exc.detail}")
                logger.warning(
                    "Access token validation rejected during OAuth callback from %s: %s",
                    client_ip,
                    exc.detail,
                )
            except Exception as exc:
                validation_errors.append(
                    f"access_token_error:{type(exc).__name__}")
                logger.error(
                    "Access token validation error during OAuth callback from %s: %s",
                    client_ip,
                    exc,
                )

        if not user_info and id_token:
            try:
                logger.info(
                    "Falling back to ID token validation for OAuth callback")
                claims = await validate_oidc_token(id_token)
                enriched = enrich_identity(claims)
                if not enriched.get("permissions"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Authenticated identity lacks required permissions",
                    )
                user_info = enriched
            except HTTPException as exc:
                validation_errors.append(f"id_token:{exc.detail}")
                logger.error(
                    "ID token validation rejected for OAuth callback from %s: %s",
                    client_ip,
                    exc.detail,
                )
            except Exception as exc:
                validation_errors.append(
                    f"id_token_error:{type(exc).__name__}")
                logger.error(
                    "ID token validation error during OAuth callback from %s: %s",
                    client_ip,
                    exc,
                )

        if not user_info:
            detail = "; ".join(
                validation_errors) if validation_errors else "No tokens available"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Unable to establish session: {detail}",
            )

        # Store minimal authentication data to prevent large session cookies
        # that exceed nginx header buffer limits
        request.session["user_info"] = {
            "preferred_username": user_info.get("preferred_username"),
            "sub": user_info.get("sub"),
            "name": user_info.get("name"),
            "email": user_info.get("email"),
            "roles": user_info.get("roles", []),
            "permissions": user_info.get("permissions", []),
            "identity_type": user_info.get("identity_type"),
            "authenticated": True,
            "auth_timestamp": datetime.now().isoformat()
        }

        logout_context: Dict[str, str] = {}
        end_session_endpoint = get_end_session_endpoint()
        if end_session_endpoint:
            logout_context["end_session_endpoint"] = end_session_endpoint
        if id_token:
            logout_context["id_token"] = _encode_logout_token(id_token)

        session_state = token.get("session_state")
        if session_state:
            logout_context["session_state"] = session_state

        if logout_context:
            request.session["oidc_logout"] = logout_context
        else:
            request.session.pop("oidc_logout", None)

        username = user_info.get("preferred_username",
                                 user_info.get("sub", "unknown"))
        logger.info(f"Authentication successful for user: {username}")

        # Redirect to main page
        return RedirectResponse(
            url="/?auth=success",
            status_code=status.HTTP_302_FOUND
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}"
        )


@router.get("/auth/token", tags=["Authentication"])
async def get_auth_token(request: Request):
    """Get authentication status from session."""
    from fastapi import Response

    if not settings.auth_enabled:
        response_data = {"authenticated": False,
                         "reason": "Authentication disabled"}
    else:
        user_info = request.session.get("user_info")

        if not user_info or not user_info.get("authenticated"):
            response_data = {"authenticated": False, "reason": "No session"}
        else:
            # Check if session is still valid (within reasonable time)
            try:
                auth_timestamp = user_info.get("auth_timestamp")
                if auth_timestamp:
                    from datetime import datetime, timedelta
                    auth_time = datetime.fromisoformat(auth_timestamp)
                    if datetime.now() - auth_time > timedelta(hours=24):
                        # Session too old
                        request.session.pop("user_info", None)
                        response_data = {"authenticated": False,
                                         "reason": "Session expired"}
                    else:
                        response_data = {
                            "authenticated": True,
                            "user": {
                                "sub": user_info.get("sub"),
                                "preferred_username": user_info.get("preferred_username"),
                                "name": user_info.get("name"),
                                "email": user_info.get("email"),
                                "roles": user_info.get("roles", []),
                                "permissions": user_info.get("permissions", []),
                                "identity_type": user_info.get("identity_type"),
                            }
                        }
                else:
                    response_data = {
                        "authenticated": True,
                        "user": {
                            "sub": user_info.get("sub"),
                            "preferred_username": user_info.get("preferred_username"),
                            "name": user_info.get("name"),
                            "email": user_info.get("email"),
                            "roles": user_info.get("roles", []),
                            "permissions": user_info.get("permissions", []),
                            "identity_type": user_info.get("identity_type"),
                        }
                    }
            except Exception:
                # Session is invalid, clear it
                request.session.pop("user_info", None)
                # Log the stack trace for debugging, but do not return details to the user
                logger.error(
                    "Exception during session validation:\n%s", traceback.format_exc())
                response_data = {"authenticated": False,
                                 "reason": "Session error"}
    # Create response with cache control headers
    response = Response(
        content=json.dumps(response_data),
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
    return response


@router.api_route("/auth/logout", methods=["POST", "GET"], tags=["Authentication"])
async def logout(request: Request):
    """Logout the current session and optionally initiate IdP single logout."""

    logout_context = request.session.get("oidc_logout")
    post_logout_redirect = _build_post_logout_redirect_url(request)

    idp_logout_url: Optional[str] = None
    if request.method == "POST":
        idp_logout_url = _build_idp_logout_url(
            request, logout_context, post_logout_redirect)
    elif logout_context:
        # Treat GET requests with stored logout context as user-initiated logouts.
        idp_logout_url = _build_idp_logout_url(
            request, logout_context, post_logout_redirect)

    # Clear session data regardless of logout method
    request.session.clear()

    if request.method == "GET":
        target = idp_logout_url or post_logout_redirect
        return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

    payload = {"message": "Logged out successfully"}
    if post_logout_redirect:
        payload["redirect_url"] = post_logout_redirect
    if idp_logout_url:
        payload["idp_logout_url"] = idp_logout_url

    return JSONResponse(payload)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates with authentication.

    Security: Authentication is performed before accepting the connection,
    ensuring only valid clients complete the WebSocket protocol upgrade.
    """
    client_id = str(uuid.uuid4())
    client_ip = websocket.client.host if websocket.client else "unknown"
    connection_start = datetime.now(timezone.utc)
    MAX_CONNECTION_TIME = settings.websocket_timeout

    try:
        # Authenticate BEFORE accepting the WebSocket connection
        # This creates a proper security boundary - only authenticated clients complete the upgrade
        user = await authenticate_websocket(websocket)

        if not user:
            # Reject the connection by closing without accepting
            # This prevents the WebSocket upgrade from completing
            await websocket.close(code=1008, reason="Authentication required")
            logger.warning(
                f"WebSocket authentication failed for client from {client_ip}")
            return

        username = user.get("preferred_username", user.get("sub", "unknown"))
        logger.info(
            f"WebSocket authenticated for user {username} from {client_ip}")

        # Accept and register with connection manager (only after successful authentication)
        connected = await websocket_manager.connect(websocket, client_id)

        if not connected:
            return

        # Send initial state
        try:
            notifications = notification_service.get_all_notifications()
            await websocket_manager.send_personal_message(client_id, {
                "type": "initial_state",
                "data": {
                    "notifications": [
                        {
                            "id": n.id,
                            "title": n.title,
                            "message": n.message,
                            "level": n.level.value,
                            "category": n.category.value,
                            "created_at": n.created_at.isoformat(),
                            "read": n.read,
                            "related_entity": n.related_entity,
                            "metadata": n.metadata,
                        }
                        for n in notifications
                    ],
                    "unread_count": notification_service.get_unread_count()
                }
            })
        except Exception as e:
            logger.error(f"Error sending initial state to {client_id}: {e}")

        # Listen for messages from client
        while True:
            try:
                # Check connection time limit
                connection_age = (datetime.now(timezone.utc) -
                                  connection_start).total_seconds()
                if connection_age > MAX_CONNECTION_TIME:
                    logger.info(
                        f"WebSocket connection time limit reached for {client_id} ({username})")
                    await websocket.close(code=1000, reason="Connection time limit reached")
                    break

                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(), timeout=MAX_CONNECTION_TIME
                    )
                except asyncio.TimeoutError:
                    logger.info(
                        f"WebSocket idle timeout reached for {client_id} ({username})"
                    )
                    await websocket.close(code=1000, reason="Connection idle timeout")
                    break
                await websocket_manager.handle_client_message(client_id, data)
            except WebSocketDisconnect:
                logger.info(f"Client {client_id} ({username}) disconnected")
                break
            except Exception as e:
                logger.error(f"Error processing message from {client_id}: {e}")
                break

    except Exception as e:
        logger.error(
            f"WebSocket error for client {client_id} from {client_ip}: {e}")

    finally:
        await websocket_manager.disconnect(client_id)


async def authenticate_websocket(websocket: WebSocket) -> Optional[dict]:
    """
    Authenticate WebSocket using shared authentication logic.

    Since FastAPI's Depends() doesn't work with WebSocket endpoints,
    we use the shared auth functions from the auth module for consistency.
    """
    client_ip = websocket.client.host if websocket.client else "unknown"

    # Development mode: no authentication required
    if not settings.auth_enabled:
        if not settings.allow_dev_auth:
            logger.error(
                f"Auth disabled but ALLOW_DEV_AUTH not set - "
                f"WebSocket denied from {client_ip}")
            return None
        logger.warning(
            f"WebSocket authentication disabled - "
            f"dev mode access from {client_ip}")
        return get_dev_user()

    # Try session authentication first (for browser clients)
    # SessionMiddleware processes session cookies for WebSocket connections
    try:
        # Access session data from WebSocket (via SessionMiddleware)
        # Session data is stored under "user_info" key
        user_info = websocket.session.get("user_info")
        if user_info:
            # Use shared session validation logic
            user = validate_session_data(user_info, client_ip)
            if user and has_permission(user, Permission.READER):
                username = get_identity_display_name(user)
                logger.info(
                    f"WebSocket session auth successful for "
                    f"{username} from {client_ip}")
                return user
            elif user:
                username = get_identity_display_name(user)
                logger.warning(
                    "WebSocket session auth rejected for %s from %s due to missing reader permission",
                    username,
                    client_ip,
                )
    except Exception as e:
        logger.debug(
            f"Error accessing WebSocket session from {client_ip}: {e}")

    # Try token from query parameter (for API clients)
    token = websocket.query_params.get("token")
    if token:
        try:
            # Use shared token authentication logic
            user = await authenticate_with_token(token, client_ip)
            if user and has_permission(user, Permission.READER):
                username = get_identity_display_name(user)
                logger.info(
                    f"WebSocket token auth successful for "
                    f"{username} from {client_ip}")
                return user
            elif user:
                username = get_identity_display_name(user)
                logger.warning(
                    "WebSocket token auth rejected for %s from %s due to missing reader permission",
                    username,
                    client_ip,
                )
        except HTTPException as exc:
            logger.warning(
                "WebSocket token authentication refused from %s: %s",
                client_ip,
                exc.detail,
            )
            return None
        except Exception as e:
            logger.error(
                f"WebSocket token authentication failed from {client_ip}: {e}")

    logger.warning(
        f"WebSocket authentication failed: no valid credentials "
        f"from {client_ip}")
    return None
