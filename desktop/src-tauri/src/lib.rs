//! CorpusMind desktop shell — Tauri 2 lifecycle.
//!
//! Responsibilities (§3.4):
//!   - spawn corpusmind-engine as a sidecar on app start
//!   - poll its /api/v1/health endpoint until ready (or timeout)
//!   - redirect sidecar stdout/stderr to a log file (NOT piped — piped
//!     stdout can hang on buffer-size limits)
//!   - on app exit, fully detach + clean up the child to avoid orphaned
//!     "zombie" processes
//!   - on macOS, strip the quarantine attribute from any bundled binary
//!     before launching it (unsigned bundled binaries are quarantined)
//!
//! Phase 0 ships the supervisor skeleton; the actual bundled binary is
//! produced by PyInstaller in CI (or `pyinstaller --onefile` locally).
//! For development we fall back to spawning `python -m app.main` if the
//! sidecar binary is missing, so a developer can run `cargo tauri dev`
//! without first building the PyInstaller bundle.

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use log::{error, info, warn};
use tauri::{Manager, State};
use thiserror::Error;

const ENGINE_HOST: &str = "127.0.0.1";
const ENGINE_PORT: u16 = 8765;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(500);

// ─── Ollama auto-start manager ──────────────────────────────────────
// Finds the ollama executable, spawns `ollama serve` if not running,
// and shuts it down when the app closes. The user never has to open
// Ollama manually.

struct OllamaManager {
    child: Mutex<Option<Child>>,
}

impl OllamaManager {
    fn new() -> Self {
        Self { child: Mutex::new(None) }
    }

    /// Find the ollama executable on the system.
    fn find_ollama() -> Option<String> {
        // 1. Check PATH
        if let Ok(path) = std::env::var("PATH") {
            for dir in path.split(if cfg!(windows) { ';' } else { ':' }) {
                let exe_name = if cfg!(windows) { "ollama.exe" } else { "ollama" };
                let candidate = std::path::Path::new(dir).join(exe_name);
                if candidate.exists() {
                    return Some(candidate.to_string_lossy().into_owned());
                }
            }
        }

        // 2. Check common Windows install locations (expanded for Ollama 0.4+)
        #[cfg(windows)]
        {
            let mut locations: Vec<String> = Vec::new();
            if let Ok(la) = std::env::var("LOCALAPPDATA") {
                locations.push(format!("{}\\Programs\\Ollama\\ollama.exe", la));
                // Newer Ollama installers sometimes place it directly here
                locations.push(format!("{}\\Ollama\\ollama.exe", la));
            }
            // Ollama's default installer puts it in AppData\Local\Ollama
            if let Ok(la) = std::env::var("LOCALAPPDATA") {
                locations.push(format!("{}\\Ollama\\ollama.exe", la));
            }
            if let Ok(pf) = std::env::var("PROGRAMFILES") {
                locations.push(format!("{}\\Ollama\\ollama.exe", pf));
            }
            if let Ok(pf86) = std::env::var("PROGRAMFILES(X86)") {
                locations.push(format!("{}\\Ollama\\ollama.exe", pf86));
            }
            // WindowsApps (if installed via winget)
            if let Ok(la) = std::env::var("LOCALAPPDATA") {
                locations.push(format!("{}\\Microsoft\\WindowsApps\\ollama.exe", la));
            }
            // Some installs go to the user profile
            if let Ok(home) = std::env::var("USERPROFILE") {
                locations.push(format!("{}\\AppData\\Local\\Programs\\Ollama\\ollama.exe", home));
                locations.push(format!("{}\\AppData\\Local\\Ollama\\ollama.exe", home));
            }
            for loc in &locations {
                if std::path::Path::new(loc).exists() {
                    return Some(loc.clone());
                }
            }

            // 3. Windows fallback: use `where ollama` (like `which` on Unix)
            //    This catches cases where Ollama is on PATH but the PATH env
            //    var seen by the Tauri process differs from the user's shell.
            if let Ok(output) = std::process::Command::new("where").arg("ollama").output() {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    if let Some(first_line) = stdout.lines().next() {
                        let path = first_line.trim();
                        if !path.is_empty() && std::path::Path::new(path).exists() {
                            return Some(path.to_string());
                        }
                    }
                }
            }
        }

        // 4. Check macOS install location
        #[cfg(target_os = "macos")]
        {
            let loc = "/usr/local/bin/ollama";
            if std::path::Path::new(loc).exists() {
                return Some(loc.to_string());
            }
            let loc = "/opt/homebrew/bin/ollama";
            if std::path::Path::new(loc).exists() {
                return Some(loc.to_string());
            }
            // /Applications/Ollama.app (GUI install)
            let loc = "/Applications/Ollama.app/Contents/Resources/ollama";
            if std::path::Path::new(loc).exists() {
                return Some(loc.to_string());
            }
        }

