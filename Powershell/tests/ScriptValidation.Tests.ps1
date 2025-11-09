# Pester tests to ensure PowerShell scripts remain syntactically valid
$ErrorActionPreference = 'Stop'

$script:scripts = @()

BeforeAll {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $repositoryRoot = Resolve-Path (Join-Path $scriptRoot '..' '..')
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
