# =========================================================================
# CorpusMind — Windows one-shot build + reinstall script
# =========================================================================
#
# Builds BOTH .exe (NSIS) and .msi installers, uninstalls any previous
# version, and installs the new build for the current user
# (C:\Users\Waleed Mandour).
#
# Requirements (the script checks for these and tells you how to install
# any that are missing):
#   - Python 3.12  (https://python.org)
#   - Node.js 20   (https://nodejs.org)
#   - Rust stable  (https://rustup.rs)
#   - Git          (https://git-scm.com)
#   - WebView2 Runtime (preinstalled on Windows 11; Windows 10 may need it)
#
# Usage:
#   1. Open PowerShell as a regular user (NOT Administrator — NSIS per-user
#      install doesn't need elevation; MSI per-user also doesn't).
#   2. cd to the CorpusMind repo root (the folder containing this script's
#      parent — i.e. the folder with `engine/`, `web/`, `desktop/`).
#   3. Run:
#        powershell -ExecutionPolicy Bypass -File scripts\build-corpusmind-windows.ps1
#
# What it does, in order:
#   0. Checks prerequisites (Python, Node, Rust, Git)
#   1. Removes any previously-installed CorpusMind (NSIS + MSI, both
#      per-user and per-machine, best-effort)
#   2. Sets up the engine venv + installs deps + downloads spaCy model
#   3. Builds the PyInstaller sidecar (corpusmind-engine.exe)
#   4. Stages the sidecar for Tauri (binaries\corpusmind-engine-x86_64-pc-windows-msvc.exe)
#   5. Builds the web PWA (web\dist\)
#   6. Runs `cargo tauri build` — produces BOTH:
#        desktop\src-tauri\target\release\bundle\nsis\CorpusMind_0.1.0_x64-setup.exe
#        desktop\src-tauri\target\release\bundle\msi\CorpusMind_0.1.0_x64_en-US.msi
#   7. Installs the NSIS .exe silently for the current user
#   8. (MSI is left alongside for manual install or enterprise deployment)
#
# =========================================================================

param(
    [string]$RepoRoot = (Get-Location).Path,
    [switch]$SkipUninstall = $false,
    [switch]$SkipInstall = $false
)

$ErrorActionPreference = "Stop"

# ─── helpers ────────────────────────────────────────────────────────────
function Log($msg)  { Write-Host "[build] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "  FAIL  $msg" -ForegroundColor Red; exit 1 }

$UserName = $env:USERNAME  # e.g. "Waleed Mandour"
$InstallDir = "$env:LOCALAPPDATA\Programs\CorpusMind"
$StartMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\CorpusMind"

Log "CorpusMind v0.1.0 — Windows build + reinstall"
Log "Repo root:  $RepoRoot"
Log "User:       $UserName"
Log "Install to: $InstallDir"
Write-Host ""

# ─── 0. Prerequisites ───────────────────────────────────────────────────
Log "checking prerequisites..."

$python = (Get-Command python -ErrorAction SilentlyContinue) ? "python" : $null
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue) ? "python3" : $null }
if (-not $python) { Die "Python not found. Install Python 3.12 from https://python.org and re-run." }
$pyVer = & $python --version 2>&1
Ok "Python: $pyVer"

$node = (Get-Command node -ErrorAction SilentlyContinue)
if (-not $node) { Die "Node.js not found. Install Node 20 from https://nodejs.org and re-run." }
Ok "Node: $(node --version)"

$cargo = (Get-Command cargo -ErrorAction SilentlyContinue)
if (-not $cargo) {
    Warn "Rust not found. Installing via rustup..."
    Invoke-WebRequest -Uri 'https://win.rustup.rs/x86_64' -OutFile "$env:TEMP\rustup-init.exe"
    & "$env:TEMP\rustup-init.exe" -y
    $env:Path += ";$env:USERPROFILE\.cargo\bin"
    . "$env:USERPROFILE\.cargo\env" 2>$null
}
Ok "Rust: $(rustc --version)"

