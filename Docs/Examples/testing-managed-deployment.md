# Testing Managed Deployment Mode

This guide provides test scenarios to validate the `deployment_type: managed` feature.

## Prerequisites

- Hyper-V cluster configured and operational
- HLVMM installed on Hyper-V hosts
- Ansible with Windows modules installed
- CredSSP configured for cluster operations
- Test VM image available (e.g., Ubuntu 22.04 LTS)

## Test Scenario 1: First-Time VM Creation (Managed Mode)

### Objective
Verify that a managed deployment creates a VM when it doesn't exist in the cluster.

### Steps

1. Ensure no VM named `test-managed-vm-01` exists in the cluster:
   ```powershell
   Get-ClusterGroup -Name 'test-managed-vm-01' -ErrorAction SilentlyContinue
   # Should return nothing
   ```

2. Run the playbook with managed deployment:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-managed-vm-01" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "vm_clustered=Yes" \
     -e "deployment_type=managed" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

3. Verify the VM was created:
   ```powershell
   Get-ClusterGroup -Name 'test-managed-vm-01'
   Get-VM -Name 'test-managed-vm-01'
   ```

### Expected Results
- ✅ Playbook completes all tasks successfully
- ✅ VM is created and added to cluster
- ✅ VM is provisioned with specified configuration
- ✅ Message: "VM 'test-managed-vm-01' does not exist in cluster. Proceeding with provisioning."

## Test Scenario 2: Idempotency Check (VM Already Exists)

### Objective
Verify that running the playbook again with the same VM name exits early without making changes.

### Steps

1. Verify VM exists from Test Scenario 1:
   ```powershell
   Get-ClusterGroup -Name 'test-managed-vm-01'
   ```

2. Run the same playbook command again:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-managed-vm-01" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "vm_clustered=Yes" \
     -e "deployment_type=managed" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

3. Verify playbook behavior:
   - Check playbook output for early termination
   - Verify VM state unchanged

### Expected Results
- ✅ Playbook exits early with no errors
- ✅ No provisioning tasks are executed
- ✅ VM state remains unchanged
- ✅ Execution time is significantly faster (only pre-tasks run)

## Test Scenario 3: Self-Healing (VM Deletion and Automatic Recreate)

### Objective
Verify that the playbook recreates a VM after it has been removed from the cluster.

### Steps

1. Remove the VM from the cluster and delete it:
   ```powershell
   Remove-ClusterGroup -Name 'test-managed-vm-01' -Force -RemoveResources
   Get-VM -Name 'test-managed-vm-01' | Remove-VM -Force
   ```

2. Run the playbook again:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-managed-vm-01" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "vm_clustered=Yes" \
     -e "deployment_type=managed" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

3. Verify the VM was recreated:
   ```powershell
   Get-ClusterGroup -Name 'test-managed-vm-01'
   Get-VM -Name 'test-managed-vm-01'
   ```

### Expected Results
- ✅ Playbook detects VM is missing
- ✅ VM is recreated and provisioned
- ✅ VM is added to cluster
- ✅ VM is fully functional

## Test Scenario 4: Validation - Managed Without Clustering

### Objective
Verify that managed mode requires `vm_clustered: Yes`.

### Steps

1. Run playbook with managed mode but without vm_clustered:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-managed-vm-02" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "deployment_type=managed" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

### Expected Results
- ✅ Playbook fails with clear error message
- ✅ Error: "deployment_type 'managed' is only compatible with vm_clustered: Yes"
- ✅ No VM is created

## Test Scenario 5: Invalid deployment_type Value

### Objective
Verify that invalid deployment_type values are rejected.

### Steps

1. Run playbook with invalid deployment_type:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-vm" \
     -e "deployment_type=invalid_value" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

### Expected Results
- ✅ Playbook fails with validation error
- ✅ Error: "deployment_type must be either 'provisioned' or 'managed'"
- ✅ No VM is created

## Test Scenario 6: Backward Compatibility (Omit deployment_type)

### Objective
Verify that omitting deployment_type maintains backward compatibility.

### Steps

1. Run playbook without specifying deployment_type:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-backward-compat-vm" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

2. Verify behavior:
   - Check that VM is created
   - Verify no cluster check is performed

### Expected Results
- ✅ Playbook uses default "provisioned" mode
- ✅ VM is created without pre-checks
- ✅ No cluster existence check is performed
- ✅ Traditional HLVMM behavior is maintained

## Test Scenario 7: Provisioned Mode with Clustering

### Objective
Verify that provisioned mode works with clustering (allows recreation).

### Steps

1. Create a VM with provisioned mode and clustering:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-provisioned-cluster-vm" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "vm_clustered=Yes" \
     -e "deployment_type=provisioned" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

2. Run the playbook again with the same VM name

### Expected Results
- ✅ First run: VM is created successfully
- ✅ Second run: Playbook attempts to create VM again (may fail if VM exists)
- ✅ No pre-check is performed
- ✅ Traditional behavior is maintained

