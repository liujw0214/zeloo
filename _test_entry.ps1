# Stub: inject only the functions needed for -Ensure testing
$ZelooHome = "C:\Users\38324\AppData\Local\zeloo"
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

function Write-Warn {
    param([string]$Message)
    Write-Host "    [WARN] $Message"
}

function Install-RipGrep {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        Write-Host "    [OK] ripgrep already installed"
        return
    }
    Write-Host "    Installing ripgrep..."
}

$Ensure = "ripgrep"
Write-Host "Testing -Ensure entry point..."
if ($Ensure) {
    $Ensure = $Ensure.Trim()
    Invoke-EnsureMode -DepName $Ensure
    Write-Host "Exit 0"
    exit 0
}

function Invoke-EnsureMode {
    param([string]$DepName)
    Write-Host "Invoke-EnsureMode called with: $DepName"
    $deps = $DepName -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    foreach ($dep in $deps) {
        switch ($dep) {
            "ripgrep" { Install-RipGrep }
            default   { Write-Warn "Unknown dep '$dep' -- skipping" }
        }
    }
}
