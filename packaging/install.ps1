<#
.SYNOPSIS
    Install Zeloo on a Windows host.

.DESCRIPTION
    Creates a per-user Zeloo home directory, materialises an isolated Python
    virtualenv under it, installs the wheel, optionally augments the user PATH
    (current session and persistent), and offers to create a desktop shortcut.

.PARAMETER InstallDir
    Override the Zeloo home directory. Defaults to "$env:USERPROFILE\.zeloo".

.PARAMETER PythonExe
    Override the Python interpreter to use. Defaults to "python".

.PARAMETER NoPath
    Skip persistent PATH augmentation.

.PARAMETER NoShortcut
    Skip desktop shortcut creation.

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File packaging/install.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".zeloo"),
    [string]$PythonExe = "python",
    [switch]$NoPath,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-PythonVersion {
    Write-Section "Checking Python version"
    $versionOutput = & $PythonExe --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python was not found on PATH (looked for '$PythonExe'). Install Python 3.11+ first."
    }
    Write-Host "Found $versionOutput"

    $versionString = ($versionOutput -replace "Python ", "").Trim()
    $major, $minor = $versionString.Split(".")
    if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
        throw "Python 3.11 or newer is required (found $versionString)."
    }
}

function Initialize-ZelooHome {
    param([string]$Path)
    Write-Section "Initialising Zeloo home at $Path"
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    foreach ($sub in @("workspace", "archive", "profile", "memory", "skills", "logs")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Path $sub) | Out-Null
    }
}

function New-ZelooVenv {
    param(
        [string]$Home,
        [string]$Python
    )
    $venv = Join-Path $Home "venv"
    Write-Section "Creating virtualenv at $venv"
    if (-not (Test-Path $venv)) {
        & $Python -m venv $venv
    }
    return $venv
}

function Install-ZelooWheel {
    param([string]$Venv)
    Write-Section "Installing Zeloo into the virtualenv"
    & (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip | Out-Null
    & (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade zeloo
}

function Update-UserPath {
    param(
        [string]$Home,
        [switch]$Skip
    )
    if ($Skip) { return }
    $bin = Join-Path $Home "venv\Scripts"
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($current -notlike "*$bin*") {
        Write-Section "Adding $bin to the user PATH"
        [Environment]::SetEnvironmentVariable(
            "Path",
            "$current;$bin",
            "User"
        )
        $env:Path = "$env:Path;$bin"
    } else {
        Write-Host "$bin is already on the user PATH."
    }
}

function New-DesktopShortcut {
    param([switch]$Skip)
    if ($Skip) { return }
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Zeloo.lnk"
    Write-Section "Creating desktop shortcut at $shortcutPath"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $InstallDir "venv\Scripts\zeloo.exe"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = "shell32.dll,13"
    $shortcut.Description = "Zeloo Resident AI Agent Runtime"
    $shortcut.Save()
}

Write-Section "Zeloo Installer"
Write-Host "InstallDir: $InstallDir"
Write-Host "Python    : $PythonExe"

Test-PythonVersion
Initialize-ZelooHome -Path $InstallDir
$venvPath = New-ZelooVenv -Home $InstallDir -Python $PythonExe
Install-ZelooWheel -Venv $venvPath
Update-UserPath -Home $InstallDir -Skip:$NoPath
New-DesktopShortcut -Skip:$NoShortcut

Write-Section "Install complete"
Write-Host "Run 'zeloo doctor' to verify the install."
Write-Host "Run 'zeloo install' for first-run workspace setup."
