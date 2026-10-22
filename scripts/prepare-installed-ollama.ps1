param(
    [Parameter(Mandatory=$true)][string]$InstallerPath
)
# Disposable Windows CI only: real SHA-pinned Ollama v0.34.0 and Qwen2.5 0.5B.
# No paid API or cloud model; Qwen executes locally for the INSTALLED app.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or
    -not $env:RUNNER_TEMP -or -not $env:GITHUB_ENV) {
    throw "Real installed Ollama test only on disposable GitHub Windows CI"
}
$version = "v0.34.0"
$expectedSha = "a7dd1b174f39d3d1b8a25d4cbc86045d0e190b17187bfdcbe2f2ee3b5a11470e"
$model = "qwen2.5-coder:0.5b"
$root = Join-Path $env:RUNNER_TEMP "jarvis-installed-real-ollama"
$zip = Join-Path $env:RUNNER_TEMP "jarvis-official-ollama-amd64.zip"
New-Item -Path $root -ItemType Directory -Force | Out-Null
Invoke-WebRequest "https://github.com/ollama/ollama/releases/download/$version/ollama-windows-amd64.zip" -OutFile $zip
$actualSha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -cne $expectedSha) { throw "Pinned official Ollama binary SHA256 mismatch" }
Expand-Archive -LiteralPath $zip -DestinationPath $root -Force
Remove-Item $zip -Force
$exe = Get-ChildItem -LiteralPath $root -Recurse -Filter "ollama.exe" -File |
    Select-Object -First 1
if (-not $exe) { throw "Official Ollama executable missing" }

$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:OLLAMA_MODELS = Join-Path $env:RUNNER_TEMP "jarvis-installed-gguf-models"
$env:OLLAMA_NO_CLOUD = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_KEEP_ALIVE = "0"
New-Item -Path $env:OLLAMA_MODELS -ItemType Directory -Force | Out-Null
$stdOut = Join-Path $env:RUNNER_TEMP "jarvis-installed-ollama-stdout.log"
$stdErr = Join-Path $env:RUNNER_TEMP "jarvis-installed-ollama-stderr.log"
$server = Start-Process -FilePath $exe.FullName -ArgumentList "serve" -PassThru -RedirectStandardOutput $stdOut -RedirectStandardError $stdErr
$server.Id | Set-Content (Join-Path $env:RUNNER_TEMP "jarvis-installed-ollama.pid")
try {
    $online = $false
    for ($i=0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        try {
            $null = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
            $online = $true
            break
        } catch { }
        if ($server.HasExited) { throw "Official local Ollama exited before readiness" }
    }
    if (-not $online) { throw "Installed test local Ollama never became ready" }
    & $exe.FullName pull $model
    if ($LASTEXITCODE -ne 0) { throw "Real Qwen GGUF download failed" }
    $models = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
    if (-not @($models.models | Where-Object { $_.name -eq $model }).Count) {
        throw "Real Qwen model missing from local Ollama model inventory"
    }
    # Keep Ollama alive in the SAME GitHub Actions step as the full native
    # installer E2E. GITHUB_ENV carries variables, never process liveness.
    $env:JARVIS_INSTALLED_REAL_OLLAMA = "1"
    $health = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
    if (-not @($health.models | Where-Object { $_.name -eq $model }).Count) {
        throw "Ollama disappeared before installed-JARVIS native E2E"
    }
    Write-Host "PASS: verified Ollama and actual Qwen model available within E2E step."
    & (Join-Path $PSScriptRoot "validate-installer.ps1") `
        -InstallerPath $InstallerPath `
        -ReceiptPath (Join-Path $env:RUNNER_TEMP "installer-smoke-proof.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Installed GUI, Ollama, and uninstall verification returned failure"
    }
} finally {
    # Explicitly stop only the process started by this step, even on failure.
    $server.Refresh()
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
    $pidfile = Join-Path $env:RUNNER_TEMP "jarvis-installed-ollama.pid"
    Remove-Item -LiteralPath $pidfile -Force -ErrorAction SilentlyContinue
}
