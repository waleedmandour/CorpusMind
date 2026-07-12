# =========================================================================
# CorpusMind - Windows one-shot build + reinstall script
# =========================================================================
#
# Builds BOTH .exe (NSIS) and .msi installers, uninstalls any previous
# version, and installs the new build for the current user.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build-corpusmind-windows.ps1
#
# Flags:
#   -SkipUninstall   - don't uninstall the previous version first
#   -SkipInstall     - build only, don't install the result
#
# =========================================================================

param(
    [string]$RepoRoot = (Get-Location).Path,
    [switch]$SkipUninstall = $false,
    [switch]$SkipInstall = $false
)

$ErrorActionPreference = "Stop"

# --- helpers ---
function Log($msg)  { Write-Host "[build] $msg" -ForegroundColor Cyan }
function OkMsg($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function WarnMsg($msg) { Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function DieMsg($msg)  { Write-Host "  FAIL  $msg" -ForegroundColor Red; exit 1 }

$UserName = $env:USERNAME
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\CorpusMind"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\CorpusMind"

Log "CorpusMind v0.1.0 - Windows build + reinstall"
Log "Repo root:  $RepoRoot"
Log "User:       $UserName"
Log "Install to: $InstallDir"
Write-Host ""

# --- 0. Prerequisites ---
Log "checking prerequisites..."

# Python - prefer py -3.12 (Windows launcher), then python, then python3
# CRITICAL: the engine requires Python 3.12. Python 3.13+ may lack wheels
# for scientific packages (spaCy, CAMeL Tools, etc.)
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    # Try py -3.12 first (most reliable on Windows with multiple Python installs)
    try {
        $py312Ver = & py -3.12 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $python = "py -3.12"
            OkMsg "Using py -3.12 (Windows launcher)"
        }
    } catch { }
}
if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $python = "python"
}
if (-not $python -and (Get-Command python3 -ErrorAction SilentlyContinue)) {
    $python = "python3"
}
if (-not $python) { DieMsg "Python not found. Install Python 3.12 from https://python.org and re-run." }
$pyVer = Invoke-Expression "$python --version" 2>&1
OkMsg "Python: $pyVer"
$pyVerNum = ($pyVer -replace "Python ", "")
try {
    $pyVersion = [version]$pyVerNum
    if ($pyVersion -ge [version]"3.13") {
        WarnMsg "Python $pyVerNum detected - some packages may not have wheels yet."
        WarnMsg "Install Python 3.12 from https://python.org and re-run."
    }
} catch { }

# Node
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    DieMsg "Node.js not found. Install Node 20 from https://nodejs.org and re-run."
}
OkMsg "Node: $(node --version)"

# Rust
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    WarnMsg "Rust not found. Installing via rustup..."
    $rustupInit = Join-Path $env:TEMP "rustup-init.exe"
    Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupInit
    & $rustupInit -y
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    $env:Path += ";$cargoBin"
    $cargoEnv = Join-Path $env:USERPROFILE ".cargo\env"
    if (Test-Path $cargoEnv) { . $cargoEnv }
}
OkMsg "Rust: $(rustc --version)"

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    DieMsg "Git not found. Install from https://git-scm.com and re-run."
}
OkMsg "Git: $(git --version)"

# --- 0.5. Pull latest code from GitHub ---
Log "pulling latest code from GitHub..."
Push-Location $RepoRoot
try {
    git fetch origin
    $localHash = git rev-parse HEAD
    $remoteHash = git rev-parse origin/main
    if ($localHash -ne $remoteHash) {
        WarnMsg "local code is behind remote - pulling latest..."
        git stash 2>$null
        git pull origin main
        if ($LASTEXITCODE -ne 0) {
            DieMsg "git pull failed. Run 'git pull origin main' manually and resolve conflicts."
        }
        OkMsg "code updated to latest"
    } else {
        OkMsg "code is already up to date"
    }
} catch {
    WarnMsg "could not pull from GitHub (non-fatal) - building with local code"
}
Pop-Location
Write-Host ""

