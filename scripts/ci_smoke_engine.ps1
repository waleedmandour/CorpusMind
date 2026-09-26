# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6).
#
# Windows twin of scripts/ci_smoke_engine.sh: launches the PyInstaller-built
# engine binary on a scratch port and asserts that the features that
# regressed in the shipped v1.2.8 actually work inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
#
# Windows-runner hardening (first failed gate, 2026-09-26): polls with
# curl.exe (Invoke-RestMethod pays multi-second proxy overhead per call on
# the runners), watches the process so an early crash fails fast with its
# exit code instead of burning the whole budget, and allows 240s because
# the first Defender scan of a freshly built ~1.5GB onedir bundle delays
# the first boot by minutes.
#
# The release workflow runs this BEFORE the Tauri packaging step; a failure
# fails the release. Usage:
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
    # curl.exe ships with the runner images and ignores the runner's HTTP
    # proxy settings for loopback, unlike Invoke-RestMethod.
    & curl.exe -fsS --noproxy "*" --max-time 3 "$Base/api/v1/health" 2>$null
    return ($LASTEXITCODE -eq 0)
}

try {
    $started = Get-Date
    Write-Host "[smoke] waiting for /api/v1/health (budget ${BudgetSeconds}s)"
    $ready = $false
    while (((Get-Date) - $started).TotalSeconds -lt $BudgetSeconds) {
        if ($proc.HasExited) {
            throw ("[smoke] FAIL: engine exited early with code " + $proc.ExitCode +
                   " after " + [int]((Get-Date) - $started).TotalSeconds + "s")
        }
        if (Poll-Health) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host "[smoke] health poll elapsed: ${elapsed}s"
    if (-not $ready) {
        if ($proc.HasExited) {
            throw ("[smoke] FAIL: engine exited early with code " + $proc.ExitCode)
        }
        throw "[smoke] FAIL: engine did not become healthy within ${BudgetSeconds}s"
    }
    Write-Host "[smoke] engine is up"

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
