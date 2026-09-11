#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install Zeloo as a Windows Service.

.DESCRIPTION
    Registers Zeloo with the Windows Service Control Manager (SCM),
    configures automatic startup, recovery actions, and starts the
    service. Designed for Windows 10/11 / Server 2019+.

.PARAMETER ServiceName
    Internal SCM name. Default: Zeloo

.PARAMETER InstallDir
    Directory that contains zeloo.exe. Default: C:\Program Files\Zeloo

.PARAMETER DataDir
    Working/data directory. Default: C:\ProgramData\Zeloo
#>
[CmdletBinding()]
param(
    [string]$ServiceName  = "Zeloo",
    [string]$DisplayName  = "Zeloo Agent Runtime",
    [string]$Description  = "Self-hosted, self-evolving resident AI Agent runtime",
    [string]$InstallDir   = "C:\Program Files\Zeloo",
    [string]$DataDir      = "C:\ProgramData\Zeloo"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# 1. Pre-flight checks
# ---------------------------------------------------------------------------
Write-Host "[1/6] Pre-flight checks..." -ForegroundColor Cyan

if (-not (Test-Path "$InstallDir\zeloo.exe")) {
    throw "zeloo.exe not found at $InstallDir. Please install Zeloo first."
}

# Ensure Python environment is reachable (py launcher is preferred on Windows)
try {
    $pyVersion = & py -3 -V 2>$null
    if ($LASTEXITCODE -ne 0) { throw "py launcher missing" }
    Write-Host "    Python detected: $pyVersion"
} catch {
    Write-Warning "Python launcher (py) not found. The service will rely on zeloo.exe shebang."
}

# Ensure data directory exists and is writable
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    Write-Host "    Created data directory: $DataDir"
}

# ---------------------------------------------------------------------------
# 2. Stop / remove any pre-existing service with the same name
# ---------------------------------------------------------------------------
Write-Host "[2/6] Checking for existing service..." -ForegroundColor Cyan
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "    Stopping existing service..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 3. Build the binary path with proper quoting
# ---------------------------------------------------------------------------
$exePath     = Join-Path $InstallDir "zeloo.exe"
$binaryPath  = "`"$exePath`" gateway foreground"

# ---------------------------------------------------------------------------
# 4. Create the service
# ---------------------------------------------------------------------------
Write-Host "[3/6] Registering service with SCM..." -ForegroundColor Cyan
New-Service `
    -Name             $ServiceName `
    -DisplayName      $DisplayName `
    -Description      $Description `
    -BinaryPathName   $binaryPath `
    -WorkingDirectory $DataDir `
    -StartupType      Automatic | Out-Null

# ---------------------------------------------------------------------------
# 5. Configure recovery: restart on first/second/subsequent failure
# ---------------------------------------------------------------------------
Write-Host "[4/6] Configuring failure recovery..." -ForegroundColor Cyan
$sc_cmd = "failure"
$sc_args = @(
    $ServiceName,
    "actions= restart/60000/restart/60000/restart/120000",
    "reset= 86400"
)
& sc.exe @sc_args | Out-Null

# Set service description via sc.exe (more reliable than New-Service on some locales)
& sc.exe description $ServiceName $Description | Out-Null

# ---------------------------------------------------------------------------
# 6. Start the service
# ---------------------------------------------------------------------------
Write-Host "[5/6] Starting service..." -ForegroundColor Cyan
Start-Service -Name $ServiceName
Start-Sleep -Seconds 3

# ---------------------------------------------------------------------------
# 7. Verify
# ---------------------------------------------------------------------------
Write-Host "[6/6] Verification:" -ForegroundColor Cyan
$svc = Get-Service -Name $ServiceName
Write-Host "    Name   : $($svc.Name)"
Write-Host "    Display: $($svc.DisplayName)"
Write-Host "    Status : $($svc.Status)"
Write-Host "    Start  : $($svc.StartType)"

if ($svc.Status -ne "Running") {
    Write-Warning "Service is not running. Inspect Event Viewer (Application log) for details."
    exit 2
}

Write-Host ""
Write-Host "Zeloo service installed and started successfully." -ForegroundColor Green
Write-Host "Logs (Event Viewer): Applications and Services Logs -> Zeloo" -ForegroundColor Green