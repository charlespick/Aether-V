# Pester tests to prevent regression of PowerShell .Count property bug
# Bug: PowerShell cmdlets return single objects (not arrays) when there's exactly one result
# Single objects don't have a .Count property, causing PropertyNotFoundException
# Solution: Wrap cmdlet results with @() to ensure they're always arrays

$ErrorActionPreference = 'Stop'

Describe "PowerShell .Count Property Bug Prevention" {
    
    Context "Array wrapping patterns" {
        
        It "verifies @() wrapping works correctly with single result" {
            # When cmdlets return a single result, we need @() to ensure consistent Count behavior
            # This simulates what happens with Get-VMNetworkAdapter returning one adapter
            
            # Simulate a single cmdlet result
            function Get-MockResult { 
                return [PSCustomObject]@{ Name = "Adapter1" }
            }
            
            # Without @() wrapping - in some PowerShell versions/contexts this might not have Count
            $singleResult = Get-MockResult
            
            # With @() wrapping - ALWAYS has Count
            $wrappedResult = @(Get-MockResult)
            
            # The wrapped result should have Count = 1
            $wrappedResult.Count | Should -Be 1
            $wrappedResult[0].Name | Should -Be "Adapter1"
        }
        
        It "demonstrates the fix: @() wrapping always provides Count" {
            # Wrapping with @() ensures Count is available
            $singleObject = [PSCustomObject]@{ Name = "Test" }
            $wrapped = @($singleObject)
            
            # Wrapped object has .Count
            $wrapped.Count | Should -Be 1
        }
        
        It "verifies @() wrapping works with zero items" {
            # For cmdlets that return nothing, @() wraps into an empty array
            # Note: @($null) creates an array with one null element (Count = 1)
            # But @() itself or @(cmdlet-returning-nothing) creates an empty array
            $result = @()
            $result.Count | Should -Be 0
        }
        
        It "verifies @() wrapping works with multiple items" {
            $multiple = @(1, 2, 3)
            $wrapped = @($multiple)
            
            # Already an array, @() doesn't double-wrap
            $wrapped.Count | Should -Be 3
        }
    }
    
    Context "Main-NewProtocol.ps1 specific checks" {
        
        BeforeAll {
            $scriptRoot = Split-Path -Parent $PSScriptRoot
            $script:MainScriptPath = Join-Path $scriptRoot 'Main-NewProtocol.ps1'
            
            if (-not (Test-Path $script:MainScriptPath)) {
                throw "Main-NewProtocol.ps1 not found at $script:MainScriptPath"
            }
        }
        
        It "verifies Get-VMNetworkAdapter result is wrapped with @() on line 711" {
            # Read the script content
            $scriptContent = Get-Content $script:MainScriptPath -Raw
            
            # Look for the pattern: Get-VMNetworkAdapter wrapped with @()
            # The fix should be: $existingAdapters = @(Get-VMNetworkAdapter -VM $vm)
            $pattern = '\$existingAdapters\s*=\s*@\(\s*Get-VMNetworkAdapter\s+-VM\s+\$vm\s*\)'
            
            $scriptContent | Should -Match $pattern -Because "Get-VMNetworkAdapter must be wrapped with @() to prevent .Count property error"
        }
        
        It "verifies script does not have bare Get-VMNetworkAdapter assigned to variables used with .Count" {
            # Read the script content
            $scriptContent = Get-Content $script:MainScriptPath -Raw
            
            # Look for problematic pattern: $var = Get-VMNetworkAdapter (without @() wrapping)
            # This regex looks for assignment without @() wrapper
            # Use (?:\r?\n) to handle both Windows (CRLF) and Unix (LF) line endings
            $problematicPattern = '\$\w+\s*=\s*Get-VMNetworkAdapter[^@]*(?:\r?\n)[^\r\n]*\.Count'
            
            # Should NOT match the problematic pattern
            $scriptContent | Should -Not -Match $problematicPattern -Because "All Get-VMNetworkAdapter calls used with .Count must be wrapped with @()"
        }
    }
    
    Context "Code scanning for vulnerable .Count usage patterns" {
        
        BeforeAll {
            # Get all PowerShell scripts
            $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
            $script:AllPowerShellScripts = Get-ChildItem -Path $repoRoot -Filter "*.ps1" -Recurse |
                Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' } |
                Where-Object { $_.FullName -notmatch '[\\/]node_modules[\\/]' }
        }
        
        It "scans all PowerShell scripts for Get-VM* cmdlets that should be wrapped" {
            # This is a comprehensive scan to catch future issues
            $vulnerableCmdlets = @(
                'Get-VMNetworkAdapter',
                'Get-VMHardDiskDrive',
                'Get-VMScsiController'
            )
            
            $issues = @()
            
            foreach ($script in $script:AllPowerShellScripts) {
                $content = Get-Content $script.FullName -Raw
                $lines = Get-Content $script.FullName
                
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    $line = $lines[$i]
                    
                    # Skip comment lines
                    if ($line -match '^\s*#') {
                        continue
                    }
                    
                    # Check if line assigns result of Get-VM* cmdlet to a variable
                    foreach ($cmdlet in $vulnerableCmdlets) {
                        # Escape cmdlet name for safe use in regex
                        $escapedCmdlet = [regex]::Escape($cmdlet)
                        
                        # Pattern: $var = Get-VMSomething (without @() wrapper)
                        if ($line -match ('\$(\w+)\s*=\s*' + $escapedCmdlet + '\s+') -and $line -notmatch ('@\(\s*' + $escapedCmdlet)) {
                            $varName = $matches[1]
                            
                            # Check if this variable is later used with .Count in next ~20 lines
                            $checkLines = $lines[$i..([Math]::Min($i + 20, $lines.Count - 1))]
                            # Filter out comments when checking for .Count usage
                            $escapedVarName = [regex]::Escape($varName)
                            $usesCount = $checkLines | Where-Object { $_ -notmatch '^\s*#' -and $_ -match ('\$' + $escapedVarName + '\.Count') }
                            
                            if ($usesCount) {
                                $issues += @{
                                    File = $script.Name
                                    Line = $i + 1
                                    Issue = "Variable `$$varName from $cmdlet is used with .Count but not wrapped with @()"
                                }
                            }
                        }
                    }
                }
            }
            
            # Report any issues found
            if ($issues.Count -gt 0) {
                $issueReport = $issues | ForEach-Object {
                    "$($_.File):$($_.Line) - $($_.Issue)"
                } | Out-String
                
                $issues.Count | Should -Be 0 -Because "Found vulnerable .Count usage patterns:`n$issueReport"
            }
        }
    }
    
    Context "Documentation of the pattern" {
        
        It "documents the safe pattern for future developers" {
            # This test serves as documentation
            
            # UNSAFE PATTERN (can fail with single result):
            # $myAdapters = Get-VMNetworkAdapter -VM $myVm
            # $myCount = $myAdapters.Count  # Fails if only one adapter
            
            # SAFE PATTERN (always works):
            # $myAdapters = @(Get-VMNetworkAdapter -VM $myVm)
            # $myCount = $myAdapters.Count  # Always works
            
            $true | Should -Be $true -Because "This pattern is documented in the test suite"
        }
    }
}
