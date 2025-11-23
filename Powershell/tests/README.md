# PowerShell Testing Documentation

This directory contains comprehensive unit and integration tests for the Aether-V PowerShell scripts, specifically designed to run in CI/CD environments without requiring actual Hyper-V hosts.

## Test Files

### ScriptValidation.Tests.ps1
Basic PowerShell syntax validation for all `.ps1` files in the repository. Ensures scripts parse without errors.

### Main-NewProtocol.Tests.ps1
**Unit tests** for `Main-NewProtocol.ps1` covering:

- JSON parsing and envelope validation (7 tests)
- `Read-JobEnvelope` function (via round-trip tests)
- `Write-JobResult` function (tested in all scenarios)
- `ConvertTo-Hashtable` function (4 round-trip tests)
- Input validation (tested in error scenarios)
- Noop-test operation (3 tests)
- JobResult envelope structure (3 tests)
- Operation types recognition (5 tests)
- Error handling (3 tests)
- Windows PowerShell 5.1 compatibility (2 tests)

**Total: 26 tests**

### Main-NewProtocol-Integration.Tests.ps1
**Integration tests** for `Main-NewProtocol.ps1` covering:

- Update operations protocol compliance (3 tests)
- Operation errors without Hyper-V (6 tests)
- Protocol compliance across operations (4 tests)
- Resource spec field extraction (3 tests)
- Complex data types handling (3 tests)

**Total: 19 tests**

## Test Strategy

### Architecture Compliance

All tests conform to the architecture defined in:
- `Docs/TechDoc-Python-PowerShell-Interface.md` - JobRequest/JobResult envelope protocol
- `Docs/TechDoc-VM-Resources-and-Provisioning.md` - Decomposed VM/Disk/NIC resources
- `Docs/System-Architecture-and-Operations.md` - Overall system architecture

### JobRequest Envelope Format
```json
{
  "operation": "vm.create | vm.update | vm.delete | disk.create | disk.update | disk.delete | nic.create | nic.update | nic.delete | noop-test",
  "resource_spec": { ... },
  "correlation_id": "uuid",
  "metadata": { ... }
}
```

### JobResult Envelope Format
```json
{
  "status": "success | error | partial",
  "code": "OPERATION_ERROR",
  "message": "Human-readable message",
  "data": { ... },
  "logs": [ ... ],
  "correlation_id": "uuid"
}
```

### Windows PowerShell 5.1 Compatibility

The tests specifically verify compatibility with Windows PowerShell 5.1 by:

1. **Avoiding `-AsHashtable` parameter**: The `-AsHashtable` parameter for `ConvertFrom-Json` is only available in PowerShell Core 6+. The code uses a custom `ConvertTo-Hashtable` function instead.

2. **Testing the workaround**: Tests verify that the script does not use `-AsHashtable` and instead uses the custom conversion function.

## Round-Trip Testing Approach

### What is Round-Trip Testing?

Round-trip testing validates the entire protocol stack:

1. Create a JobRequest envelope (JSON)
2. Send it to PowerShell script via STDIN
3. Parse the JobResult response (JSON)
4. Validate protocol compliance

### Without Hyper-V Hosts

Tests are designed to run without Hyper-V infrastructure by:

1. **Using stub operations**: Update operations (`vm.update`, `disk.update`, `nic.update`) are stubs that don't require Hyper-V
2. **Validating error handling**: Create/delete operations fail gracefully when Hyper-V is not available
3. **Testing protocol compliance**: Focus on envelope structure, field extraction, and error reporting rather than actual Hyper-V operations
4. **Using noop-test operation**: A special test operation that validates JSON parsing without any infrastructure dependencies

### Testing Matrix

| Operation | Test Coverage | Requires Hyper-V? |
|-----------|--------------|-------------------|
| noop-test | Full round-trip validation | No |
| vm.update | Protocol compliance | No (stub) |
| disk.update | Protocol compliance | No (stub) |
| nic.update | Protocol compliance | No (stub) |
| vm.create | Error handling | No (fails gracefully) |
| vm.delete | Error handling | No (fails gracefully) |
| disk.create | Field extraction | No (fails gracefully) |
| disk.delete | Error handling | No (fails gracefully) |
| nic.create | Field extraction | No (fails gracefully) |
| nic.delete | Error handling | No (fails gracefully) |

