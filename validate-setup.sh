#!/bin/bash
# Validation script for new container-first development workflow
# Run this after implementing changes to verify everything works

# Don't exit on errors - we want to see all results
set +e

echo "🧪 Aether-V Development Workflow Validation"
echo "==========================================="
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track results
PASSED=0
FAILED=0

# Helper functions
pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Test 1: Check required files exist
echo "1. Checking required files..."
FILES=(
    "docker-compose.dev.yml"
    "server/Dockerfile"
    ".devcontainer/devcontainer.json"
    "Makefile"
    "Docs/DEVELOPMENT.md"
    "Docs/MIGRATION.md"
    "QUICK_REFERENCE.md"
    ".dockerignore"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        pass "$file exists"
    else
        fail "$file missing"
    fi
done

echo ""

# Test 2: Check Dockerfile has development stage
echo "2. Checking Dockerfile structure..."
if grep -q "FROM.*AS development" server/Dockerfile; then
    pass "Development stage exists"
else
    fail "Development stage missing"
fi

if grep -q "FROM.*AS application" server/Dockerfile; then
    pass "Application stage exists"
else
    fail "Application stage missing"
fi

echo ""

# Test 3: Check docker-compose.dev.yml structure
echo "3. Checking docker-compose.dev.yml..."
if grep -q "services:" docker-compose.dev.yml && grep -q "app:" docker-compose.dev.yml; then
    pass "App service defined"
else
    fail "App service missing"
fi

if grep -q "build-tools" docker-compose.dev.yml; then
    pass "Build-tools service defined"
else
    fail "Build-tools service missing"
fi

if grep -q "target: development" docker-compose.dev.yml; then
    pass "Uses development target"
else
    fail "Development target not specified"
fi

echo ""

# Test 4: Check Makefile has new commands
echo "4. Checking Makefile commands..."
COMMANDS=(
    "dev-up"
    "dev-down"
    "dev-shell"
    "test-all"
    "test-python"
    "build-assets"
    "build-isos"
    "build-next-ui"
)

for cmd in "${COMMANDS[@]}"; do
    if grep -q "^${cmd}:" Makefile; then
        pass "make $cmd defined"
    else
        fail "make $cmd missing"
    fi
done

echo ""

# Test 5: Check devcontainer.json configuration
echo "5. Checking devcontainer.json..."
if grep -q "dockerComposeFile" .devcontainer/devcontainer.json; then
    pass "Uses docker-compose"
else
    fail "Not using docker-compose"
fi

if grep -q "onCreateCommand" .devcontainer/devcontainer.json; then
    if grep -q "install-app-deps" .devcontainer/devcontainer.json; then
        fail "Still installing app deps (should be removed)"
    else
        pass "No app deps installation in onCreateCommand"
    fi
else
    warn "No onCreateCommand (acceptable)"
fi

echo ""

# Test 6: Docker availability
echo "6. Checking Docker availability..."
if command -v docker &> /dev/null; then
    pass "Docker installed"
    
    if docker ps &> /dev/null; then
        pass "Docker daemon running"
    else
        fail "Docker daemon not running"
    fi
else
    fail "Docker not installed"
fi

echo ""

# Test 7: Check CI workflows updated
echo "7. Checking CI workflows..."
if grep -q "target: development" .github/workflows/tests.yml; then
    pass "CI uses development container"
else
    warn "CI may not use development container"
fi

if grep -q "build-tools" .github/workflows/build-server.yml; then
    pass "Build workflow uses build-tools"
else
    warn "Build workflow may not use build-tools"
fi

echo ""

# Test 8: Documentation checks
echo "8. Checking documentation..."
if grep -q "make dev-up" Docs/DEVELOPMENT.md; then
    pass "DEVELOPMENT.md references new commands"
else
    fail "DEVELOPMENT.md needs update"
fi

if grep -q "container-first" Docs/DEVELOPMENT.md; then
    pass "DEVELOPMENT.md mentions container-first"
else
    warn "DEVELOPMENT.md could emphasize container-first more"
fi

echo ""

# Test 9: Optional functional tests (if Docker is running)
if docker ps &> /dev/null; then
    echo "9. Running optional functional tests..."
    
    # Test docker-compose config
    if docker compose -f docker-compose.dev.yml config &> /dev/null; then
        pass "docker-compose.dev.yml is valid"
    else
        fail "docker-compose.dev.yml has syntax errors"
    fi
    
    # Test Dockerfile development stage
    echo "   Building development container (this may take a moment)..."
    if docker build -f server/Dockerfile --target development -t aetherv-test:dev . &> /tmp/docker-build.log; then
        pass "Development container builds successfully"
        docker rmi aetherv-test:dev &> /dev/null || true
    else
        fail "Development container build failed (see /tmp/docker-build.log)"
    fi
else
    echo "9. Skipping functional tests (Docker not running)"
fi

echo ""
echo "==========================================="
echo "Validation Results"
echo "==========================================="
echo -e "${GREEN}Passed: $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $FAILED${NC}"
else
    echo -e "${GREEN}Failed: $FAILED${NC}"
fi

echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! Setup looks good.${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Run: make dev-up"
    echo "2. Visit: http://localhost:8000"
    echo "3. Test: make test-all"
    echo ""
    echo "See Docs/DEVELOPMENT.md for complete guide."
    exit 0
else
    echo -e "${RED}❌ Some checks failed. Please review above output.${NC}"
    echo ""
    echo "See IMPLEMENTATION_SUMMARY.md for expected setup."
    exit 1
fi
