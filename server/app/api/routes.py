"""API route handlers."""
import json
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from typing import List, Optional
from datetime import datetime
import secrets

from ..core.models import (
    Host, VM, Job, VMDeleteRequest, InventoryResponse,
    HealthResponse, NotificationsResponse, JobSubmission,
    AboutResponse, BuildInfo,
)
from ..core.auth import get_current_user, oauth
from ..core.config import settings, get_config_validation_result
from ..core.build_info import build_metadata
from ..core.job_schema import (
    SchemaValidationError,
    get_job_schema,
    validate_job_submission,
)
from ..services.inventory_service import inventory_service
from ..services.job_service import job_service
from ..services.host_deployment_service import host_deployment_service
from ..services.notification_service import notification_service
from ..services.websocket_service import websocket_manager

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/healthz", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=build_metadata.version,
        timestamp=datetime.utcnow(),
        build=_current_build_info(),
    )


@router.get("/readyz", response_model=HealthResponse, tags=["Health"])
async def readiness_check():
    """Readiness check endpoint."""

    # When startup detected configuration errors we still want the
    # readiness probe to succeed so that ingress routes requests to the
    # application and the user can see the configuration warning page.
    config_result = get_config_validation_result()
    if config_result and config_result.has_errors:
        return HealthResponse(
            status="config_error",
            version=build_metadata.version,
            timestamp=datetime.utcnow(),
            build=_current_build_info(),
        )

    # Otherwise ensure the inventory service has successfully completed
    # an initial refresh before reporting ready.
    if not inventory_service.last_refresh:
        if host_deployment_service.is_startup_in_progress():
            readiness_status = "deploying_agents"
        else:
            readiness_status = "initializing"

        return HealthResponse(
            status=readiness_status,
            version=build_metadata.version,
            timestamp=datetime.utcnow(),
            build=_current_build_info(),
        )

    return HealthResponse(
        status="ready",
        version=build_metadata.version,
        timestamp=datetime.utcnow(),
        build=_current_build_info(),
    )


@router.get("/api/v1/about", response_model=AboutResponse, tags=["About"])
async def get_about(user: dict = Depends(get_current_user)):
    """Return metadata for the About screen."""

    return AboutResponse(
        name=settings.app_name,
        description="Hyper-V Virtual Machine Management Platform",
        build=_current_build_info(),
    )


@router.get("/api/v1/inventory", response_model=InventoryResponse, tags=["Inventory"])
async def get_inventory(user: dict = Depends(get_current_user)):
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
async def list_hosts(user: dict = Depends(get_current_user)):
    """List all Hyper-V hosts."""
    return inventory_service.get_all_hosts()


@router.get("/api/v1/hosts/{hostname}/vms", response_model=List[VM], tags=["Hosts"])
async def list_host_vms(hostname: str, user: dict = Depends(get_current_user)):
    """List VMs on a specific host."""
    return inventory_service.get_host_vms(hostname)


@router.get("/api/v1/vms", response_model=List[VM], tags=["VMs"])
async def list_vms(user: dict = Depends(get_current_user)):
    """List all VMs across all hosts."""
    return inventory_service.get_all_vms()


@router.get("/api/v1/vms/{hostname}/{vm_name}", response_model=VM, tags=["VMs"])
async def get_vm(hostname: str, vm_name: str, user: dict = Depends(get_current_user)):
    """Get details of a specific VM."""
    vm = inventory_service.get_vm(hostname, vm_name)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM {vm_name} not found on host {hostname}"
        )

    return vm


@router.get("/api/v1/schema/job-inputs", tags=["Schema"])
async def get_job_input_schema(user: dict = Depends(get_current_user)):
    """Return the active job input schema."""
    return get_job_schema()


@router.post("/api/v1/jobs/provision", response_model=Job, tags=["Jobs"])
async def submit_provisioning_job(
    submission: JobSubmission, user: dict = Depends(get_current_user)
):
    """Accept a schema-driven provisioning request."""

    schema = get_job_schema()
    if submission.schema_version != schema.get("version"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Schema version mismatch",
                "expected": schema.get("version"),
                "received": submission.schema_version,
            },
        )

    try:
        validated_values = validate_job_submission(submission.values, schema)
    except SchemaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"errors": exc.errors})

    if not host_deployment_service.is_provisioning_available():
        summary = host_deployment_service.get_startup_summary()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Provisioning agents are still deploying. VM provisioning is temporarily unavailable.",
                "agent_deployment": summary,
            },
        )

    target_host = (submission.target_host or "").strip()
    if not target_host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target host is required",
        )

    connected_hosts = inventory_service.get_connected_hosts()
    host_match = next((host for host in connected_hosts if host.hostname == target_host), None)
    if not host_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {target_host} is not currently connected",
        )

    vm_name = validated_values.get("vm_name")
    if vm_name:
        existing_vm = inventory_service.get_vm(target_host, vm_name)
        if existing_vm:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"VM {vm_name} already exists on host {target_host}",
            )

    schema_id = schema.get("id", "vm-provisioning") if schema else "vm-provisioning"
    job_payload = {
        "schema_id": schema_id,
        "schema_version": submission.schema_version,
        "fields": validated_values,
    }
    job = await job_service.submit_provisioning_job(submission, job_payload, target_host)
    return job


