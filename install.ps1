# ============================================================================
# Zeloo Agent Installer for Windows (PowerShell)
# ============================================================================
#
# Hermes Agent parity -- same flow as ``NousResearch/hermes-agent``'s
# ``scripts/install.ps1``:
#
#   1. Suppress IWR progress (PS 5.1 stalls otherwise)
#   2. Bootstrap uv (Astral fast Python manager)
#   3. Provision Python 3.11 via uv (no system Python required)
#   4. Create venv at ``<repo>\.venv``
#   5. ``uv pip install -r requirements.txt``
#   6. Register ``zeloo`` global command (User PATH)
#   7. Stamp ``~/.zeloo/.install_method = git``
#   8. Optionally launch ``zeloo setup`` (interactive wizard)
#
# Usage (canonical one-liner):
#
#   iex (irm https://raw.githubusercontent.com/.../install.ps1)
#
# Or with parameters:
#
#   & ([scriptblock]::Create((irm https://.../install.ps1))) -Branch main -SkipSetup
#
# Parameters
# ----------
#  -Branch         Git branch to clone (default: main)
#  -Commit         Pin to a specific commit SHA (overrides -Branch)
#  -Tag            Pin to a specific tag (e.g. v0.16.0)
#  -ZelooHome      Data directory (default: $env:LOCALAPPDATA\zeloo)
#  -InstallDir     Code location (default: $ZelooHome\zeloo)
#  -SkipSetup      Skip the post-install wizard
#  -SkipDeps       Don't run dep_ensure (for CI)
#  -Ensure <name>  Bootstrap a single external dep (called by dep_ensure.py)
#  -PostInstall    Run the full dep bootstrap (Node / ripgrep / ffmpeg / git)
#  -Json           Emit structured JSON instead of human output
#  -NonInteractive Fail instead of prompting
#
# ============================================================================

param(
    [string]$Branch = "main",
    [string]$Commit = "",
    [string]$Tag = "",
    [string]$ZelooHome,
    [string]$InstallDir,
    [switch]$SkipSetup,
    [switch]$SkipDeps,
    [string]$Ensure = "",
    [switch]$PostInstall,
    [switch]$Json,
    [switch]$NonInteractive
)

# Apply defaults (avoids the PS 5.1 parser bug where
# nested "$(if ... { "..." })" inside param() breaks parsing).
if (-not $ZelooHome) {
    if ($env:ZELOO_HOME) {
        $ZelooHome = $env:ZELOO_HOME
    } else {
        $ZelooHome = Join-Path $env:LOCALAPPDATA "zeloo"
    }
}
if (-not $InstallDir) {
    $InstallDir = Join-Path $ZelooHome "zeloo"
}

$ErrorActionPreference = "Continue"

# -- Suppress IWR progress bar (PS 5.1 10-100x speedup) -------------
$ProgressPreference = "SilentlyContinue"

# -- Helpers --------------------------------------------------------
function Write-Stage {
    param([string]$Message)
    if (-not $Json) {
        Write-Host ""
        Write-Host "==> $Message" -ForegroundColor Cyan
    }
}

function Write-Step {
    param([string]$Message)
    if (-not $Json) {
        Write-Host "    $Message" -ForegroundColor Gray
    }
}

function Write-Ok {
    param([string]$Message)
    if (-not $Json) {
        Write-Host "    [OK] $Message" -ForegroundColor Green
    }
}

function Write-Warn {
    param([string]$Message)
    if (-not $Json) {
        Write-Host "    [WARN] $Message" -ForegroundColor Yellow
    }
}

function Write-Fail {
    param([string]$Message)
    if (-not $Json) {
        Write-Host "    [FAIL] $Message" -ForegroundColor Red
    }
    if ($Json) {
        Write-Host "{`"ok`": false, `"error`": `"$Message`"}"
    }
    throw "INSTALL FAILED: $Message"
}

function Resolve-RepoRef {
    if ($Commit) { return @{ kind = "commit"; value = $Commit } }
    if ($Tag) { return @{ kind = "tag"; value = $Tag } }
    return @{ kind = "branch"; value = $Branch }
}

# -- Stage dispatch (mirrors install.ps1 in Hermes Agent) -----------
# ``-Ensure <dep>`` and ``-PostInstall`` are entry points called by
# ``zeloo_cli/dep_ensure.py``. The default invocation (no flag) is
# the full git-clone install that end users hit via the curl one-liner.

if ($Ensure) {
    # Strip BOM from payload (hermes-agent #28347)
    $Ensure = $Ensure.Trim()
    Invoke-EnsureMode -DepName $Ensure
    exit 0
}
if ($PostInstall) {
    Invoke-PostInstallMode
    exit 0
}

