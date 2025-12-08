# Aether-V Make Commands Quick Reference

## 🚀 Development (Container-based)

### Start & Stop
```bash
make dev-up        # Start development server (http://localhost:8000)
make dev-down      # Stop development server
make dev-logs      # View live server logs
make dev-shell     # Open bash shell in container
```

### First Time Setup
```bash
# Clone repository
git clone https://github.com/charlespick/Aether-V.git
cd Aether-V

# Start development (pulls images, creates containers)
make dev-up

# Access:
# - API: http://localhost:8000/docs
# - UI: http://localhost:8000
# - Next-UI: http://localhost:8000/next-ui
```

## 🧪 Testing

### Run Tests
```bash
make test-all          # Run complete test suite
make test-python       # Python tests + type checking
make test-js           # JavaScript tests
make test-powershell   # PowerShell Pester tests
make test-svelte       # Svelte type checking
make test-roundtrip    # Protocol round-trip tests
```

### Quick Test in Dev Container
```bash
make dev-shell
# Inside container:
pytest tests/test_specific.py -v
```

## 🔨 Building

### Build Assets
```bash
make build-assets      # Build everything (ISOs + next-ui + static)
make build-isos        # Build Windows/Linux provisioning ISOs
make build-next-ui     # Build Svelte frontend
make build-static      # Extract icons and Swagger UI
```

### Build Production Container
```bash
make build             # Build Docker image (includes all assets)
make all               # Build assets + container
```

## 🐳 Container Information

### Images Used
- **Development:** `aetherv:dev` (Python, Node, all dev tools)
- **Build Tools:** `ghcr.io/charlespick/aetherv-build-tools:latest` (PowerShell, Node, ISO tools)
- **Production:** `aetherv:latest` (minimal runtime)

### Services (docker-compose.dev.yml)
- `app` - FastAPI development server (port 8000)
- `build-tools` - ISO and asset builder (on-demand)

## 📁 Key Files

```
.devcontainer/devcontainer.json   # VS Code DevContainer config
docker-compose.dev.yml            # Development orchestration
server/Dockerfile                 # Multi-stage build (dev + prod)
Makefile                          # All build commands
server/.env                       # Local configuration
```

## 🔧 Common Tasks

### Update Dependencies

**Python:**
```bash
# Edit server/requirements.txt
make dev-down
docker compose -f docker-compose.dev.yml build --no-cache app
make dev-up
```

**Node (next-ui):**
```bash
# Edit next-ui/package.json
make build-next-ui
```

### View Logs
```bash
make dev-logs                     # Follow logs
docker compose -f docker-compose.dev.yml logs app  # All logs
```

### Clean Up
```bash
make clean                        # Remove build artifacts
make dev-down                     # Stop containers
docker system prune               # Clean Docker cache (optional)
```

### Rebuild Everything
```bash
make clean
make dev-down
docker compose -f docker-compose.dev.yml build --no-cache
make dev-up
```

## 🎯 Workflow Examples

### Daily Development
```bash
# Morning
make dev-up

# Work on code (auto-reloads)
# Edit server/app/...

# Test changes
make dev-shell
pytest tests/

# Evening
make dev-down
```

### Feature Development
```bash
# Create branch
git checkout -b feature/my-feature

# Start dev environment
make dev-up

# Make changes, test frequently
make test-python

# Build assets if needed
make build-next-ui

# Commit and push
git add .
git commit -m "Add feature"
git push
```

### Pre-Commit Check
```bash
# Run all tests
make test-all

# Build production to verify
make build

# Clean up
make clean
```

## ⚡ Performance Tips

### Faster Rebuilds
- Use layer caching (automatic)
- Only rebuild what changed
- Use `--no-cache` sparingly

### Faster Tests
```bash
# Run specific tests
make dev-shell
pytest tests/test_specific.py

# Run in parallel (if pytest-xdist installed)
pytest -n auto
```

### Reduce Disk Usage
```bash
# Clean build artifacts
make clean

# Remove unused Docker resources
docker system prune -a
```

## 🐛 Troubleshooting

### Port Already in Use
```bash
make dev-down
# Or manually: docker compose -f docker-compose.dev.yml down
```

### Container Won't Start
```bash
# Check logs
make dev-logs

# Rebuild
make dev-down
docker compose -f docker-compose.dev.yml build --no-cache
make dev-up
```

### Tests Fail in Container
```bash
# Update development image
make dev-down
docker compose -f docker-compose.dev.yml pull
docker compose -f docker-compose.dev.yml build
make dev-up
```

### Build-Tools Container Missing
```bash
# Pull from registry
docker pull ghcr.io/charlespick/aetherv-build-tools:latest

# Or build locally
cd build-tools
docker build -t ghcr.io/charlespick/aetherv-build-tools:latest .
```

## 🔄 Migration from Old Workflow

| Old Command | New Command |
|-------------|-------------|
| `make dev` | `make dev-up` |
| `make test` | `make test-all` |
| `make isos` | `make build-isos` |
| `make next-ui` | `make build-next-ui` |

See [Docs/MIGRATION.md](Docs/MIGRATION.md) for complete migration guide.

## 📚 Additional Resources

- [Development Guide](Docs/DEVELOPMENT.md) - Complete development documentation
- [Migration Guide](Docs/MIGRATION.md) - Transitioning from old workflow
- [Configuration Reference](Docs/Configuration.md) - Environment variables
- [Architecture](Docs/System-Architecture-and-Operations.md) - System design

## 💡 Pro Tips

1. **Always use `make` commands** - They handle container detection automatically
2. **Keep containers running** - Faster than starting/stopping repeatedly
3. **Use `make dev-shell`** - Quick access for debugging
4. **Check `make help`** - Full command reference
5. **Read the logs** - `make dev-logs` shows what's happening

---

**Need help?** Run `make help` or check the documentation in `Docs/`