@router.post("/api/v1/vms/delete", response_model=Job, tags=["VMs"])
async def delete_vm(request: VMDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete a VM."""
    # Check if VM exists
    vm = inventory_service.get_vm(request.hyperv_host, request.vm_name)
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM {request.vm_name} not found on host {request.hyperv_host}"
        )

    # Create job
    job = await job_service.submit_delete_job(request)
    return job


@router.get("/api/v1/jobs", response_model=List[Job], tags=["Jobs"])
async def list_jobs(user: dict = Depends(get_current_user)):
    """List all jobs."""
    return await job_service.get_all_jobs()


@router.get("/api/v1/jobs/{job_id}", response_model=Job, tags=["Jobs"])
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    """Get job details."""
    job = await job_service.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    return job


@router.get("/api/v1/notifications", response_model=NotificationsResponse, tags=["Notifications"])
async def get_notifications(
    limit: Optional[int] = None,
    unread_only: bool = False,
    user: dict = Depends(get_current_user)
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
    user: dict = Depends(get_current_user)
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
async def mark_all_notifications_read(user: dict = Depends(get_current_user)):
    """Mark all notifications as read."""
    count = notification_service.mark_all_read()
    return {"message": f"Marked {count} notifications as read"}


@router.delete("/api/v1/notifications/{notification_id}", tags=["Notifications"])
async def delete_notification(
    notification_id: str,
    user: dict = Depends(get_current_user)
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

        # Extract both tokens - use ID token for authentication, access token for API calls
        access_token = token.get("access_token")
        id_token = token.get("id_token")

        logger.info(
            f"OAuth callback received - access_token: {'present' if access_token else 'missing'}, id_token: {'present' if id_token else 'missing'}")

        # For OIDC authentication, we should validate the ID token, not the access token
        auth_token = id_token or access_token
        if not auth_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No authentication token received (neither id_token nor access_token)"
            )

        # Validate the token before storing
        try:
            from ..core.auth import validate_oidc_token
            logger.info(
                f"Attempting to validate {'ID token' if id_token else 'access token'}")
            user_info = await validate_oidc_token(auth_token)

            # Check for required role
            user_roles = user_info.get("roles", [])
            if settings.oidc_role_name not in user_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User does not have required role: {settings.oidc_role_name}",
                )
        except Exception as e:
            logger.error(
                f"Token validation failed in OAuth callback: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Token validation failed: {type(e).__name__}: {str(e)}"
            )

        # Store minimal authentication data to prevent large session cookies
        # that exceed nginx header buffer limits
        request.session["user_info"] = {
            "preferred_username": user_info.get("preferred_username"),
            "sub": user_info.get("sub"),
            "roles": user_info.get("roles", []),
            "authenticated": True,
            "auth_timestamp": datetime.now().isoformat()
        }

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
                                "roles": user_info.get("roles", [])
                            }
                        }
                else:
                    response_data = {
                        "authenticated": True,
                        "user": {
                            "sub": user_info.get("sub"),
                            "preferred_username": user_info.get("preferred_username"),
                            "roles": user_info.get("roles", [])
                        }
                    }
            except Exception as e:
                # Session is invalid, clear it
                request.session.pop("user_info", None)
                response_data = {"authenticated": False,
                                 "reason": f"Session error: {str(e)}"}

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


@router.post("/auth/logout", tags=["Authentication"])
async def logout(request: Request):
    """Logout and clear session."""
    # Clear session data
    request.session.clear()

    return {"message": "Logged out successfully"}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates with authentication.

    Security: Authentication is performed before accepting the connection,
    ensuring only valid clients complete the WebSocket protocol upgrade.
    """
    client_id = str(uuid.uuid4())
    client_ip = websocket.client.host if websocket.client else "unknown"
    connection_start = datetime.utcnow()
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
                connection_age = (datetime.utcnow() -
                                  connection_start).total_seconds()
                if connection_age > MAX_CONNECTION_TIME:
                    logger.info(
                        f"WebSocket connection time limit reached for {client_id} ({username})")
                    await websocket.close(code=1000, reason="Connection time limit reached")
                    break

                data = await websocket.receive_json()
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
    from ..core.auth import authenticate_with_token, validate_session_data, get_dev_user

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
            if user:
                username = user.get('preferred_username', 'unknown')
                logger.info(
                    f"WebSocket session auth successful for "
                    f"{username} from {client_ip}")
                return user
    except Exception as e:
        logger.debug(
            f"Error accessing WebSocket session from {client_ip}: {e}")

    # Try token from query parameter (for API clients)
    token = websocket.query_params.get("token")
    if token:
        try:
            # Use shared token authentication logic
            user = await authenticate_with_token(token, client_ip)
            if user:
                username = user.get('preferred_username', 'api-service')
                logger.info(
                    f"WebSocket token auth successful for "
                    f"{username} from {client_ip}")
                return user
        except Exception as e:
            logger.error(
                f"WebSocket token authentication failed from {client_ip}: {e}")

    logger.warning(
        f"WebSocket authentication failed: no valid credentials "
        f"from {client_ip}")
    return None
