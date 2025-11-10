#!/bin/bash
# Setup script for local development
# Extracts static assets (icons and swagger-ui) from node_modules

set -e

echo "🔧 Setting up local development environment..."
echo ""

cd "$(dirname "$0")"

# Install npm dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 Installing npm dependencies..."
    npm install --omit=dev
else
    echo "✅ npm dependencies already installed"
fi

# Extract icons
echo "🎨 Extracting icon assets..."
python scripts/extract_icons.py

# Extract Swagger UI assets
echo "📚 Extracting Swagger UI assets..."
python scripts/extract_swagger_ui.py

echo ""
echo "✅ Local development setup complete!"
echo ""
echo "You can now run the server locally with:"
echo "  python -m uvicorn app.main:app --reload"
echo ""
