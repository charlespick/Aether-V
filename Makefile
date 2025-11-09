.PHONY: help dev build run test test-python test-powershell test-js test-all clean deploy isos config-validate all

POWERSHELL ?= pwsh

help:
	@echo "HLVMM - High-Level VM Management - Make commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev           - Start development server with hot reload"
	@echo "  make test          - Run all tests (Python, PowerShell, JavaScript)"
	@echo "  make test-python   - Run Python tests only"
	@echo "  make test-powershell - Run PowerShell tests only"
	@echo "  make test-js       - Run JavaScript tests only"
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
	@echo "Building provisioning ISOs from latest source..."
	$(POWERSHELL) -NoLogo -NoProfile -File ./Scripts/Build-ProvisioningISOs.ps1

run:
	docker run -p 8000:8000 --env-file server/.env aetherv:latest

test: test-python test-powershell test-js
	@echo "✅ All test suites completed"

test-python:
	@echo "Running Python tests..."
	@cd server && ./test.sh

test-powershell:
	@echo "Running PowerShell tests..."
	@$(POWERSHELL) -NoLogo -NoProfile -File tests/powershell/run-tests.ps1 -Coverage

test-js:
	@echo "Running JavaScript tests..."
	@cd server && npm test

test-all: test
	@echo "✅ All tests completed successfully"

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
	rm -rf server/coverage.xml server/coverage-js
	rm -rf server/node_modules 2>/dev/null || true
	rm -rf build/ 2>/dev/null || true
	rm -rf ISOs/ 2>/dev/null || true
	rm -rf coverage-ps.xml 2>/dev/null || true
	@echo "✅ Cleanup complete"
