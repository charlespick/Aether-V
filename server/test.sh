#!/bin/bash
# Test runner script for Aether-V Server
# Runs all Python tests with coverage reporting
# Works in local, devcontainer, and CI environments

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧪 Aether-V Server Test Suite"
echo "=============================="
echo ""

# Check if pytest is installed
if ! python -m pytest --version &> /dev/null; then
    echo "❌ pytest not found. Installing development dependencies..."
    pip install -r requirements-dev.txt
    echo ""
fi

# Parse command line arguments
COVERAGE=true
PARALLEL=false
MARKERS=""
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-coverage)
            COVERAGE=false
            shift
            ;;
        --parallel)
            PARALLEL=true
            shift
            ;;
        --unit)
            MARKERS="-m unit"
            shift
            ;;
        --integration)
            MARKERS="-m integration"
            shift
            ;;
        -v|--verbose)
            VERBOSE="-vv"
            shift
            ;;
        --help)
            echo "Usage: ./test.sh [options]"
            echo ""
            echo "Options:"
            echo "  --no-coverage    Skip coverage reporting"
            echo "  --parallel       Run tests in parallel"
            echo "  --unit          Run only unit tests"
            echo "  --integration   Run only integration tests"
            echo "  -v, --verbose   Verbose output"
            echo "  --help          Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="python -m pytest"

if [ "$COVERAGE" = true ]; then
    echo "📊 Coverage reporting enabled"
else
    PYTEST_CMD="$PYTEST_CMD --no-cov"
    echo "⚠️  Coverage reporting disabled"
fi

if [ "$PARALLEL" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -n auto"
    echo "🚀 Parallel execution enabled"
fi

if [ -n "$MARKERS" ]; then
    PYTEST_CMD="$PYTEST_CMD $MARKERS"
fi

if [ -n "$VERBOSE" ]; then
    PYTEST_CMD="$PYTEST_CMD $VERBOSE"
fi

echo ""
echo "Running: $PYTEST_CMD"
echo ""

# Run tests
$PYTEST_CMD

# Report results
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ All tests passed!"
    if [ "$COVERAGE" = true ]; then
        echo ""
        echo "📊 Coverage report generated:"
        echo "   - Terminal: see above"
        echo "   - HTML: open htmlcov/index.html"
        echo "   - XML: coverage.xml"
    fi
    exit 0
else
    echo ""
    echo "❌ Some tests failed"
    exit 1
fi