# -- Default: full installer runs after all functions are defined
# (PowerShell requires function definitions before call sites).

# ----------------------------------------------------------------------
function Invoke-EnsureMode {
    param([string]$DepName)

    # Comma-separated dep list (e.g. "ripgrep,ffmpeg")
    $deps = $DepName -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    foreach ($dep in $deps) {
        switch ($dep) {
            "ripgrep" { Install-RipGrep }
            "ffmpeg"  { Install-FFmpeg }
            "node"    { Install-Node }
            "git"     { Install-PortableGit }
            "uv"      { Install-Uv }
            default   { Write-Warn "Unknown dep '$dep' -- skipping" }
        }
    }
}

function Invoke-PostInstallMode {
    Write-Stage "Running full post-install dependency bootstrap"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Install-RipGrep -UseWinget
        Install-FFmpeg  -UseWinget
        Install-Node    -UseWinget
    } else {
        Write-Warn "winget not available -- falling back to portable installs"
        Install-RipGrep
        Install-FFmpeg
        Install-Node
    }
    Install-PortableGit
    Write-Ok "Post-install complete"
}

# ----------------------------------------------------------------------
function Install-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Ok "uv already installed"
        return
    }
    Write-Stage "Installing uv (Astral Python manager)"
    $uvDir = "$env:USERPROFILE\.local\bin"
    New-Item -ItemType Directory -Path $uvDir -Force | Out-Null
    $uvZip = "$env:TEMP\uv.zip"
    try {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" `
            -OutFile $uvZip
        Expand-Archive -Path $uvZip -DestinationPath $uvDir -Force
        Write-Ok "uv installed at $uvDir\uv.exe"
    } finally {
        Remove-Item -Path $uvZip -ErrorAction SilentlyContinue
    }
    # Ensure $uvDir is on PATH for this session
    if ($env:PATH -notlike "*$uvDir*") {
        $env:PATH = "$uvDir;$env:PATH"
    }
}