        // 5. Unix fallback: use `which ollama`
        #[cfg(unix)]
        {
            if let Ok(output) = std::process::Command::new("which").arg("ollama").output() {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    if let Some(first_line) = stdout.lines().next() {
                        let path = first_line.trim();
                        if !path.is_empty() && std::path::Path::new(path).exists() {
                            return Some(path.to_string());
                        }
                    }
                }
            }
        }

        None
    }

    /// Start `ollama serve` as a background process if not already running.
    fn start(&self) -> Result<bool, String> {
        let mut child_opt = self.child.lock().unwrap();
        if child_opt.is_some() {
            return Ok(true); // Already started by us
        }

        // Check if Ollama is already running (maybe user started it)
        // We can't call async here, so we use a blocking check
        let already_running = {
            let client = reqwest::blocking::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(3))
                .build()
                .map_err(|e| format!("HTTP client: {e}"))?;
            client.get("http://127.0.0.1:11434/api/tags").send()
                .map(|r| r.status().is_success())
                .unwrap_or(false)
        };

        if already_running {
            info!(target: "ollama", "ollama already running — not starting a new instance");
            return Ok(true);
        }

        // Find the ollama executable
        let ollama_exe = Self::find_ollama()
            .ok_or_else(|| "Ollama not found. Install from https://ollama.com".to_string())?;

        info!(target: "ollama", "starting ollama serve from: {}", ollama_exe);

        // Spawn `ollama serve` — it runs as a daemon and listens on 11434
        // Redirect output to a log file so Smart Troubleshooting can read it.
        let log_dir = dirs::data_dir()
            .or_else(|| std::env::var("HOME").ok().map(std::path::PathBuf::from))
            .unwrap_or_else(|| std::path::PathBuf::from("."));
        let log_dir = log_dir.join("corpusmind").join("logs");
        std::fs::create_dir_all(&log_dir).ok();
        let ollama_log = log_dir.join("ollama.log");

        let mut cmd = Command::new(&ollama_exe);
        cmd.arg("serve");

        // Try to open log file; fall back to null if it fails
        match std::fs::File::create(&ollama_log) {
            Ok(f) => {
                let stderr = std::fs::OpenOptions::new()
                    .create(true).append(true).open(&ollama_log)
                    .unwrap_or_else(|_| std::fs::File::create(&ollama_log).unwrap_or_else(|_| {
                        // Last resort: null
                        return std::fs::File::create(
                            if cfg!(windows) { "NUL" } else { "/dev/null" }
                        ).unwrap();
                    }));
                cmd.stdout(Stdio::from(f)).stderr(Stdio::from(stderr));
            }
            Err(_) => {
                cmd.stdout(Stdio::null()).stderr(Stdio::null());
            }
        }

        let child = cmd.spawn()
            .map_err(|e| format!("Failed to start ollama: {e}"))?;

        *child_opt = Some(child);
        info!(target: "ollama", "ollama serve started (PID: {})", child_opt.as_ref().unwrap().id());
        Ok(true)
    }

    /// Wait for Ollama to be ready (poll /api/tags).
    fn wait_for_ready(&self) -> bool {
        let start = Instant::now();
        let timeout = Duration::from_secs(15);

        let client = match reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(3))
            .build()
        {
            Ok(c) => c,
            Err(_) => return false,
        };

        while start.elapsed() < timeout {
            if let Ok(r) = client.get("http://127.0.0.1:11434/api/tags").send() {
                if r.status().is_success() {
                    info!(target: "ollama", "ollama ready after {:?}", start.elapsed());
                    return true;
                }
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        warn!(target: "ollama", "ollama did not become ready within {:?}", timeout);
        false
    }

    fn shutdown(&self) {
        let mut child_opt = self.child.lock().unwrap();
        if let Some(mut child) = child_opt.take() {
            let _ = child.kill();
            let _ = child.wait();
            info!(target: "ollama", "ollama serve shut down");
        }
    }
}

impl Drop for OllamaManager {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[derive(Debug, Error)]
pub enum SidecarError {
    #[error("failed to spawn engine sidecar: {0}")]
    Spawn(String),
    #[error("engine did not become healthy within {0:?}")]
    Timeout(Duration),
    #[error("engine health check request failed: {0}")]
    Health(String),
}

struct EngineSidecar {
    child: Mutex<Option<Child>>,
}

impl EngineSidecar {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    fn spawn(&self, app: &tauri::AppHandle) -> Result<(), SidecarError> {
        let mut child_opt = self.child.lock().unwrap();
        if child_opt.is_some() {
            warn!("engine sidecar already running — skipping spawn");
            return Ok(());
        }

        let log_path = app
            .path()
            .app_log_dir()
            .map_err(|e| SidecarError::Spawn(format!("log dir: {e}")))?;
        std::fs::create_dir_all(&log_path).ok();
        let stdout_path = log_path.join("engine.stdout.log");
        let stderr_path = log_path.join("engine.stderr.log");

        let stdout = std::fs::File::create(&stdout_path)
            .map_err(|e| SidecarError::Spawn(format!("create {}: {e}", stdout_path.display())))?;
        let stderr = std::fs::File::create(&stderr_path)
            .map_err(|e| SidecarError::Spawn(format!("create {}: {e}", stderr_path.display())))?;

        // Try the bundled sidecar binary first; fall back to `python -m app.main`
        // for dev when the binary isn't present. Returns (program, args, working_dir).
        let (program, args, working_dir) = self.resolve_command(app);

        info!(target: "sidecar", "spawning engine: {} {}", program, args.join(" "));
        if let Some(ref wd) = working_dir {
            info!(target: "sidecar", "working dir: {}", wd.display());
        }
        info!(target: "sidecar", "stdout → {}", stdout_path.display());
        info!(target: "sidecar", "stderr → {}", stderr_path.display());

        let mut cmd = Command::new(&program);
        cmd.args(&args)
            .env("CORPUSMIND_HOST", ENGINE_HOST)
            .env("CORPUSMIND_PORT", ENGINE_PORT.to_string())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));

        // Set the working directory if we have one (needed for `python -m app.main`
        // to find the `app` package — Python resolves modules relative to CWD).
        if let Some(ref wd) = working_dir {
            cmd.current_dir(wd);
            // Also set PYTHONPATH to the engine dir so Python can find
            // the `app` package even if the CWD resolution doesn't work.
            // This is critical on Windows where path resolution can differ.
            cmd.env("PYTHONPATH", wd);
        }

        let mut child = cmd.spawn()
            .map_err(|e| SidecarError::Spawn(format!("{program}: {e}")))?;

