.PHONY: help run build build-assets build-isos build-next-ui build-static test test-python test-powershell test-roundtrip clean

help:
	@echo "Aether-V - VM Management Platform"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make dev-up        - Start development server with hot reload (docker compose)"
	@echo "  make dev-down      - Stop development server"
	@echo "  make run           - Run production image (after make build)"
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

# Development - uses docker-compose for hot reload
dev-up:
	@echo "🚀 Starting development server with hot reload..."
	docker compose -f docker-compose.dev.yml up -d --build app-server
	@echo ""
	@echo "✅ Development server running!"
	@echo "   - Web UI: http://localhost:8000"
	@echo "   - API Docs: http://localhost:8000/docs"
	@echo ""
	@echo "   make dev-down   - Stop server"

dev-down:
	@echo "🛑 Stopping development environment..."
	docker compose -f docker-compose.dev.yml down

# Production - just run the built image
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

dev-test:
	@echo "🧪 Running tests..."
	pytest server/tests/ -v

# Build assets commands - run directly (tools already in devcontainer/CI)
build-assets: build-isos build-next-ui build-static
	@echo "✅ All assets built successfully"

build-isos:
	@echo "� Building provisioning ISOs..."
	@docker build -f build-tools/Dockerfile -t aetherv-build-tools:latest build-tools
	@docker run --rm \
		-v "$(PWD)/Assets:/workspace/Assets" \
		-v "$(PWD)/build-tools:/workspace/build-tools" \
		-v "$(PWD)/server/app/static/downloads:/workspace/output" \
		aetherv-build-tools:latest \
		/workspace/build-tools/Create-BootableISO.ps1 -All
	@echo "✅ ISOs built successfully"

build-next-ui:
	@echo "🔨 Building next-ui Svelte application..."
	cd next-ui && npm ci && npm run build
	@echo "✅ next-ui build complete"

build-static:
	@echo "🔨 Extracting static assets..."
	cd server && npm install --omit=dev && python3 scripts/extract_icons.py && python3 scripts/extract_swagger_ui.py
	@echo "✅ Static assets extracted"

# Production build
build: build-assets
	@echo "🐳 Building production Docker container..."
	docker build -f server/Dockerfile --target application -t aetherv:latest .
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
