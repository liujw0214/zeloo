<#
.SYNOPSIS
    Uninstall Zeloo from a Windows host.

.DESCRIPTION
    Removes the per-user Zeloo home directory (after an explicit prompt to keep
    or wipe data), scrubs the user PATH entry, and removes the desktop shortcut.

.PARAMETER InstallDir
    Override the Zeloo home directory. Defaults to "$env:USERPROFILE\.zeloo".

.PARAMETER KeepData
    Skip the data-wipe prompt and keep the data directory intact.

.PARAMETER PurgeData
    Skip the data-wipe prompt and remove the data directory non-interactively.

.PARAMETER NoPath
    Skip PATH scrub.

.PARAMETER NoShortcut
    Skip desktop shortcut removal.

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File packaging/uninstall.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".zeloo"),
    [switch]$KeepData,
    [switch]$PurgeData,
    [switch]$NoPath,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Remove-UserPathEntry {
    param(
        [string]$Home,
        [switch]$Skip
    )
    if ($Skip) { return }
    $bin = Join-Path $Home "venv\Scripts"
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($current -like "*$bin*") {
        Write-Section "Removing $bin from the user PATH"
        $updated = ($current -split ";" | Where-Object { $_ -and $_ -ne $bin }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $updated, "User")
        $env:Path = ($env:Path -split ";" | Where-Object { $_ -and $_ -ne $bin }) -join ";"
    } else {
        Write-Host "$bin was not present on the user PATH."
    }
}

function Remove-DesktopShortcut {
    param([switch]$Skip)
    if ($Skip) { return }
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Zeloo.lnk"
    if (Test-Path $shortcutPath) {
        Write-Section "Removing desktop shortcut $shortcutPath"
        Remove-Item -Force $shortcutPath
    }
}

function Remove-InstallDir {
    param(
        [string]$Path,
        [bool]$KeepData
    )
    if (-not (Test-Path $Path)) {
        Write-Host "Nothing to remove at $Path."
        return
    }

    if ($KeepData) {
        Write-Section "Keeping data directory at $Path"
        return
    }

    $backupDir = Join-Path $env:USERPROFILE ("Zeloo-data-backup-{0:yyyyMMddHHmmss}" -f (Get-Date))
    Write-Section "Backing up data to $backupDir"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    foreach ($sub in @("workspace", "archive", "profile", "memory", "skills", "logs")) {
        $src = Join-Path $Path $sub
        if (Test-Path $src) {
            Copy-Item -Recurse -Force $src (Join-Path $backupDir $sub)
        }
    }

    Write-Section "Removing $Path"
    Remove-Item -Recurse -Force $Path
}

Write-Section "Zeloo Uninstaller"
Write-Host "InstallDir: $InstallDir"

if (-not (Test-Path $InstallDir)) {
    Write-Host "Zeloo does not appear to be installed at $InstallDir."
    Remove-DesktopShortcut -Skip:$NoShortcut
    Remove-UserPathEntry -Home $InstallDir -Skip:$NoPath
    exit 0
}

if (-not $KeepData -and -not $PurgeData) {
    $answer = Read-Host "Remove $InstallDir and all its data? [y/N]"
    $KeepData = -not ($answer -match '^[Yy]')
}

Remove-InstallDir -Path $InstallDir -KeepData:$KeepData
Remove-DesktopShortcut -Skip:$NoShortcut
Remove-UserPathEntry -Home $InstallDir -Skip:$NoPath

Write-Section "Uninstall complete"
