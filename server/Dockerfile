# Multi-stage build for Aether-V Orchestrator
# Note: ISOs should be pre-built using GitHub Actions before Docker build

# Stage 1: Base image with Python
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Stage 2: Dependencies
FROM base AS dependencies

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Application
FROM base AS application

# Copy Python dependencies from previous stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY server/app /app/app

# Create directories for ISO and script storage
RUN mkdir -p /app/artifacts/isos /app/artifacts/scripts

# Copy pre-built ISOs (built by GitHub Actions)
COPY ISOs/WindowsProvisioning.iso /app/artifacts/isos/
COPY ISOs/LinuxProvisioning.iso /app/artifacts/isos/

# Copy PowerShell scripts for deployment to hosts
COPY Powershell /app/artifacts/scripts/

# Copy version file
COPY version /app/artifacts/version

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
