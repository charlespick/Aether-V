#!/bin/bash
# Unified test runner for all test suites (Python, PowerShell, JavaScript)
# This script runs all tests locally the same way they run in CI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧪 Aether-V Unified Test Suite"
echo "==============================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PYTHON_PASSED=false
POWERSHELL_PASSED=false
JS_PASSED=false

# Parse command line arguments
RUN_PYTHON=true
RUN_POWERSHELL=true
RUN_JS=true
COVERAGE=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --python-only)
            RUN_POWERSHELL=false
            RUN_JS=false
            shift
            ;;
        --powershell-only)
            RUN_PYTHON=false
            RUN_JS=false
            shift
            ;;
        --js-only)
            RUN_PYTHON=false
            RUN_POWERSHELL=false
            shift
            ;;
        --no-coverage)
            COVERAGE=false
            shift
            ;;
        --help)
            echo "Usage: ./run-all-tests.sh [options]"
            echo ""
            echo "Options:"
            echo "  --python-only       Run only Python tests"
            echo "  --powershell-only   Run only PowerShell tests"
            echo "  --js-only          Run only JavaScript tests"
            echo "  --no-coverage      Skip coverage reporting"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Python Tests
if [ "$RUN_PYTHON" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🐍 Running Python Tests"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    cd server
    if [ "$COVERAGE" = true ]; then
        ./test.sh
    else
        ./test.sh --no-coverage
    fi
    
    if [ $? -eq 0 ]; then
        PYTHON_PASSED=true
        echo -e "${GREEN}✅ Python tests passed${NC}"
    else
        echo -e "${RED}❌ Python tests failed${NC}"
    fi
    cd ..
    echo ""
fi

# PowerShell Tests
if [ "$RUN_POWERSHELL" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚡ Running PowerShell Tests"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Check if pwsh is available
    if ! command -v pwsh &> /dev/null; then
        echo -e "${YELLOW}⚠️  PowerShell (pwsh) not found, skipping PowerShell tests${NC}"
        POWERSHELL_PASSED=true  # Don't fail if pwsh not available
    else
        if [ "$COVERAGE" = true ]; then
            pwsh tests/powershell/run-tests.ps1 -Coverage
        else
            pwsh tests/powershell/run-tests.ps1
        fi
        
        if [ $? -eq 0 ]; then
            POWERSHELL_PASSED=true
            echo -e "${GREEN}✅ PowerShell tests passed${NC}"
        else
            echo -e "${RED}❌ PowerShell tests failed${NC}"
        fi
    fi
    echo ""
fi

# JavaScript Tests
if [ "$RUN_JS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📦 Running JavaScript Tests"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    cd server
    
    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        echo "📥 Installing Node.js dependencies..."
        npm install
        echo ""
    fi
    
    if [ "$COVERAGE" = true ]; then
        npm run test:coverage
    else
        npm test
    fi
    
    if [ $? -eq 0 ]; then
        JS_PASSED=true
        echo -e "${GREEN}✅ JavaScript tests passed${NC}"
    else
        echo -e "${RED}❌ JavaScript tests failed${NC}"
    fi
    cd ..
    echo ""
fi

# Final Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Test Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ALL_PASSED=true

if [ "$RUN_PYTHON" = true ]; then
    if [ "$PYTHON_PASSED" = true ]; then
        echo -e "Python:     ${GREEN}✅ PASSED${NC}"
    else
        echo -e "Python:     ${RED}❌ FAILED${NC}"
        ALL_PASSED=false
    fi
fi

if [ "$RUN_POWERSHELL" = true ]; then
    if [ "$POWERSHELL_PASSED" = true ]; then
        echo -e "PowerShell: ${GREEN}✅ PASSED${NC}"
    else
        echo -e "PowerShell: ${RED}❌ FAILED${NC}"
        ALL_PASSED=false
    fi
fi

if [ "$RUN_JS" = true ]; then
    if [ "$JS_PASSED" = true ]; then
        echo -e "JavaScript: ${GREEN}✅ PASSED${NC}"
    else
        echo -e "JavaScript: ${RED}❌ FAILED${NC}"
        ALL_PASSED=false
    fi
fi

echo ""

if [ "$ALL_PASSED" = true ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✅ All test suites passed!${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 0
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}❌ Some test suites failed${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 1
fi