        // Post-spawn liveness check: wait 2 seconds, then verify the process
        // is still alive. If it exited immediately (common causes: missing
        // dependencies, port conflict, broken venv, "No module named app"),
        // we log the exit code and read the stderr log so the user can see
        // WHY it failed in the diagnostics panel. Without this check, a
        // crash leaves empty logs and a confusing "amber" state where the
        // native check fails too (engine truly offline, not just unreachable).
        let child_id = child.id();
        std::thread::sleep(Duration::from_secs(2));
        // try_wait returns Ok(None) if the process is still running
        match child.try_wait() {
            Ok(None) => {
                // Still running — good
                info!(target: "sidecar", "engine process alive (PID: {})", child_id);
            }
            Ok(Some(status)) => {
                // Process exited — read the stderr log to find out why
                let stderr_content = std::fs::read_to_string(&stderr_path).unwrap_or_default();
                error!(target: "sidecar", "engine process exited immediately: {} (exit code: {:?})", status, status.code());
                if !stderr_content.is_empty() {
                    error!(target: "sidecar", "engine stderr:\n{}", stderr_content);
                } else {
                    error!(target: "sidecar", "engine stderr is EMPTY — process may have crashed before writing any output (broken venv, missing python.exe, or antivirus interference)");
                }
                // Don't store the dead child — let the caller know spawn failed
                return Err(SidecarError::Spawn(format!(
                    "Engine process exited immediately: {}. stderr: {}",
                    status,
                    if stderr_content.is_empty() { "(empty — likely broken venv or missing deps)" } else { stderr_content.trim() }
                )));
            }
            Err(e) => {
                warn!(target: "sidecar", "could not check engine process status: {e}");
            }
        }

