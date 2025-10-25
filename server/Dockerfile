# Multi-stage build for Aether-V Orchestrator
# Provisioning ISOs are rebuilt via `make build` before this Dockerfile runs

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

# Stage 3: Collect agent artifacts (scripts, ISOs, version)
FROM base AS agent-artifacts

WORKDIR /src

# Copy required artifact sources from the repository
COPY Powershell/ ./Powershell/
COPY version ./version
COPY ISOs/ ./ISOs/

RUN set -eux; \
    mkdir -p /artifacts; \
    if [ ! -f ./version ]; then \
        echo "Missing version file in repository root" >&2; \
        exit 1; \
    fi; \
    cp ./version /artifacts/version; \
    script_count="$(find ./Powershell -maxdepth 1 -type f -name '*.ps1' | wc -l | tr -d '[:space:]')"; \
    if [ "${script_count}" -eq 0 ]; then \
        echo "No PowerShell scripts found in Powershell/." >&2; \
        exit 1; \
    fi; \
    find ./Powershell -maxdepth 1 -type f -name '*.ps1' -exec cp {} /artifacts/ \;; \
    if [ ! -d ./ISOs ]; then \
        echo "Missing ISOs directory. Run Scripts/Build-ProvisioningISOs.ps1 before building." >&2; \
        exit 1; \
    fi; \
    iso_count="$(find ./ISOs -maxdepth 1 -type f -name '*.iso' | wc -l | tr -d '[:space:]')"; \
    if [ "${iso_count}" -eq 0 ]; then \
        echo "No ISO artifacts found in ISOs/. Run Scripts/Build-ProvisioningISOs.ps1 before building." >&2; \
        exit 1; \
    fi; \
    find ./ISOs -maxdepth 1 -type f -name '*.iso' -exec cp {} /artifacts/ \;

# Stage 4: Application
FROM base AS application

# Copy Python dependencies from previous stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code and schema definitions
COPY server/app /app/app
COPY Schemas /app/Schemas

# Prepare unified agent artifact directory
RUN mkdir -p /app/agent

# Copy the curated agent artifacts (scripts, ISOs, version)
COPY --from=agent-artifacts /artifacts/ /app/agent/

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
