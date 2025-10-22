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

# Prepare unified agent artifact directory
RUN mkdir -p /app/agent

# Copy artifact sources and gather scripts/ISOs dynamically
COPY Powershell /tmp/agent-src/Powershell
COPY Scripts /tmp/agent-src/Scripts
COPY Windows /tmp/agent-src/Windows
COPY Linux /tmp/agent-src/Linux
COPY version /tmp/agent-src/version

RUN set -eux; \
    find /tmp/agent-src -type f -name '*.ps1' -exec cp {} /app/agent/ \; && \
    find /tmp/agent-src -type f -name '*.iso' -exec cp {} /app/agent/ \; && \
    if [ -f /tmp/agent-src/version ]; then cp /tmp/agent-src/version /app/agent/version; fi && \
    rm -rf /tmp/agent-src

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