        *child_opt = Some(child);
        Ok(())
    }

    /// Pick the right binary/args combo:
    ///   1. If a Tauri sidecar binary is registered for the current target, use it.
    ///   2. Otherwise, fall back to `python -m app.main` from the engine/ directory
    ///      (dev mode — assumes the developer has the venv active).
    ///   3. Otherwise, fall back to `corpusmind-engine` on PATH.
    ///
    /// Returns (program, args, working_dir). The working_dir is Some when running
    /// via `python -m app.main` (needed so Python can find the `app` package).
    fn resolve_command(&self, app: &tauri::AppHandle) -> (String, Vec<String>, Option<std::path::PathBuf>) {
        // Tauri's externalBin lookup expects the binary to be suffixed with the
        // Rust target triple of the build host.
        let target_triple = target_triple();

        // 1a. Onedir mode: the sidecar is a directory inside resources/
        //     (corpusmind-engine/corpusmind-engine.exe)
        //     This is the preferred layout — much faster to build than onefile.
        //     The resources config maps "binaries/corpusmind-engine/" → "corpusmind-engine/"
        //     so the sidecar lands at resources/corpusmind-engine/corpusmind-engine.exe
        if let Ok(resource) = app.path().resource_dir() {
            let exe_name = if cfg!(windows) { "corpusmind-engine.exe" } else { "corpusmind-engine" };
            // Primary path: resources/corpusmind-engine/corpusmind-engine.exe
            // (matches the map-form resources config)
            let candidate = resource.join("corpusmind-engine").join(exe_name);
            if candidate.exists() {
                info!(target: "sidecar", "found bundled sidecar (onedir): {}", candidate.display());
                return (candidate.to_string_lossy().into_owned(), vec![], None);
            }
            // Fallback path: resources/binaries/corpusmind-engine/corpusmind-engine.exe
            // (matches the glob-form resources config, for backward compat)
            let candidate_glob = resource.join("binaries").join("corpusmind-engine").join(exe_name);
            if candidate_glob.exists() {
                info!(target: "sidecar", "found bundled sidecar (glob layout): {}", candidate_glob.display());
                return (candidate_glob.to_string_lossy().into_owned(), vec![], None);
            }
        }

        // 1b. Onefile mode (legacy): the sidecar is a single binary with the
        //     target triple suffix (corpusmind-engine-x86_64-pc-windows-msvc.exe)
        if let Ok(resource) = app.path().resource_dir() {
            let candidate = resource.join(format!("corpusmind-engine-{target_triple}"));
            if candidate.exists() {
                info!(target: "sidecar", "found bundled sidecar (onefile): {}", candidate.display());
                return (candidate.to_string_lossy().into_owned(), vec![], None);
            }
        }

        // 2-6. Find the engine directory (env var, relative paths, common install locations)
        let engine_dir = std::env::var("CORPUSMIND_ENGINE_DIR").ok().map(std::path::PathBuf::from)
            .or_else(|| {
                std::env::current_exe()
                    .ok()
                    .and_then(|exe| exe.parent().map(|p| p.to_path_buf()))
                    .and_then(|p| p.parent().map(|gp| gp.join("engine")))
                    .filter(|d| d.exists())
            })
            .or_else(|| {
                std::env::current_dir()
                    .ok()
                    .and_then(|cwd| cwd.parent().map(|p| p.join("engine")))
                    .filter(|d| d.exists())
            })
            .or_else(|| {
                // Windows: check Documents\CorpusMind\engine
                // Also check OneDrive\Documents (common on Windows 10/11)
                #[cfg(windows)]
                {
                    // Try standard Documents
                    if let Ok(home) = std::env::var("USERPROFILE") {
                        let p = std::path::PathBuf::from(&home).join("Documents").join("CorpusMind").join("engine");
                        if p.exists() {
                            return Some(p);
                        }
                        // Try OneDrive Documents
                        let p2 = std::path::PathBuf::from(&home).join("OneDrive").join("Documents").join("CorpusMind").join("engine");
                        if p2.exists() {
                            return Some(p2);
                        }
                        // Try OneDrive - Personal
                        let p3 = std::path::PathBuf::from(&home).join("OneDrive - Personal").join("Documents").join("CorpusMind").join("engine");
                        if p3.exists() {
                            return Some(p3);
                        }
                    }
                    None
                }
                #[cfg(not(windows))]
                { None }
            })
            .or_else(|| {
                // macOS: check ~/Documents/CorpusMind/engine
                #[cfg(target_os = "macos")]
                {
                    std::env::var("HOME").ok()
                        .map(|home| std::path::PathBuf::from(home).join("Documents").join("CorpusMind").join("engine"))
                        .filter(|d| d.exists())
                }
                #[cfg(not(target_os = "macos"))]
                { None }
            });

        if let Some(dir) = engine_dir {
            info!(target: "sidecar", "found engine dir: {}", dir.display());
            // Try the venv first, then system python.
            let venv_python = if cfg!(windows) {
                dir.join(".venv").join("Scripts").join("python.exe")
            } else {
                dir.join(".venv").join("bin").join("python")
            };
            if venv_python.exists() {
                info!(target: "sidecar", "using venv python: {}", venv_python.display());
                return (
                    venv_python.to_string_lossy().into_owned(),
                    vec!["-m".into(), "app.main".into()],
                    Some(dir),
                );
            }

            // Windows: also try the corpusmind-engine console script
            // (installed by pip install -e . in the venv)
            #[cfg(windows)]
            {
                let console_script = dir.join(".venv").join("Scripts").join("corpusmind-engine.exe");
                if console_script.exists() {
                    info!(target: "sidecar", "using console script: {}", console_script.display());
                    return (
                        console_script.to_string_lossy().into_owned(),
                        vec![],
                        None,  // console script doesn't need a working dir
                    );
                }
            }

            // Last-resort: try `python` on PATH with the engine dir as CWD.
            // But first check if `python` actually exists.
            let python_cmd = if cfg!(windows) { "python" } else { "python3" };
            warn!(target: "sidecar", "venv python not found in {}, trying system python: {}", dir.display(), python_cmd);
            return (
                python_cmd.to_string(),
                vec!["-m".into(), "app.main".into()],
                Some(dir),
            );
        }

        // Final fallback: hope the wheel's console script is on PATH.
        warn!(target: "sidecar", "no engine dir found — trying corpusmind-engine on PATH");
        ("corpusmind-engine".into(), vec![], None)
    }

    fn wait_for_health(&self) -> Result<(), SidecarError> {
        let url = format!("http://{ENGINE_HOST}:{ENGINE_PORT}/api/v1/health");
        let start = Instant::now();

        // Use a simple blocking client — we're already on a background thread.
        // Bypass proxies for loopback traffic (corporate VPN fix from RDAT project).
        let client = reqwest::blocking::Client::builder()
            .timeout(HEALTH_POLL_INTERVAL)
            .no_proxy()
            .build()
            .map_err(|e| SidecarError::Health(e.to_string()))?;

        loop {
            if start.elapsed() > HEALTH_TIMEOUT {
                return Err(SidecarError::Timeout(HEALTH_TIMEOUT));
            }
            match client.get(&url).send() {
                Ok(r) if r.status().is_success() => {
                    info!(target: "sidecar", "engine healthy after {:?}", start.elapsed());
                    return Ok(());
                }
                Ok(r) => warn!(target: "sidecar", "health check returned {}", r.status()),
                Err(e) => warn!(target: "sidecar", "health check failed: {e}"),
            }
            std::thread::sleep(HEALTH_POLL_INTERVAL);
        }
    }

    /// Kill the child process if it's still running. Called on app exit.
    /// We use `kill` rather than graceful shutdown because the engine is a
    /// child process — when the parent (Tauri) exits, the OS will reap it,
    /// but we want to be explicit to avoid orphaned processes (§3.4).
    fn shutdown(&self) {
        let mut child_opt = self.child.lock().unwrap();
        if let Some(mut child) = child_opt.take() {
            // Force-kill the child. std::process::Child::kill() is
            // cross-platform — SIGKILL on Unix, TerminateProcess on
            // Windows — so no cfg gates are needed.
            let _ = child.kill();
            let _ = child.wait();
            info!(target: "sidecar", "engine sidecar shut down");
        }
    }
}

