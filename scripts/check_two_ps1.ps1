# Test: parse install.ps1 with ONLY the script structure (functions) and see if it works
$src = Join-Path $PSScriptRoot "..\install.ps1"
$src = (Resolve-Path $src).Path
$content = Get-Content $src -Raw

# Try parsing JUST the function definitions portion (lines 1-260)
$lines = $content -split "`r?`n"
$truncated = ($lines[0..259] -join "`n") + "`n# END"
$tmp = [System.IO.Path]::GetTempFileName() + ".ps1"
Set-Content -Path $tmp -Value $truncated -Encoding UTF8

$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($tmp, [ref]$null, [ref]$errors)
Remove-Item $tmp -Force

Write-Host ("Errors in first 260 lines: {0}" -f $errors.Count)
foreach ($e in $errors) {
    $lineText = (Get-Content $src)[$e.Extent.StartLineNumber - 1]
    Write-Host ("L{0}:C{1} - {2}" -f $e.Extent.StartLineNumber, $e.Extent.StartColumnNumber, $e.Message)
    Write-Host ("    > {0}" -f $lineText)
}
