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

# Install PowerShell if not present (needed for ISO builds)
if ! command -v pwsh &> /dev/null; then
    echo "📦 Installing PowerShell..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq wget apt-transport-https software-properties-common > /dev/null 2>&1
    wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb"
    sudo dpkg -i packages-microsoft-prod.deb > /dev/null 2>&1
    rm packages-microsoft-prod.deb
    sudo apt-get update -qq
    sudo apt-get install -y -qq powershell > /dev/null 2>&1
    echo "✅ PowerShell installed"
else
    echo "✅ PowerShell already installed"
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
