# True packaged Tauri desktop + PyInstaller backend smoke on disposable Windows CI.
# May not be called on a personal desktop. Does not emulate the backend or GUI.
param(
  [Parameter(Mandatory=$true)][string]$InstallRoot,
  [string]$ReceiptPath = "$env:RUNNER_TEMP\jarvis-installed-runtime-proof.json"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "Installed runtime smoke only on disposable GitHub Windows runner"
}
$root = (Resolve-Path -LiteralPath $InstallRoot).Path
if (-not $root.StartsWith([IO.Path]::GetFullPath($env:RUNNER_TEMP),
                           [StringComparison]::OrdinalIgnoreCase)) {
    throw "Installed runtime path must be under disposable runner temp"
}
$gui = Join-Path $root "jarvis-studio-gui.exe"
if (-not (Test-Path -LiteralPath $gui -PathType Leaf)) {
    throw "The real installed Tauri executable is missing"
}
$proof = $null
$guiProcess = $null
$childId = $null
$guiAlive = $false
$backendAlive = $false
$cleanExit = $false
$started = $false
$token = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
$previousToken = $env:JARVIS_WS_TOKEN
try {
    # The GUI and its frozen backend inherit the SAME ephemeral token.
    # Never put the token on the command line, into logs or into receipts.
    $env:JARVIS_WS_TOKEN = $token
    $guiProcess = Start-Process -FilePath $gui -WorkingDirectory $root -PassThru
    $started = $true
    $deadline = (Get-Date).AddSeconds(180)
    do {
        $guiProcess.Refresh()
        if ($guiProcess.HasExited) {
            throw "Installed GUI exited prematurely with ExitCode=$($guiProcess.ExitCode)"
        }
        $children = @(
            Get-CimInstance Win32_Process -Filter "Name = 'jarvis-backend.exe'" |
            Where-Object { $_.ParentProcessId -eq $guiProcess.Id }
        )
        if ($children.Count -gt 0) {
            $childId = [int]$children[0].ProcessId
            $backendAlive = $true
        }
        $socket = [Net.Sockets.TcpClient]::new()
        try {
            $connect = $socket.ConnectAsync("127.0.0.1", 8765)
            if ($connect.Wait(450) -and $socket.Connected -and $backendAlive) {
                $guiAlive = $true
                break
            }
        } catch {
            # Startup may still be provisioning; no success claim.
        } finally {
            $socket.Dispose()
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $guiAlive -or -not $backendAlive) {
        throw "Installed GUI and its child frozen backend did not start successfully"
    }
    $probeOutput = & python scripts/probe-installed-websocket.py 2>&1
    if ($LASTEXITCODE -ne 0) {
        # Never print a bearer token; Python emits only short nonsecret errors.
        throw "Packaged backend authenticated WebSocket E2E FAILED: $($probeOutput | Select-Object -Last 1)"
    }
    $proofLine = @($probeOutput | Where-Object {
        $_ -is [string] -and $_.StartsWith("JARVIS_INSTALLED_WS_PROOF=")
    })
    if ($proofLine.Count -ne 1) { throw "Missing unique positive native WebSocket receipt" }
    $proof = $proofLine[0].Substring("JARVIS_INSTALLED_WS_PROOF=".Length) | ConvertFrom-Json
    if ($proof.status -ne "real_installed_runtime_ws_verified" -or
        $proof.negative_wrong_token_rejected -ne $true -or
        $proof.authenticated_real_sysinfo -ne $true -or
        $proof.review_without_consent_denied -ne $true -or
        $proof.ollama_gguf_execution_in_this_probe -ne $true -or
        $proof.trusted_static_zip_model_proposal -ne $true -or
        $proof.review_session_rolled_back -ne $true) {
        throw "Native WebSocket receipt did not satisfy authorization conditions"
    }
    $guiProcess.Refresh()
    if ($guiProcess.HasExited) { throw "GUI exited after WebSocket probe" }
    if (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) {
        throw "Frozen child backend exited after WebSocket probe"
    }
} finally {
    $env:JARVIS_WS_TOKEN = $previousToken
    if ($guiProcess) {
        try {
            $guiProcess.Refresh()
            if (-not $guiProcess.HasExited) {
                Stop-Process -Id $guiProcess.Id -Force -ErrorAction SilentlyContinue
                $guiProcess.WaitForExit(15000) | Out-Null
            }
            $cleanExit = $guiProcess.HasExited
        } finally { $guiProcess.Dispose() }
    }
    $backendGone = $false
    if ($childId) {
        for ($attempt = 0; $attempt -lt 12; $attempt++) {
            if (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) {
                $backendGone = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        # Job Object cleanup is not always available inside GitHub job
        # containers; preserve the failure and clean ONLY this known child.
        if (-not $backendGone) {
            Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
        }
    }
    $pass = ($started -and $guiAlive -and $backendAlive -and
        $cleanExit -and $backendGone -and $null -ne $proof)
    $receipt = [ordered]@{
        schema = "jarvis-installed-runtime-v1"
        platform = "disposable-windows-github-runner"
        launched_real_tauri_exe = [bool]$started
        gui_process_stayed_alive = [bool]$guiAlive
        child_frozen_backend_observed = [bool]$backendAlive
        backend_process_terminated_with_gui = [bool]$backendGone
        native_authenticated_websocket_verified = [bool]($proof -and $proof.authenticated_real_sysinfo)
        wrong_token_rejected = [bool]($proof -and $proof.negative_wrong_token_rejected)
        review_without_consent_denied = [bool]($proof -and $proof.review_without_consent_denied)
        ollama_gguf_tested_in_installed_process = [bool]($proof -and $proof.ollama_gguf_execution_in_this_probe)
        trusted_zip_model_review_generated = [bool]($proof -and $proof.trusted_static_zip_model_proposal)
        ephemeral_review_rolled_back = [bool]($proof -and $proof.review_session_rolled_back)
        installed_gui_dom_automated = $false
        physical_power_loss_certified = $false
        not_certified = @("full_voice_ui", "physical_power_loss", "interactive_webview_render_inspection")
        success = [bool]$pass
    }
    $receipt | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $ReceiptPath -Encoding utf8
    Write-Host "Installed runtime smoke receipt: $ReceiptPath"
}
if (-not $pass) { throw "Installed runtime end-to-end smoke FAILED" }
Write-Host "PASS: real installed GUI spawned frozen backend; native WS auth and denial verified; backend exited on GUI kill."