# Tauri CLI
if (-not (Get-Command cargo-tauri -ErrorAction SilentlyContinue)) {
    WarnMsg "Tauri CLI not found. Installing (this takes ~3 minutes)..."
    cargo install tauri-cli --version "^2.0" --locked
}
OkMsg "Tauri CLI: $(cargo tauri --version 2>&1 | Select-Object -First 1)"
Write-Host ""

# --- 1. Uninstall any previous version ---
if (-not $SkipUninstall) {
    Log "removing any previously-installed CorpusMind..."

    $nsisUninstaller = Join-Path $InstallDir "corpusmind-desktop-uninstaller.exe"
    if (Test-Path $nsisUninstaller) {
        WarnMsg "found NSIS install - running uninstaller silently..."
        try {
            Start-Process -FilePath $nsisUninstaller -ArgumentList "/S" -Wait -NoNewWindow
            OkMsg "NSIS uninstalled"
        } catch {
            WarnMsg "NSIS uninstaller failed: $_"
        }
    }

    try {
        $msiProduct = Get-CimInstance Win32_Product -Filter "Name LIKE '%CorpusMind%'" -ErrorAction SilentlyContinue
        if ($msiProduct) {
            WarnMsg "found MSI install: $($msiProduct.Name) - uninstalling..."
            try {
                $msiProduct | Invoke-CimMethod -MethodName Uninstall | Out-Null
                OkMsg "MSI uninstalled"
            } catch {
                WarnMsg "MSI uninstall failed: $_"
            }
        }
    } catch { }

    foreach ($p in @($InstallDir, $StartMenuDir)) {
        if (Test-Path $p) {
            WarnMsg "removing leftover: $p"
            Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
        }
    }

    $desktopShortcut = Join-Path $env:USERPROFILE "Desktop\CorpusMind.lnk"
    $startShortcut = Join-Path $StartMenuDir "CorpusMind.lnk"
    foreach ($s in @($desktopShortcut, $startShortcut)) {
        if (Test-Path $s) { Remove-Item -Force $s -ErrorAction SilentlyContinue }
    }

    Start-Sleep -Seconds 2
    OkMsg "previous version removed"
    Write-Host ""
}

# --- 2. Engine venv + deps ---
Log "setting up Python engine venv..."
$EngineDir = Join-Path $RepoRoot "engine"
$venvPath = Join-Path $EngineDir ".venv"
if (-not (Test-Path $venvPath)) {
    # Handle "py -3.12" (split into exe + arg) vs "python" (single exe)
    $pyParts = $python -split ' '
    if ($pyParts.Count -gt 1) {
        & $pyParts[0] $pyParts[1..($pyParts.Count-1)] -m venv $venvPath
    } else {
        & $python -m venv $venvPath
    }
}
$Pip = Join-Path $venvPath "Scripts\pip.exe"
$PyExe = Join-Path $venvPath "Scripts\python.exe"
& $PyExe -m pip install --upgrade pip wheel --quiet
& $PyExe -m pip install pyinstaller python-multipart cryptography --quiet
# Install CORE engine deps only - NOT [dev,vision].
# [dev] pulls in pytest/ruff/mypy (not needed in production).
# [vision] pulls in opencv-python (~60MB) which makes PyInstaller extremely slow.
& $PyExe -m pip install -e "$EngineDir" --quiet
& $PyExe -m pip install pillow --quiet
OkMsg "engine deps installed"

Log "downloading spaCy English model..."
# Note: spaCy download writes progress to stderr. We use 2>&1 to merge
# it into stdout so PowerShell does not treat it as a fatal error.
# This is non-fatal - the build can proceed without the model.
try {
    $spacyOutput = & $PyExe -m spacy download en_core_web_sm 2>&1
    $spacyExit = $LASTEXITCODE
    if ($spacyExit -eq 0) {
        OkMsg "spaCy model ready"
    } else {
        WarnMsg "spaCy model download failed (exit $spacyExit) - non-fatal"
        WarnMsg "the engine will not ingest text until you run:"
        WarnMsg "  $PyExe -m spacy download en_core_web_sm"
    }
} catch {
    WarnMsg "spaCy model download failed - non-fatal"
    WarnMsg "install it later with: $PyExe -m spacy download en_core_web_sm"
}
Write-Host ""

