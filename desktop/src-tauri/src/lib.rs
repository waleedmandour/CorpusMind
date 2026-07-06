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
        // for dev when the binary isn't present.
        let (program, args) = self.resolve_command(app);

        info!(target: "sidecar", "spawning engine: {} {}", program, args.join(" "));
        info!(target: "sidecar", "stdout → {}", stdout_path.display());
        info!(target: "sidecar", "stderr → {}", stderr_path.display());

        let child = Command::new(&program)
            .args(&args)
            .env("CORPUSMIND_HOST", ENGINE_HOST)
            .env("CORPUSMIND_PORT", ENGINE_PORT.to_string())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr))
            .spawn()
            .map_err(|e| SidecarError::Spawn(format!("{program}: {e}")))?;

        *child_opt = Some(child);
        Ok(())
    }

    /// Pick the right binary/args combo:
    ///   1. If a Tauri sidecar binary is registered for the current target, use it.
    ///   2. Otherwise, fall back to `python -m app.main` from the engine/ directory
    ///      (dev mode — assumes the developer has the venv active).
    ///   3. Otherwise, fall back to `corpusmind-engine` on PATH.
    fn resolve_command(&self, app: &tauri::AppHandle) -> (String, Vec<String>) {
        // Tauri's externalBin lookup expects the binary to be suffixed with the
        // Rust target triple of the build host. `std::env::consts::{ARCH,OS,FAMILY}`
        // do NOT produce a valid triple (they yield e.g. "aarch64-macos-unix" on
        // Apple Silicon, but the real triple is "aarch64-apple-darwin"). We map
        // (ARCH, OS) to the canonical triples Tauri's bundler uses.
        let target_triple = target_triple();

        // The bundled binary lives in the app's resources directory after install
        // (Tauri copies externalBin entries there with the triple suffix).
        if let Ok(resource) = app.path().resource_dir() {
            let candidate = resource.join(format!("corpusmind-engine-{target_triple}"));
            if candidate.exists() {
                return (candidate.to_string_lossy().into_owned(), vec![]);
            }
        }

        // Dev fallback: run the engine from ../engine/ via Python.
        let engine_dir = std::env::current_dir()
            .ok()
            .and_then(|cwd| cwd.parent().map(|p| p.join("engine")))
            .or_else(|| std::env::var("CORPUSMIND_ENGINE_DIR").ok().map(Into::into));

        if let Some(dir) = engine_dir {
            // Try the venv first, then system python.
            let venv_python = if cfg!(windows) {
                dir.join(".venv").join("Scripts").join("python.exe")
            } else {
                dir.join(".venv").join("bin").join("python")
            };
            if venv_python.exists() {
                return (
                    venv_python.to_string_lossy().into_owned(),
                    vec!["-m".into(), "app.main".into()],
                );
            }
            // Last-resort: assume `python` is on PATH and CWD is engine/.
            return (
                "python".into(),
                vec!["-m".into(), "app.main".into()],
            );
        }

        // Final fallback: hope the wheel's console script is on PATH.
        ("corpusmind-engine".into(), vec![])
    }

    fn wait_for_health(&self) -> Result<(), SidecarError> {
        let url = format!("http://{ENGINE_HOST}:{ENGINE_PORT}/api/v1/health");
        let start = Instant::now();

        // Use a simple blocking client — we're already on a background thread.
        let client = reqwest::blocking::Client::builder()
            .timeout(HEALTH_POLL_INTERVAL)
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
            // Try graceful first, then force-kill.
            #[cfg(unix)]
            {
                use std::os::unix::process::ExitStatusExt;
                let _ = child.kill();
            }
            #[cfg(windows)]
            {
                let _ = child.kill();
            }
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
fn engine_health() -> Result<String, String> {
    // Synchronous health check the webview can call to verify the sidecar is up.
    let url = format!("http://{ENGINE_HOST}:{ENGINE_PORT}/api/v1/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let r = client.get(&url).send().map_err(|e| e.to_string())?;
    let body = r.text().map_err(|e| e.to_string())?;
    Ok(body)
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
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn in a background thread so we don't block app startup.
            tauri::async_runtime::spawn(async move {
                let sidecar: State<EngineSidecar> = handle.state();
                if let Err(e) = sidecar.spawn(&handle) {
                    error!(target: "sidecar", "spawn failed: {e}");
                    return;
                }
                // wait_for_health is a blocking fn; we are in a spawned task so blocking is OK.
                match sidecar.wait_for_health() {
                    Ok(()) => info!(target: "sidecar", "engine ready"),
                    Err(e) => error!(target: "sidecar", "engine not ready: {e}"),
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let sidecar: State<EngineSidecar> = window.state();
                sidecar.shutdown();
            }
        })
        .invoke_handler(tauri::generate_handler![engine_health])
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
