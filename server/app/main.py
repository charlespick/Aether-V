"""Main application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from .core.config import settings
from .api.routes import router
from .services.inventory_service import inventory_service
from .services.job_service import job_service

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
    logger.info(f"OIDC enabled: {settings.oidc_enabled}")
    
    # Start services
    job_service.start()
    await inventory_service.start()
    
    logger.info("Application started successfully")
    
    yield
    
    # Shutdown services
    logger.info("Shutting down application")
    await inventory_service.stop()
    job_service.stop()
    logger.info("Application stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Lightweight orchestration service for Hyper-V virtual machines",
    lifespan=lifespan
)

# Include API routes
app.include_router(router)

# Setup templates
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def root(request: Request):
    """Serve the web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/ui", response_class=HTMLResponse, tags=["UI"])
async def ui(request: Request):
    """Serve the web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


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