# --- 3. Build engine sidecar (PyInstaller) ---
Log "building engine sidecar (PyInstaller)..."
Push-Location $EngineDir
& $PyExe -m PyInstaller corpusmind-engine.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Pop-Location; DieMsg "PyInstaller build failed" }
Pop-Location

$sidecarSrcDir = Join-Path $EngineDir "dist\corpusmind-engine"
$sidecarSrc = Join-Path $sidecarSrcDir "corpusmind-engine.exe"
if (-not (Test-Path $sidecarSrc)) { DieMsg "sidecar not found at $sidecarSrc (onedir output expected)" }
$sidecarSize = [math]::Round((Get-Item $sidecarSrc).Length / 1MB, 1)
OkMsg "sidecar built: $sidecarSrc ($sidecarSize MB)"
Write-Host ""

# --- 4. Stage sidecar for Tauri ---
Log "staging sidecar for Tauri..."
$BinariesDir = Join-Path $RepoRoot "desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
$sidecarDest = Join-Path $BinariesDir "corpusmind-engine"
# Copy entire onedir directory (exe + _internal/ deps)
Copy-Item -Force $sidecarSrcDir $sidecarDest -Recurse
OkMsg "staged: $sidecarDest (onedir)"
Write-Host ""

# --- 5. Build web PWA ---
Log "building web PWA..."
$WebDir = Join-Path $RepoRoot "web"
Push-Location $WebDir
npm install --silent
if ($LASTEXITCODE -ne 0) { Pop-Location; DieMsg "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; DieMsg "PWA build failed" }
Pop-Location
$distIndex = Join-Path $WebDir "dist\index.html"
if (-not (Test-Path $distIndex)) { DieMsg "PWA build failed - missing dist\index.html" }
OkMsg "PWA built to web\dist\"
Write-Host ""

# --- 6. Build Tauri app (produces BOTH .exe and .msi) ---
Log "building Tauri desktop bundle (NSIS .exe + MSI .msi)..."
Log "  this takes 5-15 minutes on first run..."
$TauriDir = Join-Path $RepoRoot "desktop\src-tauri"
Push-Location $TauriDir
cargo tauri build
$tauriExitCode = $LASTEXITCODE
Pop-Location

if ($tauriExitCode -ne 0) {
    Write-Host ""
    Write-Host "  ====================================================================" -ForegroundColor Red
    Write-Host "  cargo tauri build FAILED (exit code $tauriExitCode)" -ForegroundColor Red
    Write-Host "  ====================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Common causes:" -ForegroundColor Yellow
    Write-Host "    1. Missing MSVC Build Tools - install with:" -ForegroundColor White
    Write-Host "       winget install Microsoft.VisualStudio.2022.BuildTools" -ForegroundColor Gray
    Write-Host "       --override '--passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    2. Missing WebView2 Runtime - install with:" -ForegroundColor White
    Write-Host "       winget install Microsoft.EdgeWebView2Runtime" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    3. Missing WiX Toolset (for MSI)" -ForegroundColor White
    Write-Host "       Tauri installs this automatically but sometimes fails." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Check the full error output above for the specific failure." -ForegroundColor Yellow
    DieMsg "cargo tauri build failed"
}

$BundleDir = Join-Path $TauriDir "target\release\bundle"
$nsisExe = Get-ChildItem (Join-Path $BundleDir "nsis\*.exe") -ErrorAction SilentlyContinue | Select-Object -First 1
$msiFile = Get-ChildItem (Join-Path $BundleDir "msi\*.msi") -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $nsisExe) { DieMsg "NSIS .exe not found" }
if (-not $msiFile) { DieMsg "MSI not found" }

