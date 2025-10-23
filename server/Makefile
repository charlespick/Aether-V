.PHONY: help dev build run test clean deploy venv install-venv

help:
	@echo "Aether-V Orchestrator - Make commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev      - Start development server with hot reload"
	@echo "  make test     - Run test suite"
	@echo ""
	@echo "Docker:"
	@echo "  make build    - Build Docker container"
	@echo "  make run      - Run container locally"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make deploy   - Deploy to Kubernetes using kubectl"
	@echo "  make undeploy - Remove from Kubernetes"
	@echo ""
	@echo "Utility:"
	@echo "  make clean    - Clean up temporary files"

dev:
	@./dev.sh

build:
	cd .. && docker build -f server/Dockerfile -t aetherv:latest .

run:
	docker run -p 8000:8000 --env-file .env aetherv:latest

PYTEST_ARGS ?=
PYTHON ?= python3
VENV_DIR ?= .venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP := $(VENV_BIN)/pip
REQUIREMENTS := requirements.txt requirements-test.txt

venv: $(VENV_PYTHON)

$(VENV_PYTHON): $(REQUIREMENTS)
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "Creating virtual environment in $(VENV_DIR)"; \
		$(PYTHON) -m venv $(VENV_DIR); \
	fi
	@echo "Installing server dependencies"
	@"$(VENV_PIP)" install -r requirements-test.txt || { \
		echo "Warning: Failed to install server requirements; tests may be skipped."; \
	}

install-venv: venv

test: venv
	@if "$(VENV_PYTHON)" -m pytest --version >/dev/null 2>&1; then \
		"$(VENV_PYTHON)" -m pytest tests $(PYTEST_ARGS); \
	else \
		echo "Pytest is not available in $(VENV_DIR); skipping tests."; \
	fi

deploy:
	kubectl apply -k k8s/

undeploy:
	kubectl delete -k k8s/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -rf .pytest_cache htmlcov .coverage
