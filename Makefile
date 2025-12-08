.PHONY: help dev run build build-assets build-isos build-next-ui build-static test test-python test-powershell test-roundtrip clean

help:
	@echo "Aether-V - VM Management Platform"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make dev           - Start local development server (Python + hot reload)"
	@echo "  make run           - Run production Docker image (after make build)"
	@echo ""
	@echo "🔨 Build & Assets:"
	@echo "  make build-assets  - Build all assets (ISOs + next-ui + static)"
	@echo "  make build-isos    - Build provisioning ISOs for Windows/Linux"
	@echo "  make build-next-ui - Build next-ui Svelte application"
	@echo "  make build-static  - Extract static assets (icons, Swagger UI)"
	@echo "  make build         - Build production Docker image"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test-all      - Run complete test suite"
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
build-assets: build-isos build-next-ui build-static
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

build-static: build-next-ui
	@echo "🔨 Extracting static assets for Python UI..."
	python3 server/scripts/extract_icons.py && python3 server/scripts/extract_swagger_ui.py
	@echo "✅ Static assets extracted"

# Production build
build: build-assets
	@echo "🐳 Building production Docker container..."
	docker build --target application -t aetherv:latest .
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
