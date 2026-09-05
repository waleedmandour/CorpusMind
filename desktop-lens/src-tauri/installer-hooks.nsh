; Custom NSIS installer hooks for CorpusMind Lens (Tauri v2).
;
; WHY THIS EXISTS
; The app ships a Python engine sidecar (corpusmind-engine.exe) that runs as
; a child process of the desktop shell. The stock Tauri NSIS template only
; stops the MAIN executable (corpusmind-lens.exe) before copying files — it
; does NOT know about the sidecar. If the engine process is still alive
; (app crashed, force-closed from Task Manager, or the child outlived its
; parent), Windows locks corpusmind-engine\*.exe and the installer/upgrade
; fails with "Error opening file for writing".
;
; NOTE: both CorpusMind and CorpusMind Lens ship a sidecar with the same
; image name (corpusmind-engine.exe) and share port 8765. Killing it here is
; intentional: an in-flight engine must be replaced atomically, and the next
; app to start simply spawns (or reuses) a fresh engine.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running CorpusMind Lens processes..."
  nsExec::Exec 'taskkill /F /T /IM corpusmind-engine.exe'
  nsExec::Exec 'taskkill /F /T /IM corpusmind-lens.exe'
  Sleep 800
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping any running CorpusMind Lens processes..."
  nsExec::Exec 'taskkill /F /T /IM corpusmind-engine.exe'
  nsExec::Exec 'taskkill /F /T /IM corpusmind-lens.exe'
  Sleep 800
!macroend
