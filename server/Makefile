.PHONY: help dev build run test clean deploy

help:
	@echo "Aether-V Orchestrator - Make commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev      - Start development server with hot reload"
	@echo "  make test     - Run tests (when implemented)"
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
	docker build -t aetherv-orchestrator:latest .

run:
	docker run -p 8000:8000 --env-file .env aetherv-orchestrator:latest

test:
	@echo "Tests not yet implemented"
	# pytest tests/

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