impl Drop for EngineSidecar {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[tauri::command]
async fn engine_health() -> Result<String, String> {
    // Async health check the webview can call to verify the sidecar is up.
    // Uses async reqwest to avoid blocking the Tauri async runtime.
    let url = format!("http://{ENGINE_HOST}:{ENGINE_PORT}/api/v1/health");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .no_proxy()
        .build()
        .map_err(|e| e.to_string())?;
    let r = client.get(&url).send().await.map_err(|e| e.to_string())?;
    let body = r.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

#[tauri::command]
fn sidecar_status(app: tauri::AppHandle) -> String {
    // Diagnostic command — returns what the sidecar resolver would pick.
    let sidecar: State<EngineSidecar> = app.state();
    let (program, args, working_dir) = sidecar.resolve_command(&app);
    let wd_str = working_dir
        .map(|d| d.display().to_string())
        .unwrap_or_else(|| "(none)".to_string());
    format!(
        "program: {}\nargs: {}\nworking_dir: {}",
        program,
        args.join(" "),
        wd_str
    )
}

/// Check if Ollama is running by trying to reach its /api/tags endpoint
/// directly from Rust (bypassing any proxy/VPN that might intercept
/// loopback traffic). This is the #1 fix for "Ollama not detected" on
/// Windows machines with corporate VPN/security software.
///
/// Tries 3 URLs in order (matching the RDAT project's pattern):
///   1. http://127.0.0.1:11434/api/tags (IPv4 explicit — most reliable)
///   2. http://localhost:11434/api/tags (fallback)
///   3. OLLAMA_HOST env var (if set)
#[tauri::command]
async fn ollama_health() -> String {
    let mut urls = vec![
        "http://127.0.0.1:11434/api/tags".to_string(),
        "http://localhost:11434/api/tags".to_string(),
    ];

    // Also check OLLAMA_HOST env var
    if let Ok(host) = std::env::var("OLLAMA_HOST") {
        let normalized = if host.starts_with("http://") || host.starts_with("https://") {
            host
        } else if host.contains(':') {
            format!("http://{}", host)
        } else {
            format!("http://{}:11434", host)
        };
        let url = format!("{}/api/tags", normalized);
        if !urls.contains(&url) {
            urls.insert(0, url);
        }
    }

    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build();

    match client {
        Ok(c) => {
            for url in &urls {
                match c.get(url).send().await {
                    Ok(r) if r.status().is_success() => {
                        info!(target: "ollama", "ollama healthy via: {}", url);
                        return serde_json::json!({
                            "healthy": true,
                            "url": url,
                            "message": "Ollama is running"
                        }).to_string();
                    }
                    Ok(r) => {
                        warn!(target: "ollama", "ollama {} returned: {}", url, r.status());
                    }
                    Err(e) => {
                        warn!(target: "ollama", "ollama {} failed: {}", url, e);
                    }
                }
            }
            serde_json::json!({
                "healthy": false,
                "url": null,
                "message": "Ollama is not running. Start it with `ollama serve`."
            }).to_string()
        }
        Err(e) => {
            serde_json::json!({
                "healthy": false,
                "url": null,
                "message": format!("Failed to create HTTP client: {}", e)
            }).to_string()
        }
    }
}

/// Restart the engine sidecar — callable from the UI "Recheck" button.
/// Shuts down any existing engine process, then spawns a new one.
#[tauri::command]
async fn restart_engine(app: tauri::AppHandle) -> String {
    let sidecar: State<EngineSidecar> = app.state();

    // Shut down existing engine
    sidecar.shutdown();

    // Small delay to let the port free up
    std::thread::sleep(Duration::from_millis(500));

    // Spawn new engine
    match sidecar.spawn(&app) {
        Ok(()) => {
            // Wait for health in a blocking thread
            let handle = app.clone();
            let result = tauri::async_runtime::spawn_blocking(move || {
                let sidecar_ref = handle.state::<EngineSidecar>();
                sidecar_ref.wait_for_health()
            }).await;

            match result {
                Ok(Ok(())) => serde_json::json!({
                    "ok": true,
                    "engine_running": true,
                    "message": "Engine restarted successfully"
                }).to_string(),
                Ok(Err(e)) => serde_json::json!({
                    "ok": false,
                    "engine_running": false,
                    "message": format!("Engine started but health check failed: {}", e)
                }).to_string(),
                Err(e) => serde_json::json!({
                    "ok": false,
                    "engine_running": false,
                    "message": format!("Health check task panicked: {}", e)
                }).to_string(),
            }
        }
        Err(e) => {
            // Return diagnostic info about what was tried
            let (program, args, wd) = sidecar.resolve_command(&app);
            serde_json::json!({
                "ok": false,
                "engine_running": false,
                "message": format!("Failed to spawn engine: {}", e),
                "diagnostics": {
                    "program": program,
                    "args": args.join(" "),
                    "working_dir": wd.map(|d| d.display().to_string()).unwrap_or_else(|| "(none)".to_string()),
                    "hint": "Make sure the engine venv exists at Documents\\CorpusMind\\engine\\.venv"
                }
            }).to_string()
        }
    }
}

/// Restart Ollama — callable from the UI "Recheck" button.
#[tauri::command]
async fn restart_ollama(app: tauri::AppHandle) -> String {
    let ollama: State<OllamaManager> = app.state();

    // Shut down any existing Ollama we started
    ollama.shutdown();
    std::thread::sleep(Duration::from_millis(500));

    // Try to start Ollama
    match ollama.start() {
        Ok(_) => {
            // Wait for ready in a blocking thread
            let handle = app.clone();
            let _ = tauri::async_runtime::spawn_blocking(move || {
                let ollama_ref = handle.state::<OllamaManager>();
                ollama_ref.wait_for_ready();
            }).await;

            // Check if it's actually running now
            let client = reqwest::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(3))
                .build();
            let running = match client {
                Ok(c) => c.get("http://127.0.0.1:11434/api/tags").send().await
                    .map(|r| r.status().is_success())
                    .unwrap_or(false),
                Err(_) => false,
            };

            let path = OllamaManager::find_ollama().unwrap_or_else(|| "not found".to_string());
            serde_json::json!({
                "ok": running,
                "ollama_running": running,
                "ollama_path": path,
                "message": if running { "Ollama started successfully" } else { "Ollama found but failed to start. Check if ollama.exe is accessible." }
            }).to_string()
        }
        Err(e) => {
            let path = OllamaManager::find_ollama().unwrap_or_else(|| "not found".to_string());
            serde_json::json!({
                "ok": false,
                "ollama_running": false,
                "ollama_path": path,
                "message": format!("Failed to start Ollama: {}", e),
                "hint": "Install Ollama from https://ollama.com and make sure it's on your PATH."
            }).to_string()
        }
    }
}

/// Check LM Studio health — callable from the UI "Recheck" button.
/// LM Studio is a GUI app with no CLI, so unlike Ollama we can't auto-start
/// it. This command just does a fresh health probe and returns the result.
/// The UI uses this to refresh the status badge after the user manually
/// starts LM Studio.
#[tauri::command]
async fn check_lmstudio() -> String {
    let client = match reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return serde_json::json!({
                "ok": false,
                "lmstudio_running": false,
                "message": format!("Failed to create HTTP client: {}", e)
            }).to_string();
        }
    };

    let urls = vec![
        "http://127.0.0.1:1234/v1/models",
        "http://localhost:1234/v1/models",
    ];

    for url in &urls {
        match client.get(*url).send().await {
            Ok(r) if r.status().is_success() => {
                info!(target: "lmstudio", "LM Studio healthy via: {}", url);
                return serde_json::json!({
                    "ok": true,
                    "lmstudio_running": true,
                    "url": url,
                    "message": "LM Studio is running"
                }).to_string();
            }
            Ok(r) => {
                warn!(target: "lmstudio", "{} returned: {}", url, r.status());
            }
            Err(e) => {
                let msg = if e.is_connect() { "Connection refused" } else { "Timeout/Network error" };
                warn!(target: "lmstudio", "{} failed: {}", url, msg);
            }
        }
    }

    serde_json::json!({
        "ok": false,
        "lmstudio_running": false,
        "message": "LM Studio is not running. Start the LM Studio desktop app and enable the local server (Developer → Start Local Server)."
    }).to_string()
}

