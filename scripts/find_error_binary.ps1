# Binary-search the failing line in install.ps1
$src = Join-Path $PSScriptRoot "..\install.ps1"
$src = (Resolve-Path $src).Path
$content = Get-Content $src -Raw
$lines = $content -split "`r?`n"

$lo = 0
$hi = $lines.Count
$badLine = $hi
while ($lo -lt $hi) {
    $mid = [int][Math]::Floor(($lo + $hi) / 2)
    $truncated = ($lines[0..($mid - 1)] -join "`n") + "`n# END"
    $tmp = [System.IO.Path]::GetTempFileName() + ".ps1"
    Set-Content -Path $tmp -Value $truncated -Encoding UTF8
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($tmp, [ref]$null, [ref]$errors)
    Remove-Item $tmp -Force
    if ($errors -and $errors.Count -gt 0) {
        $hi = $mid
        $badLine = $mid
    } else {
        $lo = $mid + 1
    }
}
Write-Host ("Earliest failing line: {0}" -f $badLine)
for ($i = [Math]::Max(0, $badLine - 3); $i -lt [Math]::Min($lines.Count, $badLine + 3); $i++) {
    Write-Host ("  {0,4}: {1}" -f ($i + 1), $lines[$i])
}
