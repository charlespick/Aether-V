# Pester tests to ensure PowerShell scripts remain syntactically valid
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = Resolve-Path (Join-Path $scriptRoot '..')
$scripts = Get-ChildItem -Path $repositoryRoot -Filter '*.ps1' -Recurse

Describe 'PowerShell script validation' {
    It 'finds scripts to validate' {
        $scripts | Should -Not -BeNullOrEmpty
    }

    foreach ($script in $scripts) {
        It "parses $($script.Name) without errors" {
            $null = $tokens = $null
            $null = $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $script.FullName,
                [ref]$tokens,
                [ref]$errors
            ) | Out-Null

            $errors | Should -BeNullOrEmpty
        }
    }
}
