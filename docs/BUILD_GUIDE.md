# Building CorpusMind on Mac, Windows, and Linux

> This guide covers building the CorpusMind engine, web PWA, and desktop
> app from source on all three major operating systems. No em dashes are
> used in this document.

---

## Table of Contents

1. [Prerequisites Overview](#1-prerequisites-overview)
2. [Building on macOS](#2-building-on-macos)
3. [Building on Windows](#3-building-on-windows)
4. [Building on Linux](#4-building-on-linux)
5. [Deploying the PWA on Vercel](#5-deploying-the-pwa-on-vercel)
6. [Running the Desktop App (Tauri 2)](#6-running-the-desktop-app-tauri-2)
7. [Production Build Checklist](#7-production-build-checklist)

---

## 1. Prerequisites Overview

All three platforms need the same core tools. The installation commands differ.

| Tool | macOS | Windows | Linux |
|------|-------|---------|-------|
| Python 3.12+ | `brew install python@3.12` | Download from python.org | `sudo apt install python3.12 python3.12-venv` |
| Node.js 20+ | `brew install node@20` | Download from nodejs.org | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo bash -` then `sudo apt install nodejs` |
| Git | `brew install git` | Download from git-scm.com | `sudo apt install git` |
| Rust (desktop only) | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` | Same as macOS | Same as macOS |
| Ollama | Download from ollama.com | Download from ollama.com | `curl -fsSL https://ollama.com/install.sh \| sh` |

### Optional: Arabic Support

If you will work with Arabic text, you also need the CAMeL Tools data packages. See Section 2.3, 3.3, or 4.3 for your platform.

### Optional: OCR (Tesseract)

If you want OCR (text extraction from images), install Tesseract:

| Platform | Command |
|----------|---------|
| macOS | `brew install tesseract tesseract-lang` |
| Windows | Download from github.com/UB-Mannheim/tesseract/wiki |
| Linux | `sudo apt install tesseract-ocr tesseract-ocr-ara` |

---

## 2. Building on macOS

### 2.1 Install Prerequisites

Open Terminal and run:

```bash
# Install Homebrew if you do not have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install core tools
brew install python@3.12 node@20 git

# Install Ollama
brew install ollama

# Pull a small model for the AI Assistant
ollama pull llama3.2:3b
```

### 2.2 Clone and Build the Engine

```bash
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind/engine

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install the English spaCy model
python -m spacy download en_core_web_sm

# Install image processing libraries
pip install opencv-python-headless pillow python-multipart

# Start the engine
corpusmind-engine
```

You should see:

```
Uvicorn running on http://127.0.0.1:8765
```

### 2.3 Optional: Arabic Support on macOS

```bash
cd CorpusMind/engine
source .venv/bin/activate

pip install camel-tools pyrsistent muddler cachetools emoji future regex

# Download the morphology database (40 MB)
camel_data -i morphology-db-msa-r13

# Download the dialect identification model (128 MB)
camel_data -i dialectid-model6
```

### 2.4 Build the Web PWA

Open a new Terminal window:

```bash
cd CorpusMind/web
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

To build the production PWA:

```bash
npm run build
```

The built files are in `web/dist/`. You can serve them with any static file server:

```bash
npx serve dist
```

### 2.5 Build the Desktop App (Tauri 2)

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Install Xcode Command Line Tools
xcode-select --install

# Build the desktop app
cd CorpusMind/desktop/src-tauri
cargo tauri dev    # development mode
cargo tauri build  # production build
```

The production build creates a `.app` bundle in `desktop/src-tauri/target/release/bundle/`.

### 2.6 macOS-Specific Notes

- On Apple Silicon (M1/M2/M3/M4), everything runs natively. No Rosetta needed.
- On Intel Macs, the same instructions work. Ollama may be slower with larger models.
- If macOS says "CorpusMind cannot be opened because it is from an unidentified developer", right-click the app and select "Open" and then "Open anyway".
- The first `cargo tauri dev` build takes 5 to 10 minutes (compiling Rust dependencies). Subsequent builds are fast.

### 2.7 One-Shot Apple Silicon Build

For a production build on Apple Silicon, use the bundled build script. It builds
the engine sidecar with PyInstaller, the web PWA with Vite, and the desktop
bundle with Tauri in one pass:

```bash
cd CorpusMind
./scripts/build-macos-arm64.sh
```

What the script does:

1. Creates an isolated Python venv in `engine/.venv-build/` and installs the
   engine plus PyInstaller.
2. Runs `pyinstaller corpusmind-engine.spec` to produce
   `engine/dist/corpusmind-engine` (a single-file executable).
3. Copies the binary to
   `desktop/src-tauri/binaries/corpusmind-engine-aarch64-apple-darwin`,
   which is the path Tauri's `externalBin` mechanism looks for.
4. Builds the web PWA with `npm install && npm run build`.
5. Runs `cargo tauri build --target aarch64-apple-darwin` to produce the
   `.app` bundle and the `.dmg` installer.

Final artifacts:

```
desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/
    dmg/CorpusMind_0.1.0_aarch64.dmg
    macos/CorpusMind.app
```

You can also build just one component:

```bash
./scripts/build-macos-arm64.sh --engine   # sidecar binary only
./scripts/build-macos-arm64.sh --web      # PWA only
./scripts/build-macos-arm64.sh --desktop  # desktop bundle only (requires sidecar already built)
```

### 2.8 Code Signing and Notarization (Optional, for Distribution)

The build script produces an unsigned `.app` / `.dmg`. To distribute the app
to other Mac users without the "unidentified developer" warning, you need an
Apple Developer ID (USD $99/year) and must codesign + notarize:

```bash
APP="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/CorpusMind.app"
DMG="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/CorpusMind_0.1.0_aarch64.dmg"

# 1. Sign the .app bundle (recursively)
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Name (TEAMID)" "$APP"

# 2. Build a signed .dmg from the signed .app (Tauri's bundler does this
#    automatically when APPLE_SIGNING_IDENTITY is set in CI; for local builds
#    use create-dmg or hdiutil).

# 3. Submit the .dmg to Apple for notarization (requires an app-specific password)
xcrun notarytool submit "$DMG" \
  --apple-id you@example.com \
  --team-id TEAMID \
  --password app-specific-pwd \
  --wait

# 4. Staple the notarization ticket to the .dmg
xcrun stapler staple "$DMG"

# 5. Verify
xcrun stapler validate "$DMG"
spctl --assess --type install "$DMG"
```

For automated builds, the GitHub Actions release workflow (`.github/workflows/release.yml`)
performs these steps automatically when you set the following repository secrets:

| Secret | Value |
|--------|-------|
| `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_CERTIFICATE_BASE64` | base64 of your exported `.p12` developer certificate |
| `APPLE_CERTIFICATE_PASSWORD` | password for the `.p12` file |
| `APPLE_ID` | your Apple ID email |
| `APPLE_PASSWORD` | app-specific password from appleid.apple.com |
| `APPLE_TEAM_ID` | your 10-character team ID |

---

## 3. Building on Windows

### 3.1 Install Prerequisites

1. **Python 3.12+**: Download from python.org. During installation, check "Add Python to PATH".

2. **Node.js 20+**: Download from nodejs.org. Use the LTS installer.

3. **Git**: Download from git-scm.com.

4. **Ollama**: Download from ollama.com. After installation, open Command Prompt and run:
   ```
   ollama pull llama3.2:3b
   ```

5. **Visual Studio C++ Build Tools** (for Tauri desktop app): Download from visualstudio.microsoft.com. Select "Desktop development with C++".

### 3.2 Clone and Build the Engine

Open PowerShell or Command Prompt:

```cmd
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind\engine

:: Create virtual environment
python -m venv .venv
.venv\Scripts\activate

:: Install dependencies
pip install -e ".[dev]"

:: Install the English spaCy model
python -m spacy download en_core_web_sm

:: Install image processing libraries
pip install opencv-python-headless pillow python-multipart

:: Start the engine
corpusmind-engine
```

You should see:

```
Uvicorn running on http://127.0.0.1:8765
```

### 3.3 Optional: Arabic Support on Windows

```cmd
cd CorpusMind\engine
.venv\Scripts\activate

pip install camel-tools pyrsistent muddler cachetools emoji future regex

:: Download the morphology database
camel_data -i morphology-db-msa-r13

:: Download the dialect identification model
camel_data -i dialectid-model6
```

### 3.4 Build the Web PWA

Open a new Command Prompt:

```cmd
cd CorpusMind\web
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

To build the production PWA:

```cmd
npm run build
```

The built files are in `web\dist\`.

### 3.5 Build the Desktop App (Tauri 2)

1. Install Rust from rustup.rs. Download and run `rustup-init.exe`.

2. Install the WebView2 runtime (usually pre-installed on Windows 10/11). If not, download it from microsoft.com.

3. Build:

```cmd
cd CorpusMind\desktop\src-tauri
cargo tauri dev
cargo tauri build
```

The production build creates an `.msi` installer and an `.exe` in `desktop\src-tauri\target\release\bundle\`.

### 3.6 Windows-Specific Notes

- Use backslashes `\` in Command Prompt paths, or forward slashes `/` in PowerShell.
- The virtual environment activation command is `.venv\Scripts\activate` (not `source .venv/bin/activate`).
- If `corpusmind-engine` is not found after install, try `python -m app.main` instead.
- Windows Defender may scan the Tauri build. Add the project folder to exclusions if builds are slow.

---

## 4. Building on Linux

### 4.1 Install Prerequisites

Tested on Ubuntu 22.04+ and Debian 12+. Adapt package names for Fedora/Arch.

```bash
# Update package list
sudo apt update

# Install Python 3.12
sudo apt install python3.12 python3.12-venv python3-pip

# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install nodejs

# Install Git
sudo apt install git

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### 4.2 Clone and Build the Engine

```bash
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind/engine

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install the English spaCy model
python -m spacy download en_core_web_sm

# Install image processing libraries
pip install opencv-python-headless pillow python-multipart

# Start the engine
corpusmind-engine
```

You should see:

```
Uvicorn running on http://127.0.0.1:8765
```

### 4.3 Optional: Arabic Support on Linux

```bash
cd CorpusMind/engine
source .venv/bin/activate

pip install camel-tools pyrsistent muddler cachetools emoji future regex

# Download the morphology database
camel_data -i morphology-db-msa-r13

# Download the dialect identification model
camel_data -i dialectid-model6
```

### 4.4 Build the Web PWA

```bash
cd CorpusMind/web
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

To build the production PWA:

```bash
npm run build
```

### 4.5 Build the Desktop App (Tauri 2)

Install system dependencies for Tauri on Linux:

```bash
# Ubuntu / Debian
sudo apt install libwebkit2gtk-4.1-dev \
    build-essential \
    curl \
    wget \
    file \
    libxdo-dev \
    libssl-dev \
    libayatana-appindicator3-dev \
    librsvg2-dev

# Fedora
# sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file \
#     libappindicator-gtk3-devel librsvg2-devel

# Arch
# sudo pacman -S webkit2gtk base-devel curl wget file openssl \
#     libappindicator-gtk3 librsvg
```

Install Rust:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

Build:

```bash
cd CorpusMind/desktop/src-tauri
cargo tauri dev
cargo tauri build
```

The production build creates an `.AppImage` and a `.deb` in `desktop/src-tauri/target/release/bundle/`.

### 4.6 Linux-Specific Notes

- On headless servers (no GUI), you only need the engine, not the web frontend or desktop app. Run the engine and access it from a browser on another machine.
- For GPU acceleration with Ollama on NVIDIA GPUs, install the CUDA toolkit and use `--gpus all` in Docker.
- If `python3.12` is not available in your package manager, use the deadsnakes PPA on Ubuntu:
  ```bash
  sudo add-apt-repository ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install python3.12 python3.12-venv
  ```

---

## 5. Deploying the PWA on Vercel

The CorpusMind PWA (the web frontend) can be deployed on Vercel. The engine must run elsewhere because Vercel does not support persistent Python processes, SQLite on disk, or spaCy/CAMeL Tools.

### 5.1 What Works on Vercel

- The static PWA build (HTML, CSS, JavaScript, service worker, manifest)
- The Vite-built frontend with React

### 5.2 What Does NOT Work on Vercel

- The FastAPI engine (no persistent Python processes)
- SQLite database (no writable filesystem)
- spaCy, CAMeL Tools, OpenCV (heavy native dependencies)
- Ollama or LM Studio (no local LLM runtime)

### 5.3 Architecture for Vercel Deployment

```
[Vercel PWA]  --HTTP-->  [Your Engine Server]  --HTTP-->  [Ollama]
  (frontend)              (FastAPI + SQLite)       (local LLM)
```

### 5.4 Step-by-Step Vercel Deployment

1. **Push the repo to GitHub** (already done at github.com/waleedmandour/CorpusMind).

2. **Go to Vercel**: Open vercel.com and sign in with GitHub.

3. **Import the project**: Click "New Project", select the CorpusMind repository.

4. **Configure the build**:
   - Framework Preset: **Vite**
   - Root Directory: **web**
   - Build Command: `npm run build`
   - Output Directory: `dist`
   - Install Command: `npm install`

5. **Set environment variables**: Under Settings > Environment Variables, add:
   - `VITE_ENGINE_URL` = the URL of your engine server (for example, `https://engine.your-lab.example.org`)

6. **Deploy**: Click "Deploy". Vercel will build the PWA and host it.

7. **Point the PWA at your engine**: The PWA will use the `VITE_ENGINE_URL` environment variable to know where the engine is running.

### 5.5 Running the Engine for Vercel

You need to run the engine on a server that is reachable from the internet. Options:

**Option A: Docker on a VPS**

```bash
# On your VPS (for example, DigitalOcean, Hetzner, AWS EC2)
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind

# Edit infra/docker-compose.yml to expose port 8765 publicly
# (change "127.0.0.1:8765:8765" to "0.0.0.0:8765:8765")

# Or use the Nginx TLS profile:
docker compose -f infra/docker-compose.yml --profile tls up -d
```

**Option B: Direct install on a VPS**

```bash
# On your VPS
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind/engine
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
pip install opencv-python-headless pillow python-multipart

# Run with public binding
CORPUSMIND_HOST=0.0.0.0 CORPUSMIND_PORT=8765 corpusmind-engine
```

**Option C: Use a process manager (recommended for production)**

```bash
# Install gunicorn or use uvicorn workers
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8765
```

### 5.6 CORS Configuration

The engine needs to allow requests from your Vercel domain. Edit `engine/.env`:

```
CORPUSMIND_CORS_ORIGINS=["https://your-app.vercel.app","https://your-custom-domain.com"]
```

Or set it as an environment variable:

```bash
export CORPUSMIND_CORS_ORIGINS='["https://your-app.vercel.app"]'
```

### 5.7 Cloud Provider Configuration

If you want to use a cloud LLM provider (Anthropic, OpenAI) with the Vercel-hosted PWA:

```bash
export CORPUSMIND_CLOUD_PROVIDER=openai
export CORPUSMIND_CLOUD_API_KEY=your-api-key
export CORPUSMIND_CLOUD_DEFAULT_MODEL=gpt-4o-mini
```

The cloud indicator will be visible in the PWA whenever a cloud request is in flight.

---

## 6. Running the Desktop App (Tauri 2)

### 6.1 Development Mode

```bash
cd CorpusMind/desktop/src-tauri
cargo tauri dev
```

This starts the engine as a sidecar process and opens the desktop window. The engine logs are written to:
- macOS: `~/Library/Logs/CorpusMind/`
- Windows: `%APPDATA%\CorpusMind\logs\`
- Linux: `~/.local/share/CorpusMind/logs/`

### 6.2 Production Build

```bash
cargo tauri build
```

This creates platform-specific installers:
- macOS: `.app` bundle and `.dmg` disk image
- Windows: `.msi` installer and `.exe`
- Linux: `.AppImage`, `.deb`, and optionally `.rpm`

### 6.3 First Launch Behavior

On first launch, the desktop app:
1. Checks if Ollama is running on `localhost:11434`
2. If not, offers to start a bundled Ollama sidecar
3. Checks if the engine is running on `localhost:8765`
4. If not, spawns the engine as a sidecar process
5. Waits for the engine health check to pass
6. Opens the webview pointed at the engine

### 6.4 Sidedar Binary (Future)

For a true "double-click and run" experience, the engine needs to be packaged as a single binary using PyInstaller:

```bash
cd CorpusMind/engine
source .venv/bin/activate
pip install pyinstaller
pyinstaller --onefile --name corpusmind-engine-$(rustc -vV | grep host | awk '{print $2}') app/main.py
```

The resulting binary goes in `desktop/binaries/` with the target-triple suffix that Tauri expects. This is a future task that will make the desktop app fully self-contained.

---

## 7. Production Build Checklist

Before deploying to production, verify:

- [ ] Engine runs without errors: `curl http://127.0.0.1:8765/api/v1/health` returns `{"status":"ok"}`
- [ ] All 97 tests pass: `cd engine && pytest tests/ -q`
- [ ] Web builds without errors: `cd web && npm run build`
- [ ] TypeScript has no errors: `cd web && npm run typecheck`
- [ ] Ruff has no errors: `cd engine && ruff check .`
- [ ] Ollama is running and a model is pulled: `ollama list`
- [ ] If using Arabic: CAMeL Tools data is downloaded
- [ ] If using OCR: Tesseract is installed
- [ ] If self-hosting: `CORPUSMIND_CLOUD_DISABLED_HARD=true` is set
- [ ] If using encryption: `CORPUSMIND_ENCRYPTION_KEY` is set and the key is backed up
- [ ] CORS origins include your frontend URL
- [ ] The firewall allows traffic on port 8765 (engine) and 11434 (Ollama) if remote

---

## Quick Reference: Three-Command Start

For any platform, after prerequisites are installed:

```bash
# Terminal 1: Start the engine
cd CorpusMind/engine && source .venv/bin/activate && corpusmind-engine

# Terminal 2: Start the web app
cd CorpusMind/web && npm run dev

# Terminal 3: Start Ollama
ollama serve
```

Then open `http://localhost:5173` in your browser.
