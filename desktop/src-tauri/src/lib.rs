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

        // 2. Check common Windows install locations
        #[cfg(windows)]
        {
            let mut locations: Vec<String> = Vec::new();
            if let Ok(la) = std::env::var("LOCALAPPDATA") {
                locations.push(format!("{}\\Programs\\Ollama\\ollama.exe", la));
            }
            if let Ok(pf) = std::env::var("PROGRAMFILES") {
                locations.push(format!("{}\\Ollama\\ollama.exe", pf));
            }
            if let Ok(pf86) = std::env::var("PROGRAMFILES(X86)") {
                locations.push(format!("{}\\Ollama\\ollama.exe", pf86));
            }
            for loc in &locations {
                if std::path::Path::new(loc).exists() {
                    return Some(loc.clone());
                }
            }
        }

        // 3. Check macOS install location
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
        }

        None
    }

    /// Check if Ollama is already running by trying to reach /api/tags.
    async fn is_running() -> bool {
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(3))
            .build();
        if let Ok(c) = client {
            for url in &["http://127.0.0.1:11434/api/tags", "http://localhost:11434/api/tags"] {
                if let Ok(r) = c.get(url).send().await {
                    if r.status().is_success() {
                        return true;
                    }
                }
            }
        }
        false
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
        let child = Command::new(&ollama_exe)
            .arg("serve")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
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
        }

        let child = cmd.spawn()
            .map_err(|e| SidecarError::Spawn(format!("{program}: {e}")))?;

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

        // 1. The bundled binary lives in the app's resources directory after install
        //    (Tauri copies externalBin entries there with the triple suffix).
        if let Ok(resource) = app.path().resource_dir() {
            let candidate = resource.join(format!("corpusmind-engine-{target_triple}"));
            if candidate.exists() {
                info!(target: "sidecar", "found bundled sidecar binary: {}", candidate.display());
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
                #[cfg(windows)]
                {
                    std::env::var("USERPROFILE").ok()
                        .map(|home| std::path::PathBuf::from(home).join("Documents").join("CorpusMind").join("engine"))
                        .filter(|d| d.exists())
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
            // Last-resort: assume `python` is on PATH and CWD is engine/.
            warn!(target: "sidecar", "venv python not found in {}, trying system python", dir.display());
            return (
                "python".into(),
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

    // Get sidecar info
    let sidecar: State<EngineSidecar> = app.state();
    let (program, args, wd) = sidecar.resolve_command(&app);
    let wd_str = wd.map(|d| d.display().to_string()).unwrap_or_else(|| "(none)".to_string());

    // Get ollama path
    let ollama_path = OllamaManager::find_ollama().unwrap_or_else(|| "not found".to_string());

    serde_json::json!({
        "engine_running": engine_ok,
        "ollama_running": ollama_ok,
        "ollama_path": ollama_path,
        "engine_program": program,
        "engine_args": args.join(" "),
        "engine_working_dir": wd_str,
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
                    Ok(true) => {
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
        .invoke_handler(tauri::generate_handler![engine_health, sidecar_status, ollama_health, system_status])
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
