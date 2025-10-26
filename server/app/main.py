"""Main application entry point."""
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import secrets

from .core.config import settings, get_config_validation_result, set_session_secret
from .core.build_info import build_metadata
from .core.config_validation import run_config_checks
from .api.routes import router
from .services.inventory_service import inventory_service
from .services.host_deployment_service import host_deployment_service
from .services.job_service import job_service
from .services.notification_service import notification_service
from .services.websocket_service import websocket_manager
from .core.job_schema import load_job_schema, get_job_schema, SchemaValidationError

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


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
    logger.info("Starting Aether-V Orchestrator")
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

    notifications_started = False
    job_started = False
    inventory_started = False

    await notification_service.start()
    notifications_started = True

    # Connect WebSocket manager to notification service
    notification_service.set_websocket_manager(websocket_manager)

    notification_service.publish_startup_configuration_result(config_result)

    await host_deployment_service.start_startup_deployment(
        settings.get_hyperv_hosts_list()
    )

    if not config_result.has_errors:
        await job_service.start()
        job_started = True
        await inventory_service.start()
        inventory_started = True
        logger.info("Application started successfully")
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
        logger.info("Application stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=build_metadata.version,
    description="Lightweight orchestration service for Hyper-V virtual machines",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount(
    settings.agent_http_mount_path,
    StaticFiles(directory=settings.agent_artifacts_path, html=False),
    name="agent",
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
    safe_headers = {k: v for k, v in request.headers.items()
                    if k.lower() not in ['authorization', 'cookie', 'x-api-key']}

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
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

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
        "Generated temporary session secret - set SESSION_SECRET_KEY environment variable for production")

# Store the session secret in the config module so it can be accessed elsewhere
set_session_secret(session_secret)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    max_age=settings.session_max_age,
    same_site="lax",  # CSRF protection
    https_only=False,  # Disable for debugging - ingress may terminate HTTPS
    domain=None,  # Don't restrict domain for debugging
    path="/"  # Ensure cookies work for all paths
    # Note: httponly is always True by default in SessionMiddleware for security
)

# Include API routes
app.include_router(router)

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

            # Check authentication status for logging purposes only
            session_user = request.session.get("user_info")

            if session_user and session_user.get("authenticated"):
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
            content="<html><body><h1>Aether-V Orchestrator</h1><p>Loading...</p><script>setTimeout(function(){location.reload()}, 2000);</script></body></html>",
            status_code=200
        )


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
        reload=settings.debug
    )


if __name__ == "__main__":
    main()
