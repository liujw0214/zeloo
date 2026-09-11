$ErrorActionPreference = "SilentlyContinue"
$t = $null; $e = $null
[System.Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot\install.ps1", [ref]$t, [ref]$e)
if ($e) {
    Write-Host "Errors: $($e.Count)"
    $e | ForEach-Object { Write-Host "  L$($_.Extent.StartLineNumber) $($_.Message)" }
} else {
    Write-Host "0 parse errors"
}
