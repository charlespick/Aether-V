.PHONY: help dev-up dev-down dev-shell dev-logs dev-test build build-assets build-isos build-next-ui build-static test-all test-python test-powershell test-roundtrip clean

# Detect if we're running inside a container
IN_CONTAINER := $(shell [ -f /.dockerenv ] && echo 1 || echo 0)

# Docker run wrapper for build-tools
DOCKER_RUN_BUILD_TOOLS := docker run --rm -v $(CURDIR):/workspace -w /workspace ghcr.io/charlespick/aetherv-build-tools:latest

help:
	@echo "Aether-V - VM Management Platform"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make dev-up        - Start development server with hot reload"
	@echo "  make dev-down      - Stop development server"
	@echo "  make dev-shell     - Open shell in development container"
	@echo "  make dev-logs      - View development server logs"
	@echo "  make dev-test      - Run tests in development container"
	@echo ""
	@echo "🔨 Build & Assets:"
	@echo "  make build-assets  - Build all assets (ISOs + next-ui + static)"
	@echo "  make build-isos    - Build provisioning ISOs for Windows/Linux"
	@echo "  make build-next-ui - Build next-ui Svelte application"
	@echo "  make build-static  - Extract static assets (icons, Swagger UI)"
	@echo "  make build         - Build production Docker container"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test-all      - Run complete test suite"
	@echo "  make test-python   - Run Python tests only"
	@echo "  make test-powershell - Run PowerShell tests only"
	@echo "  make test-roundtrip - Run round-trip protocol tests"
	@echo ""
	@echo "🔧 Utility:"
	@echo "  make clean         - Clean up temporary files and caches"

# Development commands (container-based)
dev-up:
	@echo "🚀 Starting development server..."
	docker compose -f docker-compose.dev.yml up -d --build app-server
	@echo ""
	@echo "✅ Development server running!"
	@echo "   - Web UI: http://localhost:8000"
	@echo "   - API Docs: http://localhost:8000/docs"
	@echo "   - Next UI: http://localhost:8000/next-ui"
	@echo ""
	@echo "📝 Useful commands:"
	@echo "   make dev-logs   - View server logs"
	@echo "   make dev-down   - Stop server"

dev-down:
	@echo "🛑 Stopping development environment..."
	docker compose -f docker-compose.dev.yml down

dev-shell:
	@echo "🐚 Opening shell in app server container..."
	docker compose -f docker-compose.dev.yml exec app-server bash

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f app-server

dev-test:
	@echo "🧪 Running tests..."
	pytest server/tests/ -v

# Build assets commands (container-aware)
build-assets: build-isos build-next-ui build-static
	@echo "✅ All assets built successfully"

build-isos:
	@echo "🔨 Building provisioning ISOs..."
ifeq ($(IN_CONTAINER),1)
	@pwsh -NoLogo -NoProfile -File ./Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs
else
	@$(DOCKER_RUN_BUILD_TOOLS) pwsh -NoLogo -NoProfile -File Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs
endif
	@echo "✅ ISOs built successfully"

build-next-ui:
	@echo "🔨 Building next-ui Svelte application..."
ifeq ($(IN_CONTAINER),1)
	@cd next-ui && npm ci && npm run build
else
	@$(DOCKER_RUN_BUILD_TOOLS) bash -c "cd next-ui && npm ci && npm run build"
endif
	@echo "✅ next-ui build complete"

build-static:
	@echo "🔨 Extracting static assets..."
ifeq ($(IN_CONTAINER),1)
	@cd server && npm install --omit=dev && python3 scripts/extract_icons.py && python3 scripts/extract_swagger_ui.py
else
	@$(DOCKER_RUN_BUILD_TOOLS) bash -c "cd server && npm install --omit=dev && python3 scripts/extract_icons.py && python3 scripts/extract_swagger_ui.py"
endif
	@echo "✅ Static assets extracted"

# Production build
build: build-assets
	@echo "🐳 Building production Docker container..."
	docker build -f server/Dockerfile --target application -t aetherv:latest .
	@echo "✅ Container built: aetherv:latest"

# Testing commands
test-all: test-python test-powershell test-roundtrip
	@echo ""
	@echo "✅ All test suites completed successfully"

test-python:
	@echo "🧪 Running Python tests..."
	@cd server && pytest tests/ --cov=app --cov-report=term-missing -v

test-powershell:
	@echo "🧪 Running PowerShell tests..."
ifeq ($(IN_CONTAINER),1)
	@pwsh -NoProfile -Command "Invoke-Pester -Path Powershell/tests -CI"
else
	@$(DOCKER_RUN_BUILD_TOOLS) pwsh -NoProfile -Command "Invoke-Pester -Path Powershell/tests -CI"
endif

test-roundtrip:
	@echo "🧪 Running protocol round-trip tests..."
	@cd server && PYTHONPATH=. pytest tests/test_resource_operations.py tests/test_noop_operations.py -v

# Cleanup
clean:
	@echo "Cleaning up temporary files and caches..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -rf server/.pytest_cache server/htmlcov server/.coverage
	rm -rf next-ui/.svelte-kit next-ui/build 2>/dev/null || true
	rm -rf build/ 2>/dev/null || true
	rm -rf ISOs/ 2>/dev/null || true
	@echo "✅ Cleanup complete"
