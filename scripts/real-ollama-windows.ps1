# Real Windows CI: download SHA-pinned official Ollama CLI, run authentic GGUF.
# This downloads ~1.5GB binary + a ~400MB model ONLY on GitHub-hosted Windows.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$version = "v0.34.0"
$expectedSha = "a7dd1b174f39d3d1b8a25d4cbc86045d0e190b17187bfdcbe2f2ee3b5a11470e"
$model = "qwen2.5-coder:0.5b"
$folder = Join-Path $env:RUNNER_TEMP "jarvis-ollama-real"
$zip = Join-Path $env:RUNNER_TEMP "ollama-windows-amd64.zip"
New-Item -Force -ItemType Directory -Path $folder | Out-Null
$uri = "https://github.com/ollama/ollama/releases/download/$version/ollama-windows-amd64.zip"
Write-Host "Downloading official Ollama Windows standalone package ($version)"
Invoke-WebRequest -Uri $uri -OutFile $zip
$actualSha = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -ne $expectedSha) { throw "Ollama Windows ZIP SHA256 mismatch" }
Write-Host "Verified Ollama Windows distribution SHA256"
Expand-Archive -Path $zip -DestinationPath $folder -Force
Remove-Item $zip -Force
$exe = Get-ChildItem -Path $folder -Recurse -Filter ollama.exe | Select-Object -First 1
if (-not $exe) { throw "Ollama executable missing from verified archive" }
$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:OLLAMA_MODELS = Join-Path $env:RUNNER_TEMP "jarvis-ollama-models"
$env:OLLAMA_NO_CLOUD = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_KEEP_ALIVE = "0"
New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null
$stdout = Join-Path $env:RUNNER_TEMP "jarvis-ollama-stdout.log"
$stderr = Join-Path $env:RUNNER_TEMP "jarvis-ollama-stderr.log"
$server = Start-Process -FilePath $exe.FullName -ArgumentList "serve" -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    $up = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
            $up = $true
            break
        } catch {}
        if ($server.HasExited) { throw "Ollama server exited before startup" }
    }
    if (-not $up) { throw "Ollama server did not become ready within 180 s" }
    Write-Host "Local Ollama server available; pulling model: $model"
    & $exe.FullName pull $model
    if ($LASTEXITCODE -ne 0) { throw "Real local model download failed" }
    $env:JARVIS_LOCAL_OLLAMA_URL = "http://127.0.0.1:11434"
    $env:JARVIS_LOCAL_OLLAMA_MODEL = $model
    python jarvis-studio-backend/real_local_model_e2e.py
    if ($LASTEXITCODE -ne 0) { throw "Real local model coding E2E failed" }
} finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
