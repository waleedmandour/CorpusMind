# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6).
#
# Windows twin of scripts/ci_smoke_engine.sh: launches the PyInstaller-built
# engine binary on a scratch port and asserts that the features that
# regressed in the shipped v1.2.8 actually work inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
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

Write-Host "[smoke] launching $Bin on port $Port"
$env:CORPUSMIND_PORT = "$Port"
$proc = Start-Process -FilePath $Bin -PassThru -WindowStyle Hidden

function Cleanup {
    try {
        if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    } catch { }
}

try {
    Write-Host "[smoke] waiting for /api/v1/health" -NoNewline
    $ready = $false
    foreach ($i in 1..60) {
        try {
            $null = Invoke-RestMethod -Uri "$Base/api/v1/health" -Method Get -TimeoutSec 2
            $ready = $true
            break
        } catch {
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 1
        }
    }
    Write-Host
    if (-not $ready) { throw "[smoke] FAIL: engine did not become healthy within 60s" }
    Write-Host "[smoke] engine is up"

    $res = Invoke-RestMethod -Uri "$Base/api/v1/health/resources" -Method Get
    Write-Host ("[smoke] /api/v1/health/resources -> " + ($res | ConvertTo-Json -Compress))

    if ($res.usas.en -ne $true) { throw "[smoke] FAIL: USAS en lexicon did not resolve inside the bundle: $($res.usas | ConvertTo-Json -Compress)" }
    if ($res.wordlists.awl -ne $true) { throw "[smoke] FAIL: AWL wordlist did not resolve inside the bundle" }

    $pi = $res.persuasion_index
    if (-not $pi -or $pi.installed -ne $true -or -not $pi.version) {
        throw "[smoke] FAIL: persuasion-index not installed in bundle: $($pi | ConvertTo-Json -Compress)"
    }
    Write-Host "[smoke] persuasion-index $($pi.version) present"

    $piHealth = Invoke-RestMethod -Uri "$Base/api/v1/discourse/persuasion/health" -Method Get
    Write-Host ("[smoke] /api/v1/discourse/persuasion/health -> " + ($piHealth | ConvertTo-Json -Compress))
    if ($piHealth.installed -ne $true) { throw "[smoke] FAIL: persuasion health endpoint reports the lens as not installed" }

    Write-Host "[smoke] PASS: USAS lexicon, AWL wordlist and persuasion-index all present in the bundle"
} finally {
    Cleanup
}
