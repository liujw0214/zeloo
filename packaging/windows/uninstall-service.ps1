#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Uninstall Zeloo Windows Service.

.DESCRIPTION
    Stops and removes the Zeloo service from the Windows Service
    Control Manager, unregisters the optional scheduled task, and
    (optionally) wipes persistent data.

.PARAMETER ServiceName
    SCM name to remove. Default: Zeloo

.PARAMETER DataDir
    Data directory that will be deleted when -DeleteData is set.
    Default: C:\ProgramData\Zeloo

.PARAMETER DeleteData
    If specified, deletes $DataDir after service removal.
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "Zeloo",
    [string]$DataDir     = "C:\ProgramData\Zeloo",
    [switch]$DeleteData
)

$ErrorActionPreference = "SilentlyContinue"

# ---------------------------------------------------------------------------
# 1. Stop the service
# ---------------------------------------------------------------------------
Write-Host "[1/5] Stopping service..." -ForegroundColor Cyan
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 3
    }
    Write-Host "    Service status: $(Get-Service -Name $ServiceName).Status"
} else {
    Write-Host "    Service '$ServiceName' is not installed."
}

# ---------------------------------------------------------------------------
# 2. Remove from SCM
# ---------------------------------------------------------------------------
Write-Host "[2/5] Removing service registration..." -ForegroundColor Cyan
Remove-Service -Name $ServiceName -ErrorAction SilentlyContinue
# Some builds of Windows require sc.exe for full cleanup
& sc.exe delete $ServiceName | Out-Null

# ---------------------------------------------------------------------------
# 3. Remove scheduled tasks (best-effort)
# ---------------------------------------------------------------------------
Write-Host "[3/5] Removing scheduled tasks..." -ForegroundColor Cyan
$taskNames = @(
    "Zeloo\DailyBackup",
    "Zeloo\HealthCheck",
    "Zeloo\SelfUpdate"
)
foreach ($t in $taskNames) {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "    Removed task: $t"
}

# ---------------------------------------------------------------------------
# 4. Optionally wipe data
# ---------------------------------------------------------------------------
Write-Host "[4/5] Data directory..." -ForegroundColor Cyan
if (-not $DeleteData) {
    $response = Read-Host "    Delete data files at '$DataDir'? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        $DeleteData = $true
    }
}

if ($DeleteData) {
    if (Test-Path $DataDir) {
        Remove-Item -Recurse -Force $DataDir
        Write-Host "    Removed: $DataDir"
    } else {
        Write-Host "    No data directory found at: $DataDir"
    }
} else {
    Write-Host "    Data preserved at: $DataDir"
}

# ---------------------------------------------------------------------------
# 5. Done
# ---------------------------------------------------------------------------
Write-Host "[5/5] Done." -ForegroundColor Cyan
Write-Host ""
Write-Host "Zeloo service uninstalled." -ForegroundColor Green
Write-Host "Program binaries (C:\Program Files\Zeloo) were left in place." -ForegroundColor Green
Write-Host "Remove them manually if no longer needed." -ForegroundColor Green