$git = (Get-Command git -ErrorAction SilentlyContinue)
if (-not $git) { Die "Git not found. Install from https://git-scm.com and re-run." }
Ok "Git: $(git --version)"

# Tauri CLI
if (-not (Get-Command cargo-tauri -ErrorAction SilentlyContinue)) {
    Warn "Tauri CLI not found. Installing (this takes ~3 minutes)..."
    cargo install tauri-cli --version "^2.0" --locked
}
Ok "Tauri CLI: $(cargo tauri --version 2>&1 | Select-Object -First 1)"
Write-Host ""

# ─── 1. Uninstall any previous version ──────────────────────────────────
if (-not $SkipUninstall) {
    Log "removing any previously-installed CorpusMind..."

    # 1a. NSIS per-user uninstaller (the one we ship installs here)
    $nsisUninstaller = "$InstallDir\corpusmind-desktop-uninstaller.exe"
    if (Test-Path $nsisUninstaller) {
        Warn "found NSIS install at $InstallDir — running uninstaller silently..."
        try {
            Start-Process -FilePath $nsisUninstaller -ArgumentList "/S" -Wait -NoNewWindow
            Ok "NSIS uninstalled"
        } catch {
            Warn "NSIS uninstaller failed: $_ — will remove files manually"
        }
    }

    # 1b. MSI-based install (in case a previous MSI was installed)
    $msiProduct = Get-CimInstance Win32_Product -Filter "Name LIKE '%CorpusMind%'" -ErrorAction SilentlyContinue
    if ($msiProduct) {
        Warn "found MSI install: $($msiProduct.Name) — uninstalling..."
        try {
            $msiProduct | Invoke-CimMethod -MethodName Uninstall | Out-Null
            Ok "MSI uninstalled"
        } catch {
            Warn "MSI uninstall failed: $_"
        }
    }

    # 1c. Clean up any leftover files
    foreach ($p in @($InstallDir, $StartMenuDir)) {
        if (Test-Path $p) {
            Warn "removing leftover: $p"
            Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
        }
    }

    # 1d. Remove desktop/start-menu shortcuts
    $desktopShortcut = "$env:USERPROFILE\Desktop\CorpusMind.lnk"
    $startShortcut = "$StartMenuDir\CorpusMind.lnk"
    foreach ($s in @($desktopShortcut, $startShortcut)) {
        if (Test-Path $s) { Remove-Item -Force $s -ErrorAction SilentlyContinue }
    }

    # 1e. Wait for file locks to release
    Start-Sleep -Seconds 2
    Ok "previous version removed"
    Write-Host ""
}

# ─── 2. Engine venv + deps ──────────────────────────────────────────────
Log "setting up Python engine venv..."
$EngineDir = Join-Path $RepoRoot "engine"
if (-not (Test-Path "$EngineDir\.venv")) {
    & $python -m venv "$EngineDir\.venv"
}
$Pip = "$EngineDir\.venv\Scripts\pip.exe"
$PyExe = "$EngineDir\.venv\Scripts\python.exe"
& $Pip install --upgrade pip wheel --quiet
& $Pip install pyinstaller python-multipart cryptography --quiet
& $Pip install -e "$EngineDir[dev,vision]" --quiet
Ok "engine deps installed"

Log "downloading spaCy English model..."
& $PyExe -m spacy download en_core_web_sm 2>$null
Ok "spaCy model ready"
Write-Host ""

# ─── 3. Build engine sidecar (PyInstaller) ──────────────────────────────
Log "building engine sidecar (PyInstaller)..."
Push-Location $EngineDir
& $PyExe -m PyInstaller corpusmind-engine.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "PyInstaller build failed" }
Pop-Location

$sidecarSrc = "$EngineDir\dist\corpusmind-engine.exe"
if (-not (Test-Path $sidecarSrc)) { Die "sidecar not found at $sidecarSrc" }
Ok "sidecar built: $sidecarSrc ($(Get-Item $sidecarSrc | Select-Object -ExpandProperty Length | ForEach-Object { '{0:N1} MB' -f ($_ / 1MB) }))"
Write-Host ""

