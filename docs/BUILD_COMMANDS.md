# Build Commands for CorpusMind Desktop Apps

> Copy and paste these commands into your terminal on each platform.
> No em dashes are used in this document.

---

## Prerequisites (Both Platforms)

1. Install Rust: https://rustup.rs
2. Install Node.js 20+: https://nodejs.org
3. Install Python 3.12+: https://www.python.org
4. Install Ollama: https://ollama.com

---

## Windows Build (x64)

Open PowerShell and run these commands one by one:

```powershell
# 1. Clone the repository
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind

# 2. Install the engine
cd engine
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pip install python-multipart cryptography opencv-python-headless pillow
python -m spacy download en_core_web_sm
cd ..

# 3. Install web dependencies and build the frontend
cd web
npm install
npm run build
cd ..

# 4. Install Tauri CLI
cargo install tauri-cli --version "^2.0"

# 5. Build the desktop app (produces MSI + NSIS exe)
cd desktop\src-tauri
cargo tauri build
```

The installers will be in:
```
desktop\src-tauri\target\release\bundle\msi\CorpusMind_0.1.0_x64_en-US.msi
desktop\src-tauri\target\release\bundle\nsis\CorpusMind_0.1.0_x64-setup.exe
```

### Windows Notes

- You need Visual Studio C++ Build Tools installed. Download from:
  https://visualstudio.microsoft.com/visual-cpp-build-tools/
  Select "Desktop development with C++".

- You need the WebView2 runtime (usually pre-installed on Windows 10/11).

- The first `cargo tauri build` takes 10 to 20 minutes. Subsequent builds
  are faster due to caching.

- If you get an error about `MSVC`, make sure you have the C++ build tools
  and that you are using the "x64 Native Tools Command Prompt" or that
  the Visual Studio environment is loaded.

---

## macOS Build (Apple Silicon: M1/M2/M3/M4)

Open Terminal and run these commands:

```bash
# 1. Clone the repository
git clone https://github.com/waleedmandour/CorpusMind.git
cd CorpusMind

# 2. Install the engine
cd engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install python-multipart cryptography opencv-python-headless pillow
python -m spacy download en_core_web_sm
cd ..

# 3. Install web dependencies and build the frontend
cd web
npm install
npm run build
cd ..

# 4. Install Tauri CLI
cargo install tauri-cli --version "^2.0"

# 5. Build the desktop app (produces .app + .dmg)
cd desktop/src-tauri
cargo tauri build
```

The installers will be in:
```
desktop/src-tauri/target/release/bundle/macos/CorpusMind.app
desktop/src-tauri/target/release/bundle/dmg/CorpusMind_0.1.0_aarch64.dmg
```

### macOS Notes

- You need Xcode Command Line Tools: `xcode-select --install`

- On Apple Silicon, Rust installs the `aarch64-apple-darwin` target by
  default, so the build is native (no Rosetta needed).

- The first `cargo tauri build` takes 10 to 20 minutes. Subsequent builds
  are faster.

- If you want to codesign the app for distribution, you need an Apple
  Developer certificate. For personal use, right-click the .app and
  select "Open" then "Open anyway" to bypass Gatekeeper.

- The .dmg file is the one you upload to the GitHub release.

---

## After Building: Upload to GitHub Release

Once you have the built installers, upload them to the release:

1. Go to: https://github.com/waleedmandour/CorpusMind/releases
2. Click "Draft a new release" or edit the existing v0.1.0 release
3. Drag and drop your built files into the "Attach binaries" area
4. Click "Publish release" or "Update release"

### Files to Upload

| Platform | File to Upload |
|----------|---------------|
| Windows | `CorpusMind_0.1.0_x64_en-US.msi` and/or `CorpusMind_0.1.0_x64-setup.exe` |
| macOS | `CorpusMind_0.1.0_aarch64.dmg` |

---

## Quick Build (If You Just Want to Test Locally)

If you do not want to build installers and just want to run the app:

```bash
# Terminal 1: Start the engine
cd CorpusMind/engine
source .venv/bin/activate   # Windows: .venv\Scripts\activate
corpusmind-engine

# Terminal 2: Start the web app
cd CorpusMind/web
npm run dev

# Terminal 3: Start Ollama
ollama serve
```

Then open http://localhost:5173 in your browser.
