.PHONY: help dev build run test clean deploy isos config-validate all

POWERSHELL ?= pwsh

help:
	@echo "HLVMM - High-Level VM Management - Make commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev           - Start development server with hot reload"
	@echo "  make test          - Run full test suite (pytest, mypy, npm, pester, round-trip)"
	@echo "  make all           - Build everything (ISOs + container)"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  make isos          - Build provisioning ISOs for Windows/Linux"
	@echo "  make build         - Build Docker container (includes ISOs)"
	@echo "  make run           - Run container locally"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make deploy        - Deploy to Kubernetes using kubectl"
	@echo "  make undeploy      - Remove from Kubernetes"
	@echo ""
	@echo "Validation:"
	@echo "  make config-validate - Validate configuration schemas"
	@echo ""
	@echo "Utility:"
	@echo "  make clean         - Clean up temporary files and caches"

dev:
	@./server/dev.sh

build: isos
	docker build -f server/Dockerfile -t aetherv:latest .

isos:
	@echo "Building all assets (ISOs + static files) from latest source..."
	$(POWERSHELL) -NoLogo -NoProfile -File ./Scripts/Build-All-Assets.ps1

run:
	docker run -p 8000:8000 --env-file server/.env aetherv:latest

test:
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
	@node --test tests/js
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

all: isos build
	@echo "✅ All components built successfully"

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

clean:
	@echo "Cleaning up temporary files and caches..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -rf server/.pytest_cache server/htmlcov server/.coverage
	rm -rf build/ 2>/dev/null || true
	rm -rf ISOs/ 2>/dev/null || true
	@echo "✅ Cleanup complete"
