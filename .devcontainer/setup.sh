#!/bin/bash
# DevContainer setup - runs once on container creation (non-blocking)

set -e

echo "🚀 Setting up Aether-V development environment..."

# Create .env if it doesn't exist
if [ ! -f server/.env ]; then
    if [ -f server/.env.example ]; then
        cp server/.env.example server/.env
        echo "✅ Created server/.env from example"
    fi
fi

# Install Python dependencies for IntelliSense
echo "📦 Installing Python packages for IntelliSense..."
pip install --no-cache-dir -r server/requirements.txt
pip install --no-cache-dir pytest pytest-asyncio pytest-cov httpx black flake8

echo ""
echo "✅ DevContainer ready!"
echo ""
echo "Quick start:"
echo "  make dev-up       - Start development server"
echo "  make test-all     - Run all tests"
echo "  make build-assets - Build ISOs and next-ui"
echo ""
echo "See Makefile for all commands."
