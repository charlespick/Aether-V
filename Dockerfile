# Multi-stage build for Aether-V application
# 
# Build prerequisites (run via `make build-assets`):
#   - ISOs built via build-tools container
#   - next-ui built with npm (Svelte + static assets)
#   - Icons and Swagger UI extracted from next-ui/node_modules
#
# This Dockerfile builds the production Python FastAPI server with all assets bundled.

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

# Install build-time dependencies for Python wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libkrb5-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Capture build metadata
FROM base AS build-info

# Accept GITHUB_REPOSITORY as a build argument
ARG GITHUB_REPOSITORY

WORKDIR /src

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY . /src

RUN set -eux; \
    mkdir -p /out; \
    python - <<'PY'
import datetime
import json
import os
import socket
import subprocess
from pathlib import Path


def run_git(args):
    try:
        return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT).decode().strip()
    except Exception:
        return None


metadata = {
    "source_control": "unknown",
}

if Path(".git").exists():
    metadata["source_control"] = "git"
    commit = run_git(["rev-parse", "HEAD"])
    if commit:
        metadata["git_commit"] = commit

    ref = run_git(["symbolic-ref", "-q", "--short", "HEAD"])
    state = "branch" if ref else None

    if not ref:
        ref = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if ref == "HEAD":
            state = "detached"
        elif ref:
            state = "branch"

    if ref:
        metadata["git_ref"] = ref
    if state:
        metadata["git_state"] = state
else:
    metadata["source_control"] = "absent"

# Capture GitHub repository from CI environment
github_repo = os.environ.get("GITHUB_REPOSITORY")
if github_repo:
    metadata["github_repository"] = f"https://github.com/{github_repo}"

version_file = Path("version")
metadata["version"] = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"

metadata["build_time"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
metadata["build_host"] = socket.gethostname()

output_path = Path("/out/build-info.json")
output_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
PY

# Stage 4: Collect OSS license information
FROM base AS license-collector

WORKDIR /src

# Install Node.js for license-checker and build dependencies for Python wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    gcc \
    python3-dev \
    libkrb5-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install pip-licenses
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pip-licenses

# Copy next-ui package.json which now contains all frontend dependencies
COPY next-ui/package.json next-ui/package-lock.json ./
RUN npm install --omit=dev && \
    npm install --save-dev license-checker

# Copy the license collection script and run it
COPY server/scripts/collect_licenses.py ./scripts/
RUN mkdir -p /out && \
    python scripts/collect_licenses.py && \
    cp oss-licenses.json /out/

# Stage 5: Extract static assets (icons and Swagger UI) from node_modules
FROM base AS static-extractor

WORKDIR /src

# Install Node.js and npm
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Install next-ui dependencies which include @material-symbols and swagger-ui-dist
COPY next-ui/package.json next-ui/package-lock.json ./
RUN npm install --omit=dev

# Copy icons.json configuration
COPY server/icons.json ./icons.json

# Extract icons and Swagger UI directly using inline Python
RUN mkdir -p /out/static/icons /out/static/swagger-ui && python3 - <<'PYTHON'
import json
import shutil
from pathlib import Path

# Extract icons
STATIC_ICONS_DIR = Path("/out/static/icons")
NODE_MODULES = Path("/src/node_modules")
ICON_SOURCE = NODE_MODULES / "@material-symbols" / "svg-400"

config_path = Path("/src/icons.json")
with config_path.open("r", encoding="utf-8") as f:
    config = json.load(f)

copied = 0
for style, icons in config.items():
    mapped_style = "rounded" if style == "round" else style
    for icon_name in icons:
        source = ICON_SOURCE / mapped_style / f"{icon_name}.svg"
        if source.exists():
            dest = STATIC_ICONS_DIR / style / f"{icon_name}.svg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            copied += 1
        else:
            print(f"[warn] missing icon: {style}/{icon_name}.svg")

print(f"[done] copied {copied} icons")

# Extract Swagger UI
SWAGGER_SOURCE = NODE_MODULES / "swagger-ui-dist"
SWAGGER_DEST = Path("/out/static/swagger-ui")

REQUIRED_FILES = [
    "swagger-ui-bundle.js",
    "swagger-ui.css",
    "swagger-ui-standalone-preset.js",
    "favicon-32x32.png",
]

copied = 0
for filename in REQUIRED_FILES:
    source = SWAGGER_SOURCE / filename
    if source.exists():
        dest = SWAGGER_DEST / filename
        shutil.copy2(source, dest)
        copied += 1
    else:
        print(f"[warn] missing Swagger UI file: {filename}")

print(f"[done] copied {copied}/{len(REQUIRED_FILES)} Swagger UI assets")
PYTHON

# Stage 6: Collect agent artifacts (scripts, ISOs, version)
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

# Stage 7: Application
FROM base AS application

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    krb5-user \
    libkrb5-3 \
    libgssapi-krb5-2 \
    libk5crypto3 \
    libcomerr2 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from previous stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code and schema definitions
COPY server/app /app/app
COPY Schemas /app/Schemas
COPY Assets /app/Assets

# Copy pre-built static assets from static-extractor stage
COPY --from=static-extractor /out/static/icons /app/app/static/icons
COPY --from=static-extractor /out/static/swagger-ui /app/app/static/swagger-ui

# Copy pre-built next-ui Svelte application
# Built outside Docker by build-tools container
COPY next-ui/build /app/next-ui-build

# Prepare unified agent artifact directory
RUN mkdir -p /app/agent

# Copy build metadata and the curated agent artifacts (scripts, ISOs, version)
COPY --from=build-info /out/build-info.json /app/agent/build-info.json
COPY --from=agent-artifacts /artifacts/ /app/agent/

# Copy OSS license information
COPY --from=license-collector /out/oss-licenses.json /app/oss-licenses.json

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
