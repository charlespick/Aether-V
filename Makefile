.PHONY: help dev run build build-assets build-isos build-next-ui test test-python test-powershell test-roundtrip clean

help:
	@echo "Aether-V - VM Management Platform"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make dev           - Start local development server (Python + hot reload)"
	@echo "  make run           - Run production Docker image (after make build)"
	@echo ""
	@echo "🔨 Build & Assets:"
	@echo "  make build-assets  - Build all assets (ISOs + next-ui)"
	@echo "  make build-isos    - Build provisioning ISOs for Windows/Linux"
	@echo "  make build-next-ui - Build next-ui Svelte application"
	@echo "  make build         - Build production Docker image"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test          - Run complete test suite"
	@echo "  make test-python   - Run Python tests only"
	@echo "  make test-powershell - Run PowerShell tests only"
	@echo "  make test-roundtrip - Run round-trip protocol tests"
	@echo ""
	@echo "🔧 Utility:"
	@echo "  make clean         - Clean up temporary files and caches"

# Development - local Python server with hot reload
dev:
	@echo "🚀 Starting local development server..."
	@echo "   Web UI: http://localhost:8000"
	@echo "   API Docs: http://localhost:8000/docs"
	@echo ""
	cd server && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production - run the built Docker image
run:
	@echo "� Running production image..."
	@if ! docker image inspect aetherv:latest >/dev/null 2>&1; then \
		echo "❌ Image 'aetherv:latest' not found. Run 'make build' first."; \
		exit 1; \
	fi
	docker run --rm -p 8000:8000 \
		--env-file server/.env \
		--name aetherv \
		aetherv:latest

# Build assets commands
build-assets: build-isos build-next-ui
	@echo "✅ All assets built successfully"

build-isos:
	@echo "🔨 Building provisioning ISOs..."
	@docker pull ghcr.io/charlespick/aetherv-build-tools:latest || \
		docker build -f build-tools/Dockerfile -t ghcr.io/charlespick/aetherv-build-tools:latest build-tools
	@docker run --rm \
		-v "$(PWD):/github/workspace" \
		ghcr.io/charlespick/aetherv-build-tools:latest \
		/github/workspace/Scripts/Build-ProvisioningISOs.ps1
	@echo "✅ ISOs built successfully"

build-next-ui:
	@echo "🔨 Building next-ui Svelte application..."
	cd next-ui && npm ci && npm run build
	@echo "✅ next-ui build complete"

# Production build
build: build-assets
	@echo "🐳 Building production Docker container..."
	@GIT_COMMIT=$$(git rev-parse HEAD 2>/dev/null || echo "unknown"); \
	GIT_REF=$$(git symbolic-ref -q --short HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown"); \
	if git rev-parse --verify HEAD >/dev/null 2>&1; then \
		if git symbolic-ref -q HEAD >/dev/null 2>&1; then \
			GIT_STATE="branch"; \
		else \
			GIT_STATE="detached"; \
		fi; \
	else \
		GIT_STATE="unknown"; \
	fi; \
	VERSION=$$(cat version 2>/dev/null || echo "unknown"); \
	BUILD_TIME=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	BUILD_HOST=$$(hostname); \
	docker build --target application -t aetherv:latest \
		--build-arg GIT_COMMIT="$$GIT_COMMIT" \
		--build-arg GIT_REF="$$GIT_REF" \
		--build-arg GIT_STATE="$$GIT_STATE" \
		--build-arg VERSION="$$VERSION" \
		--build-arg BUILD_TIME="$$BUILD_TIME" \
		--build-arg BUILD_HOST="$$BUILD_HOST" \
		.
	@echo "✅ Container built: aetherv:latest"

# Testing - simple and unified
test: test-python test-powershell test-roundtrip
	@echo ""
	@echo "✅ All tests passed"

test-python:
	@echo "🧪 Running Python tests..."
	@cd server && pytest tests/ --cov=app --cov-report=term-missing -v

test-powershell:
	@echo "🧪 Running PowerShell tests..."
	pwsh -NoProfile -Command "Invoke-Pester -Path Powershell/tests -CI"

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
