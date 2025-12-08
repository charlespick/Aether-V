.PHONY: help dev dev-up dev-down dev-shell dev-logs dev-test build run test clean deploy isos config-validate all next-ui build-assets build-isos build-next-ui build-static test-all test-python test-js test-powershell test-svelte test-roundtrip

POWERSHELL ?= pwsh

# Detect if we're running inside a container
IN_CONTAINER := $(shell [ -f /.dockerenv ] && echo 1 || echo 0)

# Docker run wrapper for build-tools
DOCKER_RUN_BUILD_TOOLS := docker run --rm -v $(CURDIR):/workspace -w /workspace ghcr.io/charlespick/aetherv-build-tools:latest

help:
	@echo "HLVMM - High-Level VM Management - Make commands"
	@echo ""
	@echo "🚀 Development (Container-based - Recommended):"
	@echo "  make dev-up        - Start development environment with hot reload"
	@echo "  make dev-down      - Stop development environment"
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
	@echo "  make all           - Build everything (assets + container)"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test-all      - Run complete test suite"
	@echo "  make test-python   - Run Python tests only"
	@echo "  make test-js       - Run JavaScript tests only"
	@echo "  make test-powershell - Run PowerShell tests only"
	@echo "  make test-svelte   - Run Svelte checks only"
	@echo "  make test-roundtrip - Run round-trip protocol tests"
	@echo ""
	@echo "☸️  Kubernetes:"
	@echo "  make deploy        - Deploy to Kubernetes using kubectl"
	@echo "  make undeploy      - Remove from Kubernetes"
	@echo ""
	@echo "🔧 Utility:"
	@echo "  make config-validate - Validate configuration schemas"
	@echo "  make clean         - Clean up temporary files and caches"
	@echo ""
	@echo "📜 Legacy (deprecated, use dev-up instead):"
	@echo "  make dev           - Start development server (old method)"
	@echo "  make run           - Run container locally (old method)"

# Development commands (container-based)
dev-up:
	@echo "🚀 Starting development environment..."
	docker compose -f docker-compose.dev.yml up -d app
	@echo ""
	@echo "✅ Development server running!"
	@echo "   - Web UI: http://localhost:8000"
	@echo "   - API Docs: http://localhost:8000/docs"
	@echo "   - Next UI: http://localhost:8000/next-ui"
	@echo ""
	@echo "📝 Useful commands:"
	@echo "   make dev-logs   - View server logs"
	@echo "   make dev-shell  - Open shell in container"
	@echo "   make dev-down   - Stop server"

dev-down:
	@echo "🛑 Stopping development environment..."
	docker compose -f docker-compose.dev.yml down

dev-shell:
	@echo "🐚 Opening shell in development container..."
	docker compose -f docker-compose.dev.yml exec app bash

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f app

dev-test:
	@echo "🧪 Running tests in development container..."
	docker compose -f docker-compose.dev.yml exec app pytest tests/ -v

# Build assets commands (container-aware)
build-assets: build-isos build-next-ui build-static
	@echo "✅ All assets built successfully"

build-isos:
ifeq ($(IN_CONTAINER),1)
	@echo "Building ISOs (in container)..."
	@$(POWERSHELL) -NoLogo -NoProfile -File ./Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs
else
	@echo "🔨 Building provisioning ISOs using build-tools container..."
	@$(DOCKER_RUN_BUILD_TOOLS) pwsh -NoLogo -NoProfile -File Scripts/Build-ProvisioningISOs.ps1 -OutputPath ISOs
	@echo "✅ ISOs built successfully"
endif

build-next-ui:
ifeq ($(IN_CONTAINER),1)
	@echo "Building next-ui (in container)..."
	@cd next-ui && npm ci && npm run build
else
	@echo "🔨 Building next-ui Svelte application using build-tools container..."
	@$(DOCKER_RUN_BUILD_TOOLS) bash -c "cd next-ui && npm ci && npm run build"
	@echo "✅ next-ui build complete"
endif

build-static:
ifeq ($(IN_CONTAINER),1)
	@echo "Extracting static assets (in container)..."
	@cd server && npm install --omit=dev && python3 scripts/extract_icons.py && python3 scripts/extract_swagger_ui.py
else
	@echo "🔨 Extracting static assets using development container..."
	@docker compose -f docker-compose.dev.yml run --rm app bash -c \
		"cd /workspace/server && npm install --omit=dev && python scripts/extract_icons.py && python scripts/extract_swagger_ui.py"
	@echo "✅ Static assets extracted"
