; Custom NSIS installer hooks for CorpusMind (Tauri v2).
;
; WHY THIS EXISTS
; The app ships a Python engine sidecar (corpusmind-engine.exe) that runs as
; a child process of the desktop shell. The stock Tauri NSIS template only
; stops the MAIN executable (corpusmind-desktop.exe) before copying files —
; it does NOT know about the sidecar. If the engine process is still alive
; (app crashed, force-closed from Task Manager, or the child outlived its
; parent), Windows locks corpusmind-engine\*.exe and the installer/upgrade
; fails with "Error opening file for writing".
;
; These hooks stop BOTH processes (tree-kill) before any file operation and
; give Defender a moment to release freshly-scanned handles.
;
; NOTE: both CorpusMind and CorpusMind Lens ship a sidecar with the same
; image name (corpusmind-engine.exe) and share port 8765. Killing it here is
; intentional: an in-flight engine must be replaced atomically, and the next
; app to start simply spawns (or reuses) a fresh engine.
;
; CADDY (v1.2.12): the engine runs its classroom reverse proxy from
; _internal\caddy\caddy.exe and normally ties it to the engine's lifetime
; with a Job Object. That tie can fail silently (job-assignment error,
; engine hard-killed before the job existed, pre-Job-Object installs) and
; leaves an orphaned caddy.exe holding a write-lock on the very file the
; installer must replace — the upgrade or uninstall then dies with
; "Error opening file for writing". Kill it by image name as well; the next
; classroom start respawns a fresh Caddy. Same accepted trade-off as above:
; any other app on this machine that bundles a caddy.exe under this name is
; stopped too.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running CorpusMind processes..."
  nsExec::Exec 'taskkill /F /T /IM corpusmind-engine.exe'
  nsExec::Exec 'taskkill /F /T /IM corpusmind-desktop.exe'
  ; orphan sweep: caddy.exe may have outlived the engine (see note above)
  nsExec::Exec 'taskkill /F /T /IM caddy.exe'
  Sleep 800
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping any running CorpusMind processes..."
  nsExec::Exec 'taskkill /F /T /IM corpusmind-engine.exe'
  nsExec::Exec 'taskkill /F /T /IM corpusmind-desktop.exe'
  ; orphan sweep: caddy.exe may have outlived the engine (see note above)
  nsExec::Exec 'taskkill /F /T /IM caddy.exe'
  Sleep 800
!macroend
