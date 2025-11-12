"""Main application entry point."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import secrets
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .core.config import (
    settings,
    get_config_validation_result,
    set_session_secret,
    AGENT_ARTIFACTS_DIR,
    AGENT_HTTP_MOUNT_PATH,
)
from .core.build_info import build_metadata
from .core.config_validation import run_config_checks
from .api.routes import router
from .services.inventory_service import inventory_service
from .services.host_deployment_service import host_deployment_service
from .services.job_service import job_service
from .services.notification_service import notification_service
from .services.remote_task_service import remote_task_service
from .services.websocket_service import websocket_manager
from .core.job_schema import load_job_schema, get_job_schema, SchemaValidationError

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

PROJECT_GITHUB_URL = "https://github.com/aether-v/Aether-V"
API_REFERENCE_URL = "/docs"


def _build_metadata_payload() -> dict:
    """Serialize build metadata for template consumption."""

    return {
        "version": build_metadata.version,
        "source_control": build_metadata.source_control,
        "git_commit": build_metadata.git_commit,
        "git_ref": build_metadata.git_ref,
        "git_state": build_metadata.git_state,
        "build_time": build_metadata.build_time_iso,
        "build_host": build_metadata.build_host,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Aether-V Server")
    logger.info(f"Version: {build_metadata.version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Authentication enabled: {settings.auth_enabled}")

    try:
        load_job_schema()
    except SchemaValidationError as exc:
        logger.error("Failed to load job schema: %s", "; ".join(exc.errors))
        raise

    config_result = run_config_checks()

    if config_result.has_errors:
        for issue in config_result.errors:
            logger.error("Configuration error: %s", issue.message)
            if issue.hint:
                logger.error("Hint: %s", issue.hint)

    if config_result.has_warnings:
        for issue in config_result.warnings:
            logger.warning("Configuration warning: %s", issue.message)
            if issue.hint:
                logger.warning("Hint: %s", issue.hint)

    remote_started = False
    notifications_started = False
    job_started = False
    inventory_started = False

    await remote_task_service.start()
    remote_started = True

    await notification_service.start()
    notifications_started = True

    # Connect WebSocket manager to notification service
    notification_service.set_websocket_manager(websocket_manager)

    notification_service.publish_startup_configuration_result(config_result)

    await host_deployment_service.start_startup_deployment(
        settings.get_hyperv_hosts_list()
    )

    async def _log_startup_deployment_summary() -> None:
        try:
            await host_deployment_service.wait_for_startup()
            deployment_summary = host_deployment_service.get_startup_summary()
            logger.info(
                "Startup agent deployment finished with status=%s (success=%d failed=%d)",
                deployment_summary.get("status"),
                deployment_summary.get("successful_hosts", 0),
                deployment_summary.get("failed_hosts", 0),
            )
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to record startup deployment summary")

    asyncio.create_task(_log_startup_deployment_summary())

    if not config_result.has_errors:
        await inventory_service.start()
        inventory_started = True
        await job_service.start()
        job_started = True
        logger.info(
            "Application services initialised; inventory refresh will continue in the background"
        )
    else:
        logger.error(
            "Skipping job and inventory service startup because configuration errors were detected."
        )
        logger.info("Application started in configuration warning mode")

    try:
        yield
    finally:
        logger.info("Shutting down application")
        if inventory_started:
            await inventory_service.stop()
        if job_started:
            await job_service.stop()
        if notifications_started:
            await notification_service.stop()
        if remote_started:
            await remote_task_service.stop()
        logger.info("Application stopped")


# Create FastAPI app with docs disabled (we'll serve them with local assets)
app = FastAPI(
    title=settings.app_name,
    version=build_metadata.version,
    description="Lightweight orchestration service for Hyper-V virtual machines",
    lifespan=lifespan,
    docs_url=None,  # Disable default docs
    redoc_url=None,  # Disable default redoc
)

static_dir = Path("app/static")
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
else:  # pragma: no cover - filesystem dependent
    logger.warning(
        "Static assets directory '%s' not found; static routes disabled", static_dir
    )

if AGENT_ARTIFACTS_DIR.is_dir():
    app.mount(
        AGENT_HTTP_MOUNT_PATH,
        StaticFiles(directory=str(AGENT_ARTIFACTS_DIR), html=False),
        name="agent",
    )
else:  # pragma: no cover - filesystem dependent
    logger.warning(
        "Agent artifacts directory '%s' not found; host deployments will be disabled",
        AGENT_ARTIFACTS_DIR,
    )

# Add security headers and audit logging middleware


@app.middleware("http")
async def security_and_audit_middleware(request: Request, call_next):
    """Add security headers and comprehensive audit logging."""
    start_time = time.time()

    # Log incoming request (audit trail)
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    # Don't log sensitive headers
    if settings.debug:
        safe_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ["authorization", "cookie", "x-api-key"]
        }
        logger.debug("Request headers (sanitized): %s", safe_headers)

    logger.info(
        f"Request started: {request.method} {request.url.path} "
        f"from {client_ip} UA: {user_agent[:100]}"
    )

    try:
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        )

        # Add HSTS in production
        if settings.oidc_force_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Audit logging (success)
        process_time = time.time() - start_time
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"Status: {response.status_code} Time: {process_time:.4f}s"
        )

        return response

    except Exception as e:
        # Audit logging (error)
        process_time = time.time() - start_time
        logger.error(
            f"Request failed: {request.method} {request.url.path} "
            f"Error: {str(e)[:200]} Time: {process_time:.4f}s"
        )
        raise


# Add session middleware with enhanced security
# Use secure session configuration for production
# Store the actual session secret so it can be accessed by WebSocket auth
session_secret = settings.session_secret_key
if not session_secret:
    # Generate a secure random secret for this session (will require re-login on restart)
    session_secret = secrets.token_urlsafe(32)
    logger.warning(
        "Generated temporary session secret - set SESSION_SECRET_KEY environment variable for production"
    )

# Store the session secret in the config module so it can be accessed elsewhere
set_session_secret(session_secret)

allowed_same_site_values = {"lax", "strict", "none"}
configured_same_site = (settings.cookie_samesite or "lax").lower()
if configured_same_site not in allowed_same_site_values:
    logger.warning(
        "Invalid cookie_samesite value '%s' - defaulting to 'lax'",
        settings.cookie_samesite,
    )
    configured_same_site = "lax"

cookie_secure_flag = settings.cookie_secure
session_https_only = bool(cookie_secure_flag)
if settings.auth_enabled and not session_https_only:
    logger.warning(
        "Authentication is enabled but COOKIE_SECURE is false - forcing secure session cookies."
    )
    session_https_only = True

# Ensure SameSite=None is only used with Secure cookies per browser requirements
if configured_same_site == "none" and not session_https_only:
    logger.warning(
        "SameSite=None requires secure cookies - forcing secure session cookies."
    )
    session_https_only = True

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    max_age=settings.session_max_age,
    same_site=configured_same_site,
    https_only=session_https_only,
    domain=None,
    path="/",
    # Note: httponly is always True by default in SessionMiddleware for security
)

# Include API routes
app.include_router(router)

# Custom Swagger UI endpoint using local assets to avoid CSP issues
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Serve Swagger UI with local assets instead of CDN."""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - API Documentation",
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
        swagger_favicon_url="/static/swagger-ui/favicon-32x32.png",
    )