## Running Tests Locally

### Prerequisites
- PowerShell Core 7+ (or Windows PowerShell 5.1+)
- Pester testing framework

### Install Pester (if needed)
```powershell
Install-Module -Name Pester -Force -SkipPublisherCheck
```

### Run All Tests
```powershell
# From repository root
Invoke-Pester -Path Powershell/tests
```

### Run Specific Test Suite
```powershell
# Unit tests only
Invoke-Pester -Path Powershell/tests/Main-NewProtocol.Tests.ps1

# Integration tests only
Invoke-Pester -Path Powershell/tests/Main-NewProtocol-Integration.Tests.ps1

# Script validation only
Invoke-Pester -Path Powershell/tests/ScriptValidation.Tests.ps1
```

### Run with Detailed Output
```powershell
Invoke-Pester -Path Powershell/tests -Output Detailed
```

### Run with Coverage (CI mode)
```powershell
Invoke-Pester -Path Powershell/tests -CI
```

## CI/CD Integration

Tests are automatically run in GitHub Actions via `.github/workflows/tests.yml`:

```yaml
powershell:
  name: PowerShell tests
  runs-on: ubuntu-latest
  steps:
    - name: Checkout repository
      uses: actions/checkout@v4
    
    - name: Run Pester tests
      shell: pwsh
      run: |
        Invoke-Pester -Path Powershell/tests -CI
```

The workflow runs on:
- Every push to `main` branch
- Every pull request

## Test Maintenance

### Adding New Tests

1. **For new operations**: Add tests in `Main-NewProtocol-Integration.Tests.ps1`
2. **For new functions**: Add tests in `Main-NewProtocol.Tests.ps1`
3. **For new scripts**: Add dedicated test file following the naming pattern `<ScriptName>.Tests.ps1`

### Test Naming Conventions

- Test files: `*.Tests.ps1`
- Describe blocks: Use full script name (e.g., "Main-NewProtocol.ps1 - Unit Tests")
- It blocks: Use descriptive action (e.g., "parses valid noop-test envelope")

### Helper Functions

All test files include reusable helper functions:

- `Invoke-MainProtocolScript`: Execute script with JSON input
- `New-JobRequest`: Create properly formatted JobRequest envelope
- `ConvertFrom-JobResult`: Parse JobResult from script output

## Troubleshooting

### Test Failures

1. **JSON parsing errors**: Check that the script output is valid JSON
2. **Field validation errors**: Verify JobRequest/JobResult envelope structure
3. **Timeout errors**: Increase test timeout or optimize script execution

### Common Issues

**Issue**: Tests fail with "ConvertFrom-Json: The term is not recognized"
**Solution**: Ensure PowerShell Core 7+ or Windows PowerShell 5.1+ is installed

**Issue**: Tests fail with "-AsHashtable: A parameter cannot be found"
**Solution**: This is the bug we fixed! Ensure you're using the updated `Main-NewProtocol.ps1`

**Issue**: All tests pass locally but fail in CI
**Solution**: Check that CI environment has required PowerShell version and Pester module

## Future Enhancements

Potential improvements to the test suite:

1. **Mock Hyper-V cmdlets**: Create comprehensive mocks to test create/delete operations fully
2. **Property-based testing**: Use generated inputs to test edge cases
3. **Performance testing**: Measure script execution time
4. **Integration with Python tests**: Validate end-to-end protocol with actual Python server
5. **Snapshot testing**: Compare JobResult outputs against baseline snapshots

## References

- [Pester Documentation](https://pester.dev/)
- [PowerShell Testing Best Practices](https://pester.dev/docs/introduction/testing-best-practices)
- [TechDoc-Python-PowerShell-Interface.md](../../Docs/TechDoc-Python-PowerShell-Interface.md)
- [TechDoc-VM-Resources-and-Provisioning.md](../../Docs/TechDoc-VM-Resources-and-Provisioning.md)
