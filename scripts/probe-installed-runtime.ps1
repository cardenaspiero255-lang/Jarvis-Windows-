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
$previousWebViewFlags = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
$previousWebViewData = $env:WEBVIEW2_USER_DATA_FOLDER
$uiVerified = $false
$webviewProbeFailed = $true
$websocketProbeFailed = $true
$webviewFailureCode = "not_started"
$websocketFailureCode = "not_started"
$uiScreenshot = Join-Path $env:RUNNER_TEMP "jarvis-installed-webview.png"
$cdpPolicyKey = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"
$cdpPolicyName = "jarvis-studio-gui.exe"
$cdpPolicyInstalled = $false
$cdpPolicyCreatedKey = $false
$cdpPolicyRestored = $true
$cdpPolicyMode = "non_elevated_env"
try {
    # The GUI and its frozen backend inherit the SAME ephemeral token.
    # Never put the token on the command line, into logs or into receipts.
    $env:JARVIS_WS_TOKEN = $token
    # Remote CDP inspection is enabled *only* for this disposable runner
    # and is inherited by the test-created WebView2 child process.
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1"
    $env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $env:RUNNER_TEMP ("jarvis-ci-webview2-" + [Guid]::NewGuid().ToString("N"))
    # WebView2 Runtime 150+ ignores WEBVIEW2_* debug flags for elevated hosts.
    # Apply the Microsoft-documented app-specific HKLM override on this
    # disposable CI runner only. It is never added to a shipped binary.
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    $isElevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isElevated) {
        $cdpPolicyMode = "temporary_hklm_exact_executable"
        if (-not (Test-Path -LiteralPath $cdpPolicyKey)) {
            New-Item -Path $cdpPolicyKey -Force -ErrorAction Stop | Out-Null
            $cdpPolicyCreatedKey = $true
        }
        $existing = Get-ItemProperty -Path $cdpPolicyKey -Name $cdpPolicyName -ErrorAction SilentlyContinue
        if ($null -ne $existing) { throw "Refusing to override existing WebView2 debugging policy" }
        New-ItemProperty -Path $cdpPolicyKey -Name $cdpPolicyName -PropertyType String -Value "--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1" -ErrorAction Stop | Out-Null
        $cdpPolicyInstalled = $true
        Write-Host "CDP test: per-executable HKLM WebView2 policy enabled on disposable runner."
    } else {
        Write-Host "CDP test: non-elevated WebView2 env flags."
    }
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
    # Independently report both real installed subsystems. A broken WebView2
    # must NEVER skip native WebSocket/Qwen/rollback verification or be marked PASS.
    $webviewProbeFailed = $false
    $websocketProbeFailed = $false
    $webviewFailureCode = "none"
    $websocketFailureCode = "none"
    # Secret-free JSON is also preserved by the installer workflow.
    $real_installed_ui_diagnostic = Join-Path $env:RUNNER_TEMP "jarvis-installed-ui-diagnostic.json"

    try {
        $webviewOutput = @(& python scripts/probe-installed-webview.py 2>&1)
        $uiExitCode = $LASTEXITCODE
        if ($uiExitCode -ne 0) {
            throw "webview_probe_failed"
        }
        $webviewLine = @($webviewOutput | Where-Object {
            $_ -is [string] -and $_.StartsWith("PLAYWRIGHT_INSTALLED_UI_PROOF=")
        })
        if ($webviewLine.Count -ne 1) { throw "webview_receipt_missing" }
        $uiProof = $webviewLine[0].Substring("PLAYWRIGHT_INSTALLED_UI_PROOF=".Length) | ConvertFrom-Json
        if ($uiProof.status -ne "real_installed_webview2_ui_verified" -or
            $uiProof.repo_zip_dialog_opened_and_closed -ne $true -or
            $uiProof.settings_opened_by_real_click -ne $true) {
            throw "webview_receipt_incomplete"
        }
        $uiVerified = $true
    } catch {
        $webviewProbeFailed = $true
        $webviewFailureCode = "webview_probe_failed"
        if (Test-Path -LiteralPath $real_installed_ui_diagnostic -PathType Leaf) {
            try {
                $uiDiagnostic = Get-Content -LiteralPath $real_installed_ui_diagnostic -Raw | ConvertFrom-Json
                if ($uiDiagnostic.success -eq $false) {
                    $webviewFailureCode = "stage=$($uiDiagnostic.stage);exception=$($uiDiagnostic.error_type)"
                    $cdp = $uiDiagnostic.cdp_http_diagnostics
                    if ($cdp) {
                        $webviewFailureCode += ";cdp_version=$($cdp.cdp_version_http);targets=$($cdp.cdp_target_count);http_failure=$($cdp.version_error_type)"
                    }
                }
            } catch {
                $webviewFailureCode = "webview_diagnostic_unreadable"
            }
        }
        Write-Host "FAIL installed WebView2: $webviewFailureCode; preserved independent diagnostic."
    }

    try {
        $probeOutput = @(& python scripts/probe-installed-websocket.py 2>&1)
        $wsExitCode = $LASTEXITCODE
        if ($wsExitCode -ne 0) {
            $nativeDiagnostic = @($probeOutput | Where-Object {
                $_ -is [string] -and $_.StartsWith("JARVIS_INSTALLED_WS_FAIL=")
            })
            # Only expose a bounded exception TYPE, never network URL/bearer.
            $code = "unknown"
            if ($nativeDiagnostic.Count -gt 0 -and
                $nativeDiagnostic[-1] -match '^JARVIS_INSTALLED_WS_FAIL=([A-Za-z_][A-Za-z0-9_]*)') {
                $code = $Matches[1]
            }
            throw "websocket_probe_failed:$code"
        }
        $proofLine = @($probeOutput | Where-Object {
            $_ -is [string] -and $_.StartsWith("JARVIS_INSTALLED_WS_PROOF=")
        })
        if ($proofLine.Count -ne 1) { throw "websocket_receipt_missing" }
        $proof = $proofLine[0].Substring("JARVIS_INSTALLED_WS_PROOF=".Length) | ConvertFrom-Json
        if ($proof.status -ne "real_installed_runtime_ws_verified" -or
            $proof.negative_wrong_token_rejected -ne $true -or
            $proof.negative_forged_gui_origin_rejected -ne $true -or
            $proof.authenticated_real_sysinfo -ne $true -or
            $proof.review_without_consent_denied -ne $true -or
            $proof.ollama_gguf_execution_in_this_probe -ne $true -or
            $proof.trusted_static_zip_model_proposal -ne $true -or
            $proof.approved_copy_hash_matched -ne $true -or
            $proof.reviewed_zip_export_hash_matched -ne $true -or
            $proof.review_session_rolled_back -ne $true) {
            throw "websocket_receipt_incomplete"
        }
    } catch {
        $websocketProbeFailed = $true
        $websocketFailureCode = "websocket_probe_failed"
        $safeMessage = [string]$_.Exception.Message
        if ($safeMessage -match '^websocket_(probe_failed|receipt_missing|receipt_incomplete)(:[A-Za-z_][A-Za-z0-9_]*)?$') {
            $websocketFailureCode = $safeMessage
        }
        Write-Host "FAIL installed authenticated WebSocket/Qwen: $websocketFailureCode"
    }

    $guiProcess.Refresh()
    if ($guiProcess.HasExited) { throw "GUI exited after WebSocket probe" }
    if (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) {
        throw "Frozen child backend exited after WebSocket probe"
    }
} finally {
    $env:JARVIS_WS_TOKEN = $previousToken
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $previousWebViewFlags
    $env:WEBVIEW2_USER_DATA_FOLDER = $previousWebViewData
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
    # Restore only our own temporary CDP registry value, and verify it is gone.
    # Do not report success merely because Remove-ItemProperty returned.
    $cdpPolicyCleanupErrorType = "none"
    $cdpPolicyValueAbsentVerified = $false
    try {
        if ($cdpPolicyInstalled) {
            Remove-ItemProperty -Path $cdpPolicyKey -Name $cdpPolicyName -ErrorAction Stop
            $cdpPolicyInstalled = $false
        }
        if (Test-Path -LiteralPath $cdpPolicyKey) {
            $remaining = Get-ItemProperty -Path $cdpPolicyKey -Name $cdpPolicyName -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                throw "Temporary WebView2 per-executable policy was not removed"
            }
        }
        $cdpPolicyValueAbsentVerified = $true
        if ($cdpPolicyCreatedKey -and (Test-Path -LiteralPath $cdpPolicyKey)) {
            $key = Get-Item -Path $cdpPolicyKey -ErrorAction Stop
            if (@($key.GetValueNames()).Count -ne 0 -or $key.SubKeyCount -ne 0) {
                throw "Temporary WebView2 policy key unexpectedly contains other policy data"
            }
            Remove-Item -Path $cdpPolicyKey -ErrorAction Stop
            if (Test-Path -LiteralPath $cdpPolicyKey) {
                throw "Temporary WebView2 policy key still exists"
            }
        }
        $cdpPolicyRestored = $true
    } catch {
        $cdpPolicyRestored = $false
        $cdpPolicyCleanupErrorType = $_.Exception.GetType().Name
        Write-Host "FAIL: WebView2 ephemeral CDP policy cleanup was not verified (type=$cdpPolicyCleanupErrorType)."
    }
    $pass = ($started -and $guiAlive -and $backendAlive -and
        $cleanExit -and $backendGone -and $uiVerified -and $null -ne $proof -and
        $cdpPolicyRestored)
    $receipt = [ordered]@{
        schema = "jarvis-installed-runtime-v1"
        platform = "disposable-windows-github-runner"
        launched_real_tauri_exe = [bool]$started
        gui_process_stayed_alive = [bool]$guiAlive
        child_frozen_backend_observed = [bool]$backendAlive
        backend_process_terminated_with_gui = [bool]$backendGone
        native_authenticated_websocket_verified = [bool]($proof -and $proof.authenticated_real_sysinfo)
        installed_webview_ui_verified = [bool]$uiVerified
        webview2_cdp_mode = $cdpPolicyMode
        webview2_temporary_policy_restored = [bool]$cdpPolicyRestored
        cdp_policy_cleanup_error_type = $cdpPolicyCleanupErrorType
        cdp_policy_value_absent_verified = [bool]$cdpPolicyValueAbsentVerified
        webview_probe_failed = [bool]$webviewProbeFailed
        websocket_probe_failed = [bool]$websocketProbeFailed
        webview_probe_failure_code = $webviewFailureCode
        websocket_probe_failure_code = $websocketFailureCode
        installed_ui_diagnostic_receipt = "jarvis-installed-ui-diagnostic.json"
        installed_webview_screenshot_available = (Test-Path -LiteralPath $uiScreenshot -PathType Leaf)
        wrong_token_rejected = [bool]($proof -and $proof.negative_wrong_token_rejected)
        forged_gui_origin_without_token_rejected = [bool]($proof -and $proof.negative_forged_gui_origin_rejected)
        review_without_consent_denied = [bool]($proof -and $proof.review_without_consent_denied)
        ollama_gguf_tested_in_installed_process = [bool]($proof -and $proof.ollama_gguf_execution_in_this_probe)
        trusted_zip_model_review_generated = [bool]($proof -and $proof.trusted_static_zip_model_proposal)
        ephemeral_review_rolled_back = [bool]($proof -and $proof.review_session_rolled_back)
        approved_copy_hash_matched = [bool]($proof -and $proof.approved_copy_hash_matched)
        exported_reviewed_zip_hash_matched = [bool]($proof -and $proof.reviewed_zip_export_hash_matched)
        installed_gui_dom_automated = $false
        physical_power_loss_certified = $false
        not_certified = @("physical_microphone_and_wake_word", "physical_power_loss", "signed_installer")
        success = [bool]$pass
    }
    $receipt | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $ReceiptPath -Encoding utf8
    Write-Host "Installed runtime smoke receipt: $ReceiptPath"
}
if (-not $pass) { throw "Installed runtime end-to-end smoke FAILED (WebView2=$webviewFailureCode; WebSocket=$websocketFailureCode)" }
Write-Host "PASS: real installed GUI spawned frozen backend; native WS auth and denial verified; backend exited on GUI kill."
