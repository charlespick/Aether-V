#!/bin/bash
# Quick start script for local development using Docker

set -e

echo "🚀 Aether-V Orchestrator - Development Setup (Docker)"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo "⚙️  Please edit .env and configure your settings:"
    echo "   - Set HYPERV_HOSTS to your Hyper-V hosts"
    echo "   - Configure WinRM credentials"
    echo "   - Set OIDC_ENABLED=false for quick dev setup without auth"
    echo ""
    read -p "Press Enter when ready to continue..."
fi

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
fi

# Check if Docker image exists, build if needed
if ! docker image inspect aetherv &> /dev/null; then
    echo "🔨 Building Docker image with artifacts..."
    echo "📁 Building from repository root to include artifacts..."
    cd ..
    docker build -f server/Dockerfile -t aetherv .
    cd server
else
    echo "✅ Docker image 'aetherv' found"
    echo "💡 To rebuild with latest artifacts, run: cd .. && docker build -f server/Dockerfile -t aetherv ."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🎯 Starting Aether-V Orchestrator in Docker..."
echo "   - Web UI: http://localhost:8000"
echo "   - API Docs: http://localhost:8000/docs"
echo "   - Health Check: http://localhost:8000/healthz"
echo ""
echo "🔄 Hot reload enabled - code changes will be picked up automatically"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

# Run the application in Docker with volume mount for hot reload
docker run --rm -it \
    --name hlvmm-dev \
    -p 8000:8000 \
    -v "$(pwd):/app" \
    -v "$(pwd)/.env:/app/.env" \
    --env-file .env \
    aetherv \
    python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
