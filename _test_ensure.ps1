$ErrorActionPreference = "SilentlyContinue"
$Ensure = "ripgrep"
$Ensure = $Ensure.Trim()
Write-Host "Calling Invoke-EnsureMode..."
Invoke-EnsureMode -DepName $Ensure
Write-Host "Done"
exit 0

function Invoke-EnsureMode {
    param([string]$DepName)
    Write-Host "Ensure: $DepName"
}