/// Open a native file picker dialog to select a local model file (.gguf).
/// Returns the selected file path, or null if the user cancelled.
///
/// This is used by the Settings → Model Providers → Ollama → Import from file
/// flow so the user doesn't have to type the full path manually. The selected
/// path is passed to the engine's /api/v1/ollama/import endpoint, which calls
/// `ollama create <name> -f <path>` to register the model.
#[tauri::command]
async fn pick_model_file(app: tauri::AppHandle) -> String {
    use tauri_plugin_dialog::DialogExt;

    let result = app.dialog()
        .file()
        .add_filter("GGUF model files", &["gguf"])
        .add_filter("All files", &["*"])
        .blocking_pick_file();

    match result {
        Some(file_path) => {
            let path_str = file_path.to_string();
            info!(target: "dialog", "picked model file: {}", path_str);
            serde_json::json!({
                "ok": true,
                "path": path_str,
                "message": "File selected"
            }).to_string()
        }
        None => {
            serde_json::json!({
                "ok": false,
                "path": null,
                "message": "No file selected (user cancelled)"
            }).to_string()
        }
    }
}

/// Open a native file picker dialog to select multiple corpus text files.
/// Returns the selected file paths, or an empty list if the user cancelled.
///
/// Supports all common text file formats: .txt, .md, .csv, .tsv, .html, .htm,
/// .xml, .docx, .pdf, .json, .rtf, .log, .srt, .sub.
#[tauri::command]
async fn pick_corpus_files(app: tauri::AppHandle) -> String {
    use tauri_plugin_dialog::DialogExt;

    let result = app.dialog()
        .file()
        .add_filter("Text files", &["txt", "md", "csv", "tsv", "log", "srt", "sub"])
        .add_filter("Documents", &["docx", "pdf", "rtf"])
        .add_filter("Web & markup", &["html", "htm", "xml", "json"])
        .add_filter("All files", &["*"])
        .blocking_pick_files();

    match result {
        Some(paths) => {
            let path_strs: Vec<String> = paths.iter().map(|p| p.to_string()).collect();
            info!(target: "dialog", "picked {} corpus files", path_strs.len());
            serde_json::json!({
                "ok": true,
                "paths": path_strs,
                "count": path_strs.len(),
                "message": format!("{} file(s) selected", path_strs.len())
            }).to_string()
        }
        None => {
            serde_json::json!({
                "ok": false,
                "paths": [],
                "count": 0,
                "message": "No files selected (user cancelled)"
            }).to_string()
        }
    }
}

/// Read the engine's stdout and stderr log files so the UI can display
/// WHY the engine failed to start. This is the #1 diagnostic tool for
/// "engine offline" issues — the logs contain Python tracebacks, import
/// errors, port conflicts, etc.
#[tauri::command]
fn engine_logs(app: tauri::AppHandle) -> String {
    let log_path = match app.path().app_log_dir() {
        Ok(p) => p,
        Err(e) => return serde_json::json!({
            "ok": false,
            "stdout": "",
            "stderr": "",
            "message": format!("Cannot resolve log dir: {e}")
        }).to_string(),
    };

    let stdout_path = log_path.join("engine.stdout.log");
    let stderr_path = log_path.join("engine.stderr.log");

    let stdout = std::fs::read_to_string(&stdout_path).unwrap_or_default();
    let stderr = std::fs::read_to_string(&stderr_path).unwrap_or_default();

    // Truncate to last 8 KB to avoid sending megabytes to the webview
    let truncate = |s: String| -> String {
        const MAX: usize = 8 * 1024;
        if s.len() > MAX {
            let start = s.len() - MAX;
            format!("...[truncated, showing last 8KB]...\n{}", &s[start..])
        } else {
            s
        }
    };

    serde_json::json!({
        "ok": true,
        "stdout_path": stdout_path.display().to_string(),
        "stderr_path": stderr_path.display().to_string(),
        "stdout": truncate(stdout),
        "stderr": truncate(stderr),
    }).to_string()
}