# ─── 4. Stage sidecar for Tauri ─────────────────────────────────────────
Log "staging sidecar for Tauri..."
$BinariesDir = Join-Path $RepoRoot "desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
$sidecarDest = "$BinariesDir\corpusmind-engine-x86_64-pc-windows-msvc.exe"
Copy-Item -Force $sidecarSrc $sidecarDest
Ok "staged: $sidecarDest"
Write-Host ""

# ─── 5. Build web PWA ───────────────────────────────────────────────────
Log "building web PWA..."
$WebDir = Join-Path $RepoRoot "web"
Push-Location $WebDir
npm install --silent
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "PWA build failed" }
Pop-Location
if (-not (Test-Path "$WebDir\dist\index.html")) { Die "PWA build failed — missing dist\index.html" }
Ok "PWA built → web\dist\"
Write-Host ""

# ─── 6. Build Tauri app (produces BOTH .exe and .msi) ───────────────────
Log "building Tauri desktop bundle (NSIS .exe + MSI .msi)..."
Log "  this takes 5–15 minutes on first run..."
$TauriDir = Join-Path $RepoRoot "desktop\src-tauri"
Push-Location $TauriDir
cargo tauri build
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "cargo tauri build failed" }
Pop-Location

$BundleDir = "$TauriDir\target\release\bundle"
$nsisExe = Get-ChildItem "$BundleDir\nsis\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$msiFile = Get-ChildItem "$BundleDir\msi\*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $nsisExe) { Die "NSIS .exe not found in $BundleDir\nsis\" }
if (-not $msiFile) { Die "MSI not found in $BundleDir\msi\" }

Ok "NSIS installer: $($nsisExe.FullName) ($('{0:N1} MB' -f ($nsisExe.Length / 1MB)))"
Ok "MSI installer:  $($msiFile.FullName) ($('{0:N1} MB' -f ($msiFile.Length / 1MB)))"
Write-Host ""

# ─── 7. Install the NSIS .exe silently for the current user ─────────────
if (-not $SkipInstall) {
    Log "installing NSIS build for $UserName..."
    # NSIS /S = silent, /D = install dir (must be last, no quotes, no trailing slash)
    $installArgs = "/S", "/D=$InstallDir"
    Start-Process -FilePath $nsisExe.FullName -ArgumentList $installArgs -Wait -NoNewWindow
    Start-Sleep -Seconds 3

    if (Test-Path "$InstallDir\corpusmind-desktop.exe") {
        Ok "installed to $InstallDir"

        # Create Start Menu shortcut
        New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut("$StartMenuDir\CorpusMind.lnk")
        $shortcut.TargetPath = "$InstallDir\corpusmind-desktop.exe"
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.IconLocation = "$InstallDir\corpusmind-desktop.exe,0"
        $shortcut.Save()

        # Create desktop shortcut
        $desktopShortcut = "$env:USERPROFILE\Desktop\CorpusMind.lnk"
        $desktopShortcutObj = $shell.CreateShortcut($desktopShortcut)
        $desktopShortcutObj.TargetPath = "$InstallDir\corpusmind-desktop.exe"
        $desktopShortcutObj.WorkingDirectory = $InstallDir
        $desktopShortcutObj.IconLocation = "$InstallDir\corpusmind-desktop.exe,0"
        $desktopShortcutObj.Save()

        Ok "shortcuts created (Start Menu + Desktop)"
    } else {
        Warn "install may not have completed — check $InstallDir"
        Warn "you can install manually by running: $($nsisExe.FullName)"
    }
    Write-Host ""
}

# ─── Done ───────────────────────────────────────────────────────────────
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
Write-Host "To reinstall later, just re-run this script — it uninstalls the old" -ForegroundColor Gray
Write-Host "version first, then builds + installs the new one." -ForegroundColor Gray
Write-Host ""