$nsisSize = [math]::Round($nsisExe.Length / 1MB, 1)
$msiSize = [math]::Round($msiFile.Length / 1MB, 1)
OkMsg "NSIS installer: $($nsisExe.FullName) ($nsisSize MB)"
OkMsg "MSI installer:  $($msiFile.FullName) ($msiSize MB)"
Write-Host ""

# --- 6.5. Verify the sidecar was embedded in the installer ---
Log "verifying sidecar was embedded in installer..."
$stagedSidecar = Join-Path $BinariesDir "corpusmind-engine\corpusmind-engine.exe"
if (Test-Path $stagedSidecar) {
    $sidecarSize = [math]::Round((Get-Item $stagedSidecar).Length / 1MB, 1)
    OkMsg "sidecar staged: $stagedSidecar ($sidecarSize MB)"
    if ($sidecarSize -lt 10) {
        WarnMsg "sidecar is suspiciously small ($sidecarSize MB) - PyInstaller may have failed."
        WarnMsg "the engine will NOT work. Check the PyInstaller output above for errors."
    }
} else {
    WarnMsg "sidecar NOT staged at $stagedSidecar"
    WarnMsg "the installer will NOT include the engine - it will be offline after install."
}
if ($nsisSize -lt 50) {
    WarnMsg "NSIS installer is only $nsisSize MB - the sidecar was probably NOT embedded."
    WarnMsg "a working installer should be 50-200 MB."
}
Write-Host ""

# --- 7. Install the NSIS .exe silently for the current user ---
if (-not $SkipInstall) {
    Log "installing NSIS build for $UserName..."
    $installArgs = @("/S", "/D=$InstallDir")
    Start-Process -FilePath $nsisExe.FullName -ArgumentList $installArgs -Wait -NoNewWindow
    Start-Sleep -Seconds 3

    $appExe = Join-Path $InstallDir "corpusmind-desktop.exe"
    if (Test-Path $appExe) {
        OkMsg "installed to $InstallDir"

        New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $StartMenuDir "CorpusMind.lnk"))
        $shortcut.TargetPath = $appExe
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.IconLocation = "$appExe,0"
        $shortcut.Save()

        # Create desktop shortcut - use the actual Desktop path
        # (handles OneDrive redirection and custom Desktop locations)
        try {
            $desktopPath = [Environment]::GetFolderPath("Desktop")
            if (-not $desktopPath) { $desktopPath = Join-Path $env:USERPROFILE "Desktop" }
            $desktopShortcut = Join-Path $desktopPath "CorpusMind.lnk"
            $desktopShortcutObj = $shell.CreateShortcut($desktopShortcut)
            $desktopShortcutObj.TargetPath = $appExe
            $desktopShortcutObj.WorkingDirectory = $InstallDir
            $desktopShortcutObj.IconLocation = "$appExe,0"
            $desktopShortcutObj.Save()
            OkMsg "shortcuts created (Start Menu + Desktop)"
        } catch {
            WarnMsg "could not create desktop shortcut: $_"
            OkMsg "Start Menu shortcut created (desktop shortcut skipped)"
        }
    } else {
        WarnMsg "install may not have completed - check $InstallDir"
        WarnMsg "you can install manually by running: $($nsisExe.FullName)"
    }
    Write-Host ""
}

# --- Done ---
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Installers produced:" -ForegroundColor White
Write-Host "  NSIS (.exe): $($nsisExe.FullName)"
Write-Host "  MSI (.msi):  $($msiFile.FullName)"
Write-Host ""
if (-not $SkipInstall) {
    Write-Host "Installed to: $InstallDir" -ForegroundColor White
    Write-Host "Launch via:   Start Menu > CorpusMind  (or desktop shortcut)" -ForegroundColor White
    Write-Host ""
}
Write-Host "To reinstall later, just re-run this script." -ForegroundColor Gray
Write-Host ""
