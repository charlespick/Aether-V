# Development Guide

## Quick Start

The Aether-V project uses a **container-first development approach** for consistency across all environments (dev, CI, production).

### Prerequisites

- Docker Desktop or Docker Engine with Docker Compose
- Git
- Visual Studio Code (recommended) with Dev Containers extension

### Option 1: DevContainer (Recommended)

1. **Open in DevContainer:**
   ```bash
   # In VS Code, use Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
   > Dev Containers: Reopen in Container
   ```

2. **Start development server:**
   ```bash
   make dev-up
   ```

3. **Access the application:**
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Next UI: http://localhost:8000/next-ui

### Option 2: Local Docker Compose

1. **Clone and start:**
   ```bash
   git clone https://github.com/charlespick/Aether-V.git
   cd Aether-V
   make dev-up
   ```

2. **View logs:**
   ```bash
   make dev-logs
   ```

3. **Stop server:**
   ```bash
   make dev-down
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
make test-all

# Run specific test suites
make test-python      # Python unit tests
make test-js          # JavaScript tests
make test-powershell  # PowerShell tests
make test-svelte      # Svelte type checking
make test-roundtrip   # Protocol integration tests
```

### Building Assets

Assets are built using the pre-built `aetherv-build-tools` container:

```bash
# Build everything
make build-assets

# Build specific components
make build-isos       # Windows/Linux provisioning ISOs
make build-next-ui    # Svelte frontend
make build-static     # Icons and Swagger UI
```

### Container Shell Access

```bash
# Open bash shell in development container
make dev-shell

# Inside container, you can:
pytest tests/              # Run tests
python -m app.main         # Start server manually
mypy .                     # Type checking
black .                    # Format code
```

### Hot Reload

The development container mounts your local code with live reload enabled:

- **Python changes** → Auto-reload (uvicorn `--reload`)
- **Static files** → Served directly from mounted volumes
- **Next-UI** → Rebuild with `make build-next-ui` (one-time)

## Project Structure

```
Aether-V/
├── server/                    # FastAPI backend
│   ├── app/                   # Application code
│   │   ├── api/              # API endpoints
│   │   ├── core/             # Core business logic
│   │   ├── services/         # External services
│   │   └── static/           # Static assets
│   ├── tests/                # Python tests
│   ├── Dockerfile            # Multi-stage build (dev + prod)
│   └── requirements.txt      # Python dependencies
├── next-ui/                   # Svelte frontend
│   ├── src/                  # Svelte components
│   ├── build/                # Built output (gitignored)
│   └── package.json          # Node dependencies
├── Powershell/               # PowerShell provisioning scripts
├── Windows/                  # Windows provisioning files
├── Linux/                    # Linux provisioning files
├── Schemas/                  # JSON schemas
├── docker-compose.dev.yml    # Development orchestration
├── Makefile                  # Build automation
└── .devcontainer/            # VS Code DevContainer config
```

## Environment Configuration

### Creating .env File

The development container automatically creates `.env` from `.env.example`:

```bash
cd server
cp .env.example .env
# Edit .env with your settings
```

### Key Environment Variables

```bash
# Hyper-V Hosts
HYPERV_HOSTS=hyperv1.example.com,hyperv2.example.com

# Authentication (optional for dev)
OIDC_ENABLED=false

# WinRM Configuration
WINRM_USERNAME=administrator
WINRM_PASSWORD=yourpassword
```

## Architecture Overview

### Container Stages

The project uses different container targets for different purposes:

1. **Development** (`development` stage)
   - Full tooling (pytest, mypy, black, etc.)
   - Hot reload enabled
   - Development dependencies included

2. **Production** (`application` stage)
   - Minimal runtime dependencies
   - Pre-built artifacts baked in
   - Non-root user
   - Health checks enabled

### Build Process

```
┌─────────────────────────────────────┐
│   Build-Tools Container             │
│   (PowerShell, Node, Python, ISO)   │
└──────────┬──────────────────────────┘
           │
           ├─► Build ISOs (Windows/Linux)
           ├─► Build next-ui (Svelte)
           └─► Extract static assets
                    │
                    ▼
           ┌────────────────────┐
           │  Production Build  │
           │  (Dockerfile)      │
           └────────┬───────────┘
                    │
                    ▼
           ┌────────────────────┐
           │  aetherv:latest    │
           │  (Ready to deploy) │
           └────────────────────┘
```

## Troubleshooting

### DevContainer Build Slow

**Solution:** The new setup is fast (<30s). If slow:
1. Ensure Docker has adequate resources (4GB+ RAM)
2. Pull latest base images: `docker compose pull`

### Port Already in Use

```bash
# Stop any existing containers
make dev-down

# Or manually:
docker compose -f docker-compose.dev.yml down
```

### Tests Failing in Container

```bash
# Rebuild development container
docker compose -f docker-compose.dev.yml build --no-cache app

# Check logs
make dev-logs
```

### Build-Tools Container Not Found

The CI/CD pipeline builds and publishes `aetherv-build-tools`. If not available:

```bash
# Build locally
cd build-tools
docker build -t ghcr.io/charlespick/aetherv-build-tools:latest .
```

## Performance Tips

### Faster Builds

- Use layer caching (already configured in CI)
- Build assets once, reuse: `make build-assets`
- Use `--parallel` for compose (Docker Compose v2+)

### Faster Tests

```bash
# Run specific test file
docker compose exec app pytest tests/test_specific.py

# Parallel execution
docker compose exec app pytest -n auto  # Requires pytest-xdist
```

## Migration from Legacy Setup

### Old Workflow → New Workflow

| Old Command | New Command | Notes |
|-------------|-------------|-------|
| `make dev` | `make dev-up` | Now uses compose |
| `make test` | `make test-all` | Runs in containers |
| `make isos` | `make build-isos` | Uses build-tools |
| `make next-ui` | `make build-next-ui` | Uses build-tools |
| Manual venv setup | Automatic | Container has everything |

### What Changed?

✅ **Before:** Local Python venv, manual dependency installation  
✅ **After:** Everything in containers, no local setup needed

✅ **Before:** 5-10 minute devcontainer build  
✅ **After:** <30 second startup

✅ **Before:** CI uses different tools than dev  
✅ **After:** Dev = CI = Prod (consistent)

## CI/CD Integration

All GitHub Actions workflows use the same containers as local development:

- **Python tests** → `development` container
- **JS tests** → `development` container
- **PowerShell tests** → `build-tools` container
- **Svelte build** → `build-tools` container
- **Production build** → Multi-stage Dockerfile

This ensures **zero surprises** when pushing code.

## Additional Resources

- [System Architecture](Docs/System-Architecture-and-Operations.md)
- [Next-UI Implementation](Docs/next-ui-implementation.md)
- [Deployment Guide](Docs/agent-deployment-service.md)
- [Configuration Reference](Docs/Configuration.md)

## Getting Help

- Check existing issues: https://github.com/charlespick/Aether-V/issues
- Review logs: `make dev-logs`
- Inspect container: `make dev-shell`
- Ask in discussions: https://github.com/charlespick/Aether-V/discussions
