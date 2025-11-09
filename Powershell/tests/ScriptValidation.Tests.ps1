# Pester tests to ensure PowerShell scripts remain syntactically valid
$ErrorActionPreference = 'Stop'

$script:scripts = @()

BeforeAll {
    $repositoryRoot = $null

    $scriptRootCandidates = @(
        $PSScriptRoot,
        $(if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }),
        $(if ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { $null })
    ) | Where-Object { $_ }

    foreach ($candidate in $scriptRootCandidates) {
        try {
            $resolvedCandidate = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).ProviderPath
            $parent = Split-Path -Parent $resolvedCandidate
            $repositoryCandidate = Split-Path -Parent $parent
            $repositoryRoot = (Resolve-Path -LiteralPath $repositoryCandidate -ErrorAction Stop).ProviderPath
            break
        } catch {
            continue
        }
    }

    if (-not $repositoryRoot -and $env:GITHUB_WORKSPACE) {
        try {
            $repositoryRoot = (Resolve-Path -LiteralPath $env:GITHUB_WORKSPACE -ErrorAction Stop).ProviderPath
        } catch {
            # fall through to final failure
        }
    }

    if (-not $repositoryRoot) {
        try {
            $repositoryRoot = (Resolve-Path -LiteralPath (Get-Location).ProviderPath -ErrorAction Stop).ProviderPath
        } catch {
            throw 'Unable to determine repository root for script validation.'
        }
    }

    $script:scripts = Get-ChildItem -Path $repositoryRoot -Filter '*.ps1' -Recurse -File
}

Describe 'PowerShell script validation' {
    It 'finds scripts to validate' {
        $script:scripts | Should -Not -BeNullOrEmpty
    }

    It 'parses scripts without errors' -ForEach $script:scripts {
        $null = $tokens = $null
        $null = $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $_.FullName,
            [ref]$tokens,
            [ref]$errors
        ) | Out-Null

        $errors | Should -BeNullOrEmpty
    }
}