function Install-PortableGit {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "git already installed"
        return
    }
    Write-Stage "Installing PortableGit"
    $gitDir = "$ZelooHome\git"
    New-Item -ItemType Directory -Path $gitDir -Force | Out-Null
    $gitZip = "$env:TEMP\PortableGit.zip"
    try {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "https://github.com/git-for-windows/git/releases/download/v2.47.0.windows.2/PortableGit-2.47.0-64-bit.7z.exe" `
            -OutFile $gitZip
        # The .7z.exe self-extractor is interactive; for a fully silent
        # install we'd want 7-Zip installed. Fall back to winget if
        # available, otherwise surface a clear hint.
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements
        } else {
            Write-Warn "Please install Git for Windows manually: https://git-scm.com/download/win"
        }
    } finally {
        Remove-Item -Path $gitZip -ErrorAction SilentlyContinue
    }
}

function Install-RipGrep {
    param([switch]$UseWinget)
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        Write-Ok "ripgrep already installed"
        return
    }
    Write-Stage "Installing ripgrep"
    if ($UseWinget -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        winget install --id BurntSushi.ripgrep --silent --accept-package-agreements --accept-source-agreements
    } else {
        $rgZip = "$env:TEMP\ripgrep.zip"
        try {
            Invoke-WebRequest -UseBasicParsing `
                -Uri "https://github.com/BurntSushi/ripgrep/releases/download/14.1.0/ripgrep-14.1.0-x86_64-pc-windows-msvc.zip" `
                -OutFile $rgZip
            Expand-Archive -Path $rgZip -DestinationPath "$env:LOCALAPPDATA\zeloo\rg" -Force
            Write-Ok "ripgrep installed at $env:LOCALAPPDATA\zeloo\rg"
        } finally {
            Remove-Item -Path $rgZip -ErrorAction SilentlyContinue
        }
    }
}

function Install-FFmpeg {
    param([switch]$UseWinget)
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        Write-Ok "ffmpeg already installed"
        return
    }
    Write-Stage "Installing ffmpeg"
    if ($UseWinget -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        winget install --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Warn "Please install ffmpeg manually: https://www.gyan.dev/ffmpeg/builds/"
    }
}

function Install-Node {
    param([switch]$UseWinget)
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Write-Ok "node already installed"
        return
    }
    Write-Stage "Installing Node.js LTS"
    if ($UseWinget -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Warn "Please install Node.js manually: https://nodejs.org/"
    }
}

# ----------------------------------------------------------------------
function Invoke-Main {
    Write-Stage "Zeloo Agent Installer (Windows / PowerShell)"
    Write-Step "Branch / Tag / Commit: $(Resolve-RepoRef | ConvertTo-Json -Compress)"
    Write-Step "Install dir:  $InstallDir"
    Write-Step "Data dir:     $ZelooHome"

    # 1. Ensure git is available (we need it to clone the repo or
    #    detect that we're running inside one already).
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Install-PortableGit
    }

    # 2. Bootstrap uv
    Install-Uv

    # 3. Provision Python 3.11 via uv
    if (-not (Test-Path "$InstallDir\.venv")) {
        Write-Stage "Provisioning Python 3.11 via uv"
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if (-not $uv) {
            Write-Fail "uv not found on PATH after Install-Uv"
        }
        & uv python install 3.11 2>$null | Out-Null
    }

    # 4. If we're not already inside a Zeloo checkout, clone it.
    if (-not (Test-Path "$InstallDir\cli.py")) {
        Write-Stage "Cloning Zeloo repository"
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        $repo = "https://github.com/your-org/zeloo.git"  # TODO: replace with real repo
        git clone --depth 1 --branch $Branch $repo $InstallDir
        if ($Commit) {
            git -C $InstallDir checkout $Commit
        }
    } else {
        Write-Ok "Existing checkout detected at $InstallDir"
    }

    # 5. Create venv + install requirements
    $venvPython = "$InstallDir\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Stage "Creating virtual environment at $InstallDir\.venv"
        & uv venv "$InstallDir\.venv" --python 3.11
    }
    Write-Stage "Installing Python dependencies"
    & uv pip install --python $venvPython -r "$InstallDir\requirements.txt"

    # 6. Install the package itself in editable mode so `zeloo` resolves
    #    without sys.path tricks.
    & uv pip install --python $venvPython -e "$InstallDir"

    # 7. Register the global `zeloo` command on User PATH
    $zelooExe = "$InstallDir\.venv\Scripts\zeloo.exe"
    if (Test-Path $zelooExe) {
        Write-Stage "Registering global 'zeloo' command"
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($userPath -notlike "*$InstallDir\.venv\Scripts*") {
            [Environment]::SetEnvironmentVariable(
                "Path",
                "$InstallDir\.venv\Scripts;$userPath",
                "User"
            )
            $env:Path = "$InstallDir\.venv\Scripts;$env:Path"
            Write-Ok "'zeloo' registered on User PATH"
        } else {
            Write-Ok "'zeloo' already on User PATH"
        }
    } else {
        Write-Warn "'zeloo.exe' not built yet -- using 'python -m zeloo_cli.click_app'"
    }

    # 8. Stamp the install method so dep_ensure() can find this script
    #    when the user later runs `zeloo doctor`.
    Write-Stage "Stamping install method"
    $refKind = if ($Commit) { 'commit' } elseif ($Tag) { 'tag' } else { 'branch' }
    $refValue = if ($Commit) { $Commit } elseif ($Tag) { $Tag } else { $Branch }
    # Delegate the JSON write to a small Python helper so we don't have
    # to embed a Python here-string in PowerShell (indentation rules
    # are painful across editors).
    $stampScript = Join-Path $InstallDir "scripts\stamp_install_method.py"
    if (Test-Path $stampScript) {
        & $venvPython $stampScript $ZelooHome $InstallDir $refKind $refValue
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Failed to stamp install_method (continuing anyway)"
        }
    } else {
        Write-Warn "stamp helper missing at $stampScript -- skipping"
    }

    # 9. Provision ~/.zeloo/ data directory (matches the Python side).
    Write-Stage "Creating Zeloo data directory at $ZelooHome"
    foreach ($sub in @('profile', 'memory', 'skills', 'archive')) {
        New-Item -ItemType Directory -Path "$ZelooHome\$sub" -Force | Out-Null
    }

    # 10. Optionally launch the setup wizard.
    if (-not $SkipSetup) {
        Write-Stage "Launching Zeloo setup wizard"
        & $venvPython "$InstallDir\cli.py" setup
    }

    Write-Stage "Installation complete!"
    $a = "Open a new terminal and run:  zeloo chat -q 'hello'"
    $b = "Verify with:                   zeloo doctor"
    $c = "Re-run the wizard later:       zeloo setup"
    Write-Step $a
    Write-Step $b
    Write-Step $c
}

# ----------------------------------------------------------------------
# Entry point -- invoke Invoke-Main() when we actually have nothing else
# to do. ``-Ensure`` and ``-PostInstall`` already returned above.
# (Mirrors Hermes Agent's install.ps1 dispatcher pattern.)
# ----------------------------------------------------------------------
Invoke-Main
