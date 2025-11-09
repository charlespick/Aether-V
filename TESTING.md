# Testing Guide

This document describes the comprehensive testing infrastructure for Aether-V.

## Overview

Aether-V uses a multi-language testing approach covering:
- **Python**: Server application, services, and API
- **PowerShell**: Host automation scripts and provisioning logic
- **JavaScript**: Frontend web interface

All tests are designed to run in CI environments without requiring actual Hyper-V hosts or Windows-specific PowerShell commands.

## Quick Start

### Run All Tests

```bash
make test
```

### Run Specific Test Suites

```bash
# Python tests only
make test-python

# PowerShell tests only
make test-powershell

# JavaScript tests only
make test-js
```

## Python Testing

### Setup

Install development dependencies:

```bash
cd server
pip install -r requirements-dev.txt
```

### Running Tests

```bash
# Run all Python tests with coverage
cd server
./test.sh

# Run without coverage
./test.sh --no-coverage

# Run tests in parallel
./test.sh --parallel

# Run only unit tests
./test.sh --unit

# Verbose output
./test.sh -v
```

### Test Organization

Python tests are located in `server/tests/` and follow pytest conventions:

- `test_*.py` - Test files
- Organized by service/module being tested
- Use markers to categorize tests:
  - `@pytest.mark.unit` - Fast unit tests
  - `@pytest.mark.integration` - Integration tests
  - `@pytest.mark.winrm` - Tests involving WinRM (mocked in CI)
  - `@pytest.mark.requires_hosts` - Tests requiring actual hosts (skipped in CI)

### Writing Python Tests

Example test structure:

```python
import pytest
from unittest.mock import Mock, patch

@pytest.mark.unit
def test_service_function():
    """Test a specific function."""
    result = my_function(input)
    assert result == expected

@pytest.mark.integration
@pytest.mark.winrm
async def test_winrm_service():
    """Test WinRM service with mocked connections."""
    with patch('app.services.winrm_service.WSMan') as mock_wsman:
        # Configure mock
        mock_wsman.return_value = Mock()
        
        # Run test
        result = await service.execute_command("test")
        assert result is not None
```

### Coverage

Coverage reports are generated in multiple formats:
- **Terminal**: Summary displayed after test run
- **HTML**: `server/htmlcov/index.html`
- **XML**: `server/coverage.xml` (for CI integration)

## PowerShell Testing

### Setup

Install Pester 5.x:

```powershell
Install-Module -Name Pester -MinimumVersion 5.0.0 -Force -Scope CurrentUser
```

### Running Tests

```powershell
# Run all PowerShell tests
pwsh tests/powershell/run-tests.ps1

# Run with coverage
pwsh tests/powershell/run-tests.ps1 -Coverage

# CI mode (less verbose)
pwsh tests/powershell/run-tests.ps1 -CI
```

### Test Organization

PowerShell tests are located in `tests/powershell/` and follow Pester 5 conventions:

- `*.Tests.ps1` - Test files
- Use `Describe`, `Context`, and `It` blocks
- Mock external dependencies (WinRM, Hyper-V cmdlets)

### Writing PowerShell Tests

Example test structure:

```powershell
BeforeAll {
    # Import module under test
    . $PSScriptRoot/../../Powershell/MyScript.ps1
    
    # Mock external commands
    Mock Get-VM { return @{ Name = "test-vm"; State = "Running" } }
}

Describe "MyScript Tests" {
    Context "When VM exists" {
        It "Should return VM information" {
            $result = Get-VMInfo -Name "test-vm"
            $result.Name | Should -Be "test-vm"
        }
    }
    
    Context "When VM doesn't exist" {
        BeforeAll {
            Mock Get-VM { throw "VM not found" }
        }
        
        It "Should handle error gracefully" {
            { Get-VMInfo -Name "missing-vm" } | Should -Throw
        }
    }
}
```

### Mocking Strategy for CI

Since CI runs on Linux with PowerShell Core, mock Windows-specific cmdlets:

```powershell
# Mock Hyper-V cmdlets
Mock Get-VM { }
Mock New-VM { }
Mock Start-VM { }
Mock Stop-VM { }

# Mock WinRM/PSRemoting
Mock Invoke-Command { }
Mock New-PSSession { }
```

## JavaScript Testing

### Setup

Install Node.js dependencies:

```bash
cd server
npm install
```

### Running Tests

```bash
# Run all JavaScript tests
npm test

# Run with coverage
npm run test:coverage

# Watch mode for development
npm run test:watch
```

### Test Organization

JavaScript tests are located in `server/tests/js/` and use Jest:

- `*.test.js` - Test files
- Tests run in jsdom environment (simulated browser)
- Mock WebSocket and other browser APIs

### Writing JavaScript Tests

Example test structure:

