$ErrorActionPreference = 'Continue'
$files = @(
    'main.py',
    'hermes_bootstrap.py',
    'hermes_startup_watchdog.py',
    'zeloo_cli\gateway.py',
    'gateway\status.py',
    'gateway\run.py'
)
$allOk = $true
foreach ($f in $files) {
    $result = & python -c "import ast; ast.parse(open('$f').read()); print('OK: $f')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: $f"
        Write-Host $result
        $allOk = $false
    } else {
        Write-Host $result
    }
}
if ($allOk) { Write-Host "ALL SYNTAX OK" }
