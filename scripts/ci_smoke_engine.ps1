# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6).
#
# Windows twin of scripts/ci_smoke_engine.sh: launches the PyInstaller-built
# engine binary on a scratch port and asserts that the features that
# regressed in the shipped v1.2.8 actually work inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
#
# Windows-runner hardening history:
#   1. Invoke-RestMethod paid multi-second proxy overhead per poll ->
#      poll with curl.exe --noproxy.
#   2. First-boot Defender scan of a fresh onedir bundle delayed boot ->
#      dedicated warm-up step in the workflow.
#   3. The engine process stayed alive but never bound the port and never
#      exited - the windowed bootloader swallows ALL output, so a boot-time
#      crash showed up as a WER dialog keeping the process "alive". The
#      workflow now disables the WER UI (crashes exit and yield codes) and
#      this script dumps the engine's file log (data_dir/logs/engine.log)
#      plus netstat on failure. It also probes the default port 8765 as a
#      fallback in case CORPUSMIND_PORT did not propagate.
#
# Usage:
#   powershell -File scripts/ci_smoke_engine.ps1 -Bin <path-to-engine.exe>

param(
    [Parameter(Mandatory = $true)]
    [string]$Bin
)

$ErrorActionPreference = "Stop"
$Port = if ($env:CORPUSMIND_SMOKE_PORT) { [int]$env:CORPUSMIND_SMOKE_PORT } else { 8799 }
$Base = "http://127.0.0.1:$Port"
$BudgetSeconds = 240

Write-Host "[smoke] launching $Bin on port $Port"
$env:CORPUSMIND_PORT = "$Port"
$proc = Start-Process -FilePath $Bin -PassThru -WindowStyle Hidden

function Cleanup {
    try {
        if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    } catch { }
}

function Poll-Health {
    param([string]$Url)
    & curl.exe -fsS --noproxy "*" --max-time 3 "$Url/api/v1/health" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Dump-Diagnostics {
    Write-Host "[smoke] --- diagnostics ---"
    Write-Host ("[smoke] process alive: " + (-not $proc.HasExited))
    if ($proc.HasExited) { Write-Host ("[smoke] exit code: " + $proc.ExitCode) }
    try {
        $net = & netstat -ano | Select-String -Pattern "(:$Port|:8765)\s"
        if ($net) { $net | ForEach-Object { Write-Host "[smoke] netstat: $_" } }
        else { Write-Host "[smoke] netstat: nothing listening on $Port or 8765" }
    } catch { Write-Host "[smoke] netstat failed: $_" }
    $engineLog = Join-Path $env:USERPROFILE ".corpusmind\logs\engine.log"
    if (Test-Path $engineLog) {
        Write-Host "[smoke] --- engine.log tail ---"
        Get-Content $engineLog -Tail 40 | ForEach-Object { Write-Host "[smoke] $_" }
    } else {
        Write-Host "[smoke] no engine.log at $engineLog"
    }
}

try {
    $started = Get-Date
    Write-Host "[smoke] waiting for /api/v1/health (budget ${BudgetSeconds}s)"
    $ready = $false
    while (((Get-Date) - $started).TotalSeconds -lt $BudgetSeconds) {
        if ($proc.HasExited) {
            Dump-Diagnostics
            throw ("[smoke] FAIL: engine exited early with code " + $proc.ExitCode +
                   " after " + [int]((Get-Date) - $started).TotalSeconds + "s")
        }
        if (Poll-Health $Base) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        # Fallback: maybe CORPUSMIND_PORT did not propagate and the engine
        # is serving on its default port. If so, adopt it for the checks.
        if (Poll-Health "http://127.0.0.1:8765") {
            Write-Host "[smoke] WARNING: engine answered on default port 8765, not $Port - adopting 8765"
            $Base = "http://127.0.0.1:8765"
            $ready = $true
        }
    }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host "[smoke] health poll elapsed: ${elapsed}s"
    if (-not $ready) {
        Dump-Diagnostics
        if ($proc.HasExited) {
            throw ("[smoke] FAIL: engine exited early with code " + $proc.ExitCode)
        }
        throw "[smoke] FAIL: engine did not become healthy within ${BudgetSeconds}s"
    }
    Write-Host "[smoke] engine is up (against $Base)"

    $resJson = & curl.exe -fsS --noproxy "*" "$Base/api/v1/health/resources"
    $res = $resJson | ConvertFrom-Json
    Write-Host ("[smoke] /api/v1/health/resources -> " + ($resJson -join ""))

    if ($res.usas.en -ne $true) { throw "[smoke] FAIL: USAS en lexicon did not resolve inside the bundle: $($resJson -join '')" }
    if ($res.wordlists.awl -ne $true) { throw "[smoke] FAIL: AWL wordlist did not resolve inside the bundle" }

    $pi = $res.persuasion_index
    if (-not $pi -or $pi.installed -ne $true -or -not $pi.version) {
        throw "[smoke] FAIL: persuasion-index not installed in bundle: $($resJson -join '')"
    }
    Write-Host "[smoke] persuasion-index $($pi.version) present"

    $piHealth = (& curl.exe -fsS --noproxy "*" "$Base/api/v1/discourse/persuasion/health") | ConvertFrom-Json
    if ($piHealth.installed -ne $true) { throw "[smoke] FAIL: persuasion health endpoint reports the lens as not installed" }

    Write-Host "[smoke] PASS: USAS lexicon, AWL wordlist and persuasion-index all present in the bundle"
} finally {
    Cleanup
}
