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

from .core.config import settings
from .api.routes import router
from .services.inventory_service import inventory_service
from .services.job_service import job_service
from .services.notification_service import notification_service
from .services.websocket_service import websocket_manager

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Aether-V Orchestrator")
    logger.info(f"Version: {settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Authentication enabled: {settings.auth_enabled}")

    # Start services
    await notification_service.start()

    # Connect WebSocket manager to notification service
    notification_service.set_websocket_manager(websocket_manager)

    job_service.start()
    await inventory_service.start()

    logger.info("Application started successfully")

    yield

    # Shutdown services
    logger.info("Shutting down application")
    await inventory_service.stop()
    job_service.stop()
    await notification_service.stop()
    logger.info("Application stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Lightweight orchestration service for Hyper-V virtual machines",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
from .core.config import set_session_secret
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
        # Check authentication status
        auth_param = request.query_params.get("auth")
        session_user = request.session.get("user_info")

        if session_user and session_user.get("authenticated"):
            username = session_user.get("preferred_username", "unknown")
            logger.info(f"Authenticated request from user: {username}")

        # Always serve the page - let the frontend handle authentication state
        # This prevents redirect loops and allows graceful token handling
        environment_name = "Imaginary Datacenter" if settings.dummy_data else settings.environment_name
        response = templates.TemplateResponse("index.html", {
            "request": request,
            "auth_enabled": settings.auth_enabled,
            "environment_name": environment_name,
            # Convert to milliseconds
            "websocket_refresh_time": settings.websocket_refresh_time * 1000,
            # Convert to milliseconds
            "websocket_ping_interval": settings.websocket_ping_interval * 1000
        })

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