/// Verify that the bundled PyInstaller sidecar binary exists in the app's
/// resources directory. This is the #1 diagnostic for "engine offline" on
/// fresh installs — if the sidecar isn't there, the installer was built
/// without it (local build script failure) and the app falls back to
/// looking for Python on the system (which usually isn't installed).
#[tauri::command]
fn verify_sidecar(app: tauri::AppHandle) -> String {
    let target = target_triple();

    let mut sidecar_found = false;
    let mut sidecar_path = String::new();
    let mut resource_dir = String::new();
    let mut layout = "none";

    if let Ok(resource) = app.path().resource_dir() {
        resource_dir = resource.display().to_string();

        // Check onedir layout first (preferred)
        let exe_name = if cfg!(windows) { "corpusmind-engine.exe" } else { "corpusmind-engine" };
        let onedir_candidate = resource.join("corpusmind-engine").join(exe_name);
        if onedir_candidate.exists() {
            sidecar_found = true;
            sidecar_path = onedir_candidate.display().to_string();
            layout = "onedir";
        }

        // Check onefile layout (legacy)
        if !sidecar_found {
            let onefile_name = if cfg!(windows) {
                format!("corpusmind-engine-{target}.exe")
            } else {
                format!("corpusmind-engine-{target}")
            };
            let onefile_candidate = resource.join(&onefile_name);
            if onefile_candidate.exists() {
                sidecar_found = true;
                sidecar_path = onefile_candidate.display().to_string();
                layout = "onefile";
            }
        }
    }

    // Also check what resolve_command would pick
    let sidecar_state: State<EngineSidecar> = app.state();
    let (program, args, wd) = sidecar_state.resolve_command(&app);

    serde_json::json!({
        "ok": sidecar_found,
        "sidecar_found": sidecar_found,
        "sidecar_path": sidecar_path,
        "resource_dir": resource_dir,
        "layout": layout,
        "target_triple": target,
        "resolved_program": program,
        "resolved_args": args.join(" "),
        "resolved_working_dir": wd.map(|d| d.display().to_string()).unwrap_or_else(|| "(none)".to_string()),
        "message": if sidecar_found {
            format!("Bundled sidecar found ({layout} layout) — engine should work.")
        } else {
            "Bundled sidecar NOT found. The installer was built without the engine embedded. Use the GitHub Actions release build, or rebuild with the full build script.".to_string()
        }
    }).to_string()
}

/// Returns the full system status: engine running? ollama running? ollama path?
#[tauri::command]
async fn system_status(app: tauri::AppHandle) -> String {
    // Check engine
    let engine_url = format!("http://{}:{}/api/v1/health", ENGINE_HOST, ENGINE_PORT);
    let engine_ok = match reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c.get(&engine_url).send().await
            .map(|r| r.status().is_success())
            .unwrap_or(false),
        Err(_) => false,
    };

    // Check Ollama
    let ollama_ok = match reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c.get("http://127.0.0.1:11434/api/tags").send().await
            .map(|r| r.status().is_success())
            .unwrap_or(false),
        Err(_) => false,
    };

    // Check LM Studio
    let lmstudio_ok = match reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c.get("http://127.0.0.1:1234/v1/models").send().await
            .map(|r| r.status().is_success())
            .unwrap_or(false),
        Err(_) => false,
    };

    // Get sidecar info
    let sidecar: State<EngineSidecar> = app.state();
    let (program, args, wd) = sidecar.resolve_command(&app);
    let wd_str = wd.map(|d| d.display().to_string()).unwrap_or_else(|| "(none)".to_string());

    // Get ollama path
    let ollama_path = OllamaManager::find_ollama().unwrap_or_else(|| "not found".to_string());

    serde_json::json!({
        "engine_running": engine_ok,
        "ollama_running": ollama_ok,
        "lmstudio_running": lmstudio_ok,
        "ollama_path": ollama_path,
        "engine_program": program,
        "engine_args": args.join(" "),
        "engine_working_dir": wd_str,
    }).to_string()
}

// ─── Unified provider health check ─────────────────────────────────
//
// The UI needs a single, authoritative source of truth for whether each
// provider (engine, Ollama, LM Studio) is reachable. Previously the UI
// relied on the engine's /api/v1/providers endpoint for Ollama + LM Studio
// health, but that creates a circular dependency: if the engine is down,
// ALL providers appear "not detected" even if they're running fine.
//
// This command checks ALL providers directly from Rust (via reqwest with
// no_proxy), giving the UI a reliable status that doesn't depend on the
// engine being up. The webview calls this on mount and polls every 5s.

/// Probe a URL with a no-proxy reqwest client. Returns Ok(()) on HTTP 2xx,
/// Err(message) on any failure.
async fn probe_url(client: &reqwest::Client, url: &str) -> Result<(), String> {
    match client.get(url).send().await {
        Ok(r) if r.status().is_success() => Ok(()),
        Ok(r) => Err(format!("HTTP {}", r.status())),
        Err(e) => {
            let msg = if e.is_connect() {
                "Connection refused".to_string()
            } else if e.is_timeout() {
                "Timeout".to_string()
            } else {
                e.to_string()
            };
            Err(msg)
        }
    }
}