endif

# Production build
build: build-assets
	@echo "🐳 Building production Docker container..."
	docker build -f server/Dockerfile -t aetherv:latest .
	@echo "✅ Container built: aetherv:latest"

all: build-assets build
	@echo "✅ All components built successfully"

# Testing commands (container-based)
test-all: test-python test-js test-powershell test-svelte test-roundtrip
	@echo ""
	@echo "✅ All test suites completed successfully"

test-python:
	@echo "🧪 Running Python tests..."
	@docker compose -f docker-compose.dev.yml run --rm app \
		pytest tests/ --cov=app --cov-report=term-missing -v

test-js:
	@echo "🧪 Running JavaScript tests..."
	@docker compose -f docker-compose.dev.yml run --rm app \
		node --test /workspace/tests/js/*.test.js

test-powershell:
	@echo "🧪 Running PowerShell tests..."
	@$(DOCKER_RUN_BUILD_TOOLS) pwsh -NoProfile -Command "Invoke-Pester -Path Powershell/tests -CI"

test-svelte:
	@echo "🧪 Running Svelte type checks..."
	@$(DOCKER_RUN_BUILD_TOOLS) bash -c "cd next-ui && npm ci && npm run check"

test-roundtrip:
	@echo "🧪 Running protocol round-trip tests..."
	@docker compose -f docker-compose.dev.yml run --rm app \
		pytest tests/test_resource_operations.py tests/test_noop_operations.py -v

# Legacy commands (for backward compatibility)
dev:
	@echo "⚠️  Warning: 'make dev' is deprecated. Use 'make dev-up' instead."
	@echo "Starting legacy dev server..."
	@./server/dev.sh

run:
	@echo "⚠️  Warning: 'make run' is deprecated. Use 'make dev-up' instead."
	docker run -p 8000:8000 --env-file server/.env aetherv:latest

# Standalone targets that don't require containers
next-ui:
	@echo "⚠️  Warning: Use 'make build-next-ui' for container-based build"
	@cd next-ui && npm install && npm run build
	@echo "✅ next-ui build complete"

isos:
	@echo "⚠️  Warning: Use 'make build-isos' for container-based build"
	@echo "Building all assets (ISOs + static files) from latest source..."
	$(POWERSHELL) -NoLogo -NoProfile -File ./Scripts/Build-All-Assets.ps1

test:
	@echo "⚠️  Warning: 'make test' is deprecated. Use 'make test-all' instead."
	@echo "Running full test suite..."
	@echo ""
	@echo "=== Python Tests ==="
	@cd server && (\
		if [ -f ../.venv/bin/pytest ]; then \
			echo "Running pytest..." && ../.venv/bin/pytest tests/; \
		else \
			echo "Running pytest..." && pytest tests/; \
		fi \
	)
	@echo ""
	@echo "=== Python Type Checking ==="
	@cd server && (\
		if [ -f ../.venv/bin/mypy ]; then \
			echo "Running mypy type checker..." && ../.venv/bin/mypy .; \
		else \
			echo "Running mypy type checker..." && mypy .; \
		fi \
	)
	@echo ""
	@echo "=== JavaScript Tests ==="
	@echo "Running Node.js tests..."
	@node --test 'tests/js/*.test.js'
	@echo ""
	@echo "=== PowerShell Tests ==="
	@echo "Running Pester tests..."
	@$(POWERSHELL) -NoProfile -Command "Invoke-Pester -Path Powershell/tests -CI"
	@echo ""
	@echo "=== Round-trip Tests ==="
	@echo "Running protocol round-trip tests..."
	@cd server && (\
		if [ -f ../.venv/bin/pytest ]; then \
			PYTHONPATH=$$(pwd) ../.venv/bin/pytest tests/test_resource_operations.py tests/test_noop_operations.py -v; \
		else \
			PYTHONPATH=$$(pwd) pytest tests/test_resource_operations.py tests/test_noop_operations.py -v; \
		fi \
	)
	@echo ""
	@echo "✅ All test suites completed successfully"

# Kubernetes deployment
config-validate:
	@echo "Validating configuration schemas..."
	@if [ -f "Schemas/job-inputs.yaml" ]; then \
		echo "✅ Job inputs schema found"; \
	else \
		echo "❌ Job inputs schema missing"; \
		exit 1; \
	fi
	@echo "✅ Configuration validation complete"

deploy:
	kubectl apply -k server/k8s/

undeploy:
	kubectl delete -k server/k8s/

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
