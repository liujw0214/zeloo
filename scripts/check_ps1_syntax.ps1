$path = (Resolve-Path 'install.ps1').Path
$errors = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors -and $errors.Count -gt 0) {
    Write-Host "install.ps1: SYNTAX ERRORS"
    foreach ($err in $errors) {
        Write-Host "  - $($err.Extent.StartLineNumber):$($err.Extent.StartColumnNumber) - $($err.Message)"
    }
    exit 1
} else {
    Write-Host "install.ps1: syntax OK"
}
