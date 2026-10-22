# Build the JARVIS Windows installer (NSIS) with bundled Python backend.
# Prerequisites: Python 3.11+, Node.js 20+, Rust, WebView2 runtime.
# Usage: .\scripts\build.ps1 [-Lean]  (Lean skips heavy offline assets for smoke builds)

param(
    [switch]$Lean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Gui  = Join-Path $Root "jarvis-studio-gui"

Write-Host "JARVIS release build" -ForegroundColor Cyan

if ($Lean) {
    & (Join-Path $Root "scripts\package-backend.ps1") -Lean
} else {
    & (Join-Path $Root "scripts\package-backend.ps1")
}
if ($LASTEXITCODE -ne 0) { throw "Backend packaging exited $LASTEXITCODE" }
$Frozen = Join-Path $Root "jarvis-studio-gui\src-tauri\resources\jarvis-backend\jarvis-backend.exe"
if (-not (Test-Path -LiteralPath $Frozen -PathType Leaf)) { throw "Missing frozen jarvis-backend.exe" }

Push-Location $Gui
try {
    if (-not (Test-Path "node_modules")) {
        npm ci
    }
    npm run tauri:build
    if ($LASTEXITCODE -ne 0) { throw "Tauri installer build exited $LASTEXITCODE" }
} finally {
    Pop-Location
}

$Bundle = Join-Path $Gui "src-tauri\target\release\bundle\nsis"
if ((Test-Path $Bundle) -and @(Get-ChildItem $Bundle -Filter "*.exe" -File).Count -eq 1) {
    Write-Host "`nInstaller output:" -ForegroundColor Green
    Get-ChildItem $Bundle -Filter "*.exe" | ForEach-Object { Write-Host "  $($_.FullName)" }
} else {
    throw "Expected exactly one NSIS installer in $Bundle; build failed or ambiguous output."
}

Write-Host "`nThe NSIS installer includes JARVIS.exe and the frozen jarvis-backend folder."
Write-Host "Users only need API keys at first launch - no Python install required."
