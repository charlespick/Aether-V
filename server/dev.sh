#!/bin/bash
# Quick start script for local development

set -e

echo "🚀 Aether-V Orchestrator - Development Setup"
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

# Check Python version
python3 --version || { echo "❌ Python 3 not found"; exit 1; }

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📚 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "🎯 Starting Aether-V Orchestrator..."
echo "   - Web UI: http://localhost:8000"
echo "   - API Docs: http://localhost:8000/docs"
echo "   - Health Check: http://localhost:8000/healthz"
echo ""

# Run the application
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