/// Check ALL providers (engine + Ollama + LM Studio) from Rust in one call.
/// This is the authoritative source of truth for the UI's status badges.
///
/// Each provider is checked with .no_proxy() to bypass corporate VPNs that
/// would silently intercept loopback traffic. OLLAMA_HOST env var is
/// respected for custom Ollama configurations.
#[tauri::command]
async fn all_providers_health() -> String {
    let client = match reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return serde_json::json!({
                "engine": {"healthy": false, "error": format!("HTTP client: {e}")},
                "ollama": {"healthy": false, "error": format!("HTTP client: {e}")},
                "lmstudio": {"healthy": false, "error": format!("HTTP client: {e}")},
            }).to_string();
        }
    };

    // Engine: check /api/v1/health
    let engine_url = format!("http://{}:{}/api/v1/health", ENGINE_HOST, ENGINE_PORT);
    let engine = match probe_url(&client, &engine_url).await {
        Ok(()) => serde_json::json!({"healthy": true, "url": engine_url, "error": null}),
        Err(e) => serde_json::json!({"healthy": false, "url": engine_url, "error": e}),
    };

    // Ollama: try OLLAMA_HOST env var first, then 127.0.0.1, then localhost
    let ollama_urls = {
        let mut urls = vec![
            "http://127.0.0.1:11434/api/tags".to_string(),
            "http://localhost:11434/api/tags".to_string(),
        ];
        if let Ok(host) = std::env::var("OLLAMA_HOST") {
            let normalized = if host.starts_with("http://") || host.starts_with("https://") {
                host
            } else if host.contains(':') {
                format!("http://{}", host)
            } else {
                format!("http://{}:11434", host)
            };
            urls.insert(0, format!("{}/api/tags", normalized));
        }
        urls
    };
    let mut ollama_healthy = false;
    let mut ollama_error = "All URLs failed".to_string();
    let mut ollama_url_used = String::new();
    for url in &ollama_urls {
        match probe_url(&client, url).await {
            Ok(()) => {
                ollama_healthy = true;
                ollama_url_used = url.clone();
                ollama_error.clear();
                break;
            }
            Err(e) => {
                ollama_error = format!("{} | {}", url, e);
            }
        }
    }
    let ollama_path = OllamaManager::find_ollama().unwrap_or_else(|| "not found".to_string());
    let ollama = serde_json::json!({
        "healthy": ollama_healthy,
        "url": if ollama_healthy { ollama_url_used } else { "http://127.0.0.1:11434".to_string() },
        "error": if ollama_healthy { serde_json::Value::Null } else { serde_json::Value::String(ollama_error) },
        "path": ollama_path,
    });

    // LM Studio: check /v1/models (OpenAI-compatible)
    let lmstudio_urls = vec![
        "http://127.0.0.1:1234/v1/models".to_string(),
        "http://localhost:1234/v1/models".to_string(),
    ];
    let mut lmstudio_healthy = false;
    let mut lmstudio_error = "All URLs failed".to_string();
    let mut lmstudio_url_used = String::new();
    for url in &lmstudio_urls {
        match probe_url(&client, url).await {
            Ok(()) => {
                lmstudio_healthy = true;
                lmstudio_url_used = url.clone();
                lmstudio_error.clear();
                break;
            }
            Err(e) => {
                lmstudio_error = format!("{} | {}", url, e);
            }
        }
    }
    let lmstudio = serde_json::json!({
        "healthy": lmstudio_healthy,
        "url": if lmstudio_healthy { lmstudio_url_used } else { "http://127.0.0.1:1234/v1".to_string() },
        "error": if lmstudio_healthy { serde_json::Value::Null } else { serde_json::Value::String(lmstudio_error) },
    });

    serde_json::json!({
        "engine": engine,
        "ollama": ollama,
        "lmstudio": lmstudio,
    }).to_string()
}

pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_secs()
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .manage(EngineSidecar::new())
        .manage(OllamaManager::new())
        .setup(|app| {
            let handle = app.handle().clone();

            // Start Ollama first (blocking, but fast — just spawns a process)
            {
                let ollama: State<OllamaManager> = handle.state();
                match ollama.start() {
                    Ok(_) => {
                        // Wait for Ollama to be ready (non-blocking — spawn in thread)
                        let handle_clone = handle.clone();
                        std::thread::spawn(move || {
                            let ollama: State<OllamaManager> = handle_clone.state();
                            ollama.wait_for_ready();
                        });
                    }
                    Err(e) => {
                        warn!(target: "ollama", "could not start Ollama: {e}");
                    }
                }
            }

            // Spawn the engine in a background thread so we don't block app startup.
            tauri::async_runtime::spawn(async move {
                let sidecar: State<EngineSidecar> = handle.state();
                if let Err(e) = sidecar.spawn(&handle) {
                    error!(target: "sidecar", "spawn failed: {e}");
                    return;
                }
                let handle_for_blocking = handle.clone();
                let result = tauri::async_runtime::spawn_blocking(move || {
                    let sidecar_ref = handle_for_blocking.state::<EngineSidecar>();
                    sidecar_ref.wait_for_health()
                }).await;
                match result {
                    Ok(Ok(())) => info!(target: "sidecar", "engine ready"),
                    Ok(Err(e)) => error!(target: "sidecar", "engine not ready: {e}"),
                    Err(e) => error!(target: "sidecar", "health check task panicked: {e}"),
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let sidecar: State<EngineSidecar> = window.state();
                sidecar.shutdown();
                let ollama: State<OllamaManager> = window.state();
                ollama.shutdown();
            }
        })
        .invoke_handler(tauri::generate_handler![
            engine_health,
            sidecar_status,
            ollama_health,
            system_status,
            all_providers_health,
            restart_engine,
            restart_ollama,
            check_lmstudio,
            pick_model_file,
            pick_corpus_files,
            engine_logs,
            verify_sidecar
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Return the canonical Rust target triple for the build host.
///
/// Tauri's `externalBin` mechanism appends this triple to the binary name when
/// looking up sidecar executables (e.g. `corpusmind-engine-aarch64-apple-darwin`).
/// We hardcode the mapping instead of using `std::env::consts::{ARCH,OS,FAMILY}`
/// because those constants don't compose into a valid triple.
fn target_triple() -> &'static str {
    match (std::env::consts::ARCH, std::env::consts::OS) {
        ("aarch64", "macos") => "aarch64-apple-darwin",
        ("x86_64", "macos") => "x86_64-apple-darwin",
        ("aarch64", "linux") => "aarch64-unknown-linux-gnu",
        ("x86_64", "linux") => "x86_64-unknown-linux-gnu",
        ("x86_64", "windows") => "x86_64-pc-windows-msvc",
        ("aarch64", "windows") => "aarch64-pc-windows-msvc",
        (arch, os) => {
            // Best-effort fallback for unusual targets. This will likely not
            // match any bundled binary, but logging it here lets the dev fallback
            // take over cleanly.
            warn!(target: "sidecar", "unknown target triple for arch={arch} os={os}, sidecar lookup will fail");
            "unknown-target"
        }
    }
}