# Setup templates
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def root(request: Request):
    """Serve the web UI."""
    try:
        config_result = get_config_validation_result()
        environment_name = (
            "Imaginary Datacenter" if settings.dummy_data else settings.environment_name
        )

        if config_result and config_result.has_errors:
            checked_at = (
                config_result.checked_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                if config_result and config_result.checked_at
                else None
            )
            response = templates.TemplateResponse(
                "config_warning.html",
                {
                    "request": request,
                    "environment_name": environment_name,
                    "result": config_result,
                    "build_metadata": build_metadata,
                    "build_metadata_payload": _build_metadata_payload(),
                    "checked_at": checked_at,
                },
                status_code=status.HTTP_200_OK,
            )
        else:
            if config_result and config_result.has_warnings:
                logger.info(
                    "Startup configuration warnings detected, but proceeding with standard UI."
                )

            # Check authentication status to determine which view to render
            session_user = request.session.get("user_info")
            is_authenticated = bool(session_user and session_user.get("authenticated"))

            if not is_authenticated:
                logger.info("Unauthenticated request for UI; rendering login page")
                response = templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "auth_enabled": settings.auth_enabled,
                        "environment_name": environment_name,
                        "app_name": settings.app_name,
                        "build_metadata": build_metadata,
                        "build_metadata_payload": _build_metadata_payload(),
                        "github_url": PROJECT_GITHUB_URL,
                        "api_reference_url": API_REFERENCE_URL,
                    },
                    status_code=status.HTTP_200_OK,
                )
            else:
                username = session_user.get("preferred_username", "unknown")
                logger.info(f"Authenticated request from user: {username}")

                response = templates.TemplateResponse(
                    "index.html",
                    {
                        "request": request,
                        "auth_enabled": settings.auth_enabled,
                        "environment_name": environment_name,
                        # Convert to milliseconds
                        "websocket_refresh_time": settings.websocket_refresh_time * 1000,
                        # Convert to milliseconds
                        "websocket_ping_interval": settings.websocket_ping_interval * 1000,
                        "job_schema": get_job_schema(),
                        "agent_deployment": host_deployment_service.get_startup_summary(),
                        "build_metadata": build_metadata,
                        "build_metadata_payload": _build_metadata_payload(),
                        "app_name": settings.app_name,
                    },
                )

        # Add cache headers to prevent caching issues
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response

    except Exception as e:
        logger.error(f"Error in root route: {type(e).__name__}: {e}")
        # Return a minimal HTML response to prevent 502 errors
        return HTMLResponse(
            content="<html><body><h1>Aether-V Server</h1><p>Loading...</p><script>setTimeout(function(){location.reload()}, 2000);</script></body></html>",
            status_code=200,
        )


@app.get("/cluster/{cluster_name}", response_class=HTMLResponse, tags=["UI"])
async def cluster_page(_cluster_name: str, request: Request):
    """Serve the main UI for cluster-specific routes."""
    return await root(request)


@app.get("/host/{hostname}", response_class=HTMLResponse, tags=["UI"])
async def host_page(_hostname: str, request: Request):
    """Serve the main UI for host-specific routes."""
    return await root(request)


@app.get("/virtual-machine/{vm_name}", response_class=HTMLResponse, tags=["UI"])
async def vm_page(_vm_name: str, request: Request):
    """Serve the main UI for VM-specific routes."""
    return await root(request)


@app.get("/disconnected-hosts", response_class=HTMLResponse, tags=["UI"])
async def disconnected_hosts_page(request: Request):
    """Serve the main UI for the disconnected hosts section."""
    return await root(request)


@app.get("/ui", response_class=HTMLResponse, tags=["UI"])
async def ui(request: Request):
    """Serve the web UI."""
    # Redirect to root which handles auth
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


def main():
    """Run the application."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="debug" if settings.debug else "info",
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