## Test Scenario 8: CredSSP Handler Cleanup

### Objective
Verify that CredSSP is properly disabled after managed deployment operations.

### Steps

1. Run a managed deployment:
   ```bash
   ansible-playbook Ansible/Provisioning.yaml \
     -e "hyperv_host=hyperv01.example.com" \
     -e "vm_name=test-credssp-vm" \
     -e "image_name='Ubuntu 22.04 LTS'" \
     -e "gb_ram=4" \
     -e "cpu_cores=2" \
     -e "vm_clustered=Yes" \
     -e "deployment_type=managed" \
     -e "guest_la_uid=testadmin" \
     -e "guest_la_pw=TestPassword123"
   ```

2. Verify CredSSP state after playbook completion:
   ```powershell
   Get-WSManCredSSP
   ```

### Expected Results
- ✅ CredSSP is enabled during cluster operations
- ✅ CredSSP is disabled by handler after completion
- ✅ No security issues from leaving CredSSP enabled

## Automated Test Script

Here's a PowerShell script to run through multiple test scenarios:

```powershell
# automated-deployment-tests.ps1

$TestResults = @()

function Test-ManagedDeployment {
    param($TestName, $VMName, $DeploymentType, $VMClustered)
    
    Write-Host "`n=== Running Test: $TestName ===" -ForegroundColor Cyan
    
    $extraVars = @(
        "hyperv_host=hyperv01.example.com"
        "vm_name=$VMName"
        "image_name='Ubuntu 22.04 LTS'"
        "gb_ram=4"
        "cpu_cores=2"
        "guest_la_uid=testadmin"
        "guest_la_pw=TestPassword123"
    )
    
    if ($DeploymentType) { $extraVars += "deployment_type=$DeploymentType" }
    if ($VMClustered) { $extraVars += "vm_clustered=$VMClustered" }
    
    $extraVarsString = ($extraVars | ForEach-Object { "-e `"$_`"" }) -join " "
    
    $result = ansible-playbook Ansible/Provisioning.yaml $extraVarsString
    
    $global:TestResults += [PSCustomObject]@{
        TestName = $TestName
        VMName = $VMName
        ExitCode = $LASTEXITCODE
        Timestamp = Get-Date
    }
    
    return $LASTEXITCODE
}

# Clean up any existing test VMs
Write-Host "Cleaning up any existing test VMs..." -ForegroundColor Yellow
Get-ClusterGroup | Where-Object { $_.Name -like "test-*-vm*" } | Remove-ClusterGroup -Force -RemoveResources

# Run tests
Test-ManagedDeployment "First-Time Creation (Managed)" "test-managed-vm-01" "managed" "Yes"
Test-ManagedDeployment "Idempotency Check" "test-managed-vm-01" "managed" "Yes"
Test-ManagedDeployment "Backward Compatibility" "test-backward-compat-vm" $null $null
Test-ManagedDeployment "Provisioned Mode" "test-provisioned-vm" "provisioned" "Yes"

# Display results
Write-Host "`n=== Test Results ===" -ForegroundColor Green
$global:TestResults | Format-Table -AutoSize
```

## Cleanup

After testing, clean up test VMs:

```powershell
# Remove test VMs
Get-ClusterGroup | Where-Object { $_.Name -like "test-*-vm*" } | Remove-ClusterGroup -Force -RemoveResources

# Verify cleanup
Get-ClusterGroup | Where-Object { $_.Name -like "test-*-vm*" }
```

## Troubleshooting Test Failures

### CredSSP Authentication Failures
- Verify CredSSP is configured on Ansible controller
- Check `ansible_winrm_transport` is set to `credssp`
- Verify domain credentials have cluster admin rights

### Cluster Operation Timeouts
- Increase `pause` seconds before cluster operations
- Check cluster service health
- Verify network connectivity to cluster nodes

### VM Not Detected After Creation
- Verify VM was added to cluster successfully
- Check cluster group name matches vm_name exactly
- Ensure cluster service is running on all nodes

## Performance Benchmarks

Expected execution times (approximate):

- **First-time creation (managed)**: 3-5 minutes (full provisioning)
- **Idempotency check (managed, VM exists)**: 10-15 seconds (early exit)
- **Provisioned mode**: 3-5 minutes (no pre-check overhead)
- **Cluster check operation**: 5-10 seconds (CredSSP + query)

## Success Criteria

All tests pass if:
- ✅ Test Scenario 1: VM created successfully
- ✅ Test Scenario 2: Playbook exits early, no changes made
- ✅ Test Scenario 3: VM recreated after deletion
- ✅ Test Scenario 4: Validation error for missing vm_clustered
- ✅ Test Scenario 5: Validation error for invalid deployment_type
- ✅ Test Scenario 6: Default behavior maintained
- ✅ Test Scenario 7: Provisioned mode works as expected
- ✅ Test Scenario 8: CredSSP properly cleaned up