```javascript
describe('WebSocket Client', () => {
  let mockWebSocket;
  
  beforeEach(() => {
    // Mock WebSocket
    mockWebSocket = {
      send: jest.fn(),
      close: jest.fn(),
      readyState: WebSocket.OPEN
    };
    
    global.WebSocket = jest.fn(() => mockWebSocket);
  });
  
  test('should connect to server', () => {
    const client = new WebSocketClient('ws://localhost:8000');
    expect(global.WebSocket).toHaveBeenCalledWith('ws://localhost:8000');
  });
  
  test('should send messages', () => {
    const client = new WebSocketClient('ws://localhost:8000');
    client.send({ type: 'test' });
    expect(mockWebSocket.send).toHaveBeenCalled();
  });
});
```

## Integration Testing

Integration tests verify interactions between components:

### Python-PowerShell Integration

Test Python code that invokes PowerShell scripts:

```python
@pytest.mark.integration
@pytest.mark.powershell
async def test_invoke_powershell_script():
    """Test Python invoking PowerShell via WinRM."""
    with patch('pypsrp.powershell.PowerShell') as mock_ps:
        # Configure mock PowerShell session
        mock_ps.return_value.invoke.return_value = []
        
        # Test the integration
        service = WinRMService(...)
        result = await service.execute_script("test.ps1")
        
        assert result is not None
```

### API-Frontend Integration

Test API endpoints that frontend JavaScript consumes:

```python
@pytest.mark.integration
async def test_api_endpoint(test_client):
    """Test API endpoint used by frontend."""
    response = await test_client.get("/api/v1/inventory")
    assert response.status_code == 200
    data = response.json()
    assert "hosts" in data
```

## CI/CD Integration

### GitHub Actions

Tests run automatically on pull requests via `.github/workflows/test.yml`:

1. **Python Tests**: Run on Ubuntu with Python 3.11
2. **PowerShell Tests**: Run on Ubuntu with PowerShell Core
3. **JavaScript Tests**: Run on Ubuntu with Node.js 20

All tests must pass before merging.

### Coverage Reporting

Coverage reports are:
- Uploaded to Codecov for tracking
- Available as artifacts in GitHub Actions
- Commented on PRs automatically

### PR Comments

Test results are automatically commented on PRs with:
- Pass/fail status for each test suite
- Links to coverage reports
- Summary of test execution

## Development Workflow

### Local Development

1. **Before making changes**: Run tests to establish baseline
   ```bash
   make test
   ```

2. **During development**: Use watch mode for rapid feedback
   ```bash
   # Python: Run specific test file
   cd server
   python -m pytest tests/test_myservice.py -v
   
   # JavaScript: Watch mode
   npm run test:watch
   ```

3. **Before committing**: Run full test suite
   ```bash
   make test
   ```

### DevContainer

The devcontainer is pre-configured with all testing tools:

- Python testing tools (pytest, coverage)
- PowerShell with Pester
- Node.js with Jest
- All dependencies installed automatically

Just open in VS Code with Dev Containers extension and run:

```bash
make test
```

## Best Practices

### 1. Mock External Dependencies

Always mock external systems (Hyper-V, WinRM, real VMs):

```python
# Good: Mocked WinRM
with patch('app.services.winrm_service.WSMan'):
    result = service.connect()

# Bad: Real WinRM connection
result = service.connect()  # Will fail in CI
```

### 2. Test Isolation

Each test should be independent:

```python
# Good: Self-contained test
def test_function():
    input_data = create_test_data()
    result = function(input_data)
    assert result == expected

# Bad: Depends on previous test state
def test_function():
    result = function(global_state)  # Fragile!
```

### 3. Descriptive Test Names

Use clear, descriptive names:

```python
# Good
def test_winrm_service_handles_connection_timeout_gracefully():
    ...

# Bad
def test_service():
    ...
```

### 4. Test Both Success and Failure

```python
def test_create_vm_success():
    """Test successful VM creation."""
    ...

def test_create_vm_handles_duplicate_name_error():
    """Test error handling when VM name already exists."""
    ...
```

### 5. Use Markers

Categorize tests with markers:

```python
@pytest.mark.unit
@pytest.mark.fast
def test_utility_function():
    ...

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.winrm
async def test_full_workflow():
    ...
```

## Troubleshooting

### Tests Fail Locally But Pass in CI

- Check Python/Node.js version matches CI
- Verify all dependencies are installed
- Check for OS-specific code (Linux vs Windows)

### Tests Pass Locally But Fail in CI

- Likely using real external resources instead of mocks
- Check for hardcoded paths
- Verify environment variables are set correctly

### Coverage Lower Than Expected

- Check that all code paths are tested
- Look for untested error handling
- Review pytest coverage report: `open server/htmlcov/index.html`

### PowerShell Tests Fail on Linux

- Ensure using PowerShell Core compatible code
- Mock all Windows-specific cmdlets
- Avoid `windows-powershell` specific features

## Further Reading

- [pytest documentation](https://docs.pytest.org/)
- [Pester documentation](https://pester.dev/)
- [Jest documentation](https://jestjs.io/)
- [GitHub Actions testing](https://docs.github.com/en/actions)
