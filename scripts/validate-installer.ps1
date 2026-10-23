# NSIS installer acceptance on a DISPOSABLE GitHub-hosted Windows runner.
# Runs the actual untrusted? NO: only JARVIS built by this repository.
# Never run on the user's personal Windows installation without consent.
param(
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [string]$ReceiptPath = "$env:RUNNER_TEMP\installer-smoke-proof.json"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-BoundedProcess([string]$Exe, [string[]]$Arguments, [int]$Seconds=180) {
    $job = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru -WindowStyle Hidden
    try {
        if (-not $job.WaitForExit($Seconds * 1000)) {
            $job.Kill()
            throw "installer/uninstaller timed out"
        }
        if ($job.ExitCode -ne 0) {
            throw "installer/uninstaller nonzero ExitCode=$($job.ExitCode)"
        }
        return [int]$job.ExitCode
    } finally {
        $job.Dispose()
    }
}

if (-not $env:GITHUB_ACTIONS -or $env:GITHUB_ACTIONS -ne 'true' -or
    -not $env:RUNNER_TEMP -or -not $env:RUNNER_OS -or $env:RUNNER_OS -ne 'Windows') {
    Throw "Installer smoke runs only on a disposable GitHub Actions Windows runner."
}
$Installer = (Resolve-Path -LiteralPath $InstallerPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf) -or
    [IO.Path]::GetExtension($Installer).ToLowerInvariant() -ne ".exe") {
    Throw "A single authentic NSIS .exe installer is required."
}
$length = (Get-Item -LiteralPath $Installer).Length
if ($length -lt 100000) { Throw "NSIS setup is too small to contain the app." }
$hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()

# NSIS /D must be last and unquoted; reject whitespace and unexpected paths.
$root = Join-Path $env:RUNNER_TEMP ("JARVIS-Smoke-" + [Guid]::NewGuid().ToString("N"))
if ($root -match '\s') { Throw "NSIS smoke install path cannot contain whitespace" }
$installed = $false
$uninstalled = $false
$runtimePresent = $false
$backendPresent = $false
$installerExitCode = -1
$uninstallerExitCode = -1
$installedRuntimeVerified = $false
$runtimeProofPath = Join-Path $env:RUNNER_TEMP "jarvis-installed-runtime-proof.json"
$uninstallPath = $null
$installedLocation = $null
$uninstallRegistry = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$beforeKeys = @(Get-ChildItem -Path $uninstallRegistry -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty PSChildName)
try {
    $installerExitCode = Invoke-BoundedProcess $Installer @("/S", "/D=$root") 180
    # The Tauri product title is "JARVIS", but Cargo actually emits
    # jarvis-studio-gui.exe. Do not assume productName renames the binary.
    $expectedGuiName = "jarvis-studio-gui.exe"
    $deadline = (Get-Date).AddSeconds(25)
    do {
        $registrations = @(
            Get-ChildItem -Path $uninstallRegistry -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -notin $beforeKeys } |
            ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue } |
            Where-Object { $_.DisplayName -like "JARVIS*" }
        )
        # Tauri NSIS currentUser can install to LocalAppData. /D is preferred,
        # but the actual location must be learned from the installed files and
        # the new uninstall registry entry (not guessed from display name).
        $paths = @($root, (Join-Path $env:LOCALAPPDATA "JARVIS"))
        $paths += @($registrations | ForEach-Object { $_.InstallLocation } |
            Where-Object { $_ -is [string] -and $_.Length -gt 0 })
        foreach ($candidate in ($paths | Select-Object -Unique)) {
            $guiCandidate = Join-Path $candidate $expectedGuiName
            if (-not (Test-Path -LiteralPath $guiCandidate -PathType Leaf)) { continue }
            $installedLocation = $candidate
            $gui = $guiCandidate
            $runtimePresent = $true
            $backendCandidates = @(
                (Join-Path $candidate "jarvis-backend\jarvis-backend.exe"),
                (Join-Path $candidate "resources\jarvis-backend\jarvis-backend.exe")
            )
            $backendPresent = @($backendCandidates | Where-Object {
                Test-Path -LiteralPath $_ -PathType Leaf
            }).Count -gt 0
            if ($backendPresent) { break }
        }
        if ($runtimePresent -and $backendPresent) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $runtimePresent -or -not $backendPresent) {
        Write-Host "Installer diagnostics (no success claimed): expected binary $expectedGuiName"
        Write-Host "Proposed /D location: $root"
        Write-Host "New JARVIS uninstall entries: $($registrations.Count)"
        foreach ($entry in $registrations) {
            Write-Host "Registry InstallLocation: $($entry.InstallLocation)"
        }
        if (Test-Path -LiteralPath $root) {
            Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue |
                Select-Object -First 12 -ExpandProperty Name | ForEach-Object { Write-Host "File: $_" }
        }
        Throw "NSIS did not install the real Tauri binary and frozen Python backend."
    }
    Write-Host "Discovered installed location: $installedLocation"
    $uninstaller = @(Get-ChildItem -LiteralPath $installedLocation -File |
        Where-Object { $_.Name -match '^(?i:uninstall|unins.*)\.exe$' })
    if ($uninstaller.Count -ne 1) {
        Throw "Exactly one NSIS uninstall executable is required."
    }
    $uninstallPath = $uninstaller[0].FullName
    # A valid installer is NOT sufficient without launching its bundled GUI.
    # Uninstall still required after runtime verification failure: we must not
    # leave the disposable Windows runner with an incompletely tested package.
    $installedRuntimeError = "none"
    try {
        & (Join-Path $PSScriptRoot "probe-installed-runtime.ps1") `
            -InstallRoot $installedLocation -ReceiptPath $runtimeProofPath
        if (-not (Test-Path -LiteralPath $runtimeProofPath -PathType Leaf)) {
            throw "Missing installed runtime receipt"
        }
        $runtimeReceipt = Get-Content -LiteralPath $runtimeProofPath -Raw | ConvertFrom-Json
        if ($runtimeReceipt.success -ne $true -or
            $runtimeReceipt.installed_webview_ui_verified -ne $true -or
            $runtimeReceipt.ollama_gguf_tested_in_installed_process -ne $true -or
            $runtimeReceipt.child_frozen_backend_observed -ne $true -or
            $runtimeReceipt.native_authenticated_websocket_verified -ne $true -or
            $runtimeReceipt.wrong_token_rejected -ne $true -or
            $runtimeReceipt.backend_process_terminated_with_gui -ne $true) {
            throw "Installed runtime did not pass all required E2E checks"
        }
        $installedRuntimeVerified = $true
    } catch {
        $installedRuntimeError = "runtime_probe_failed"
        Write-Host "Runtime probe failed; continuing to verify uninstallation"
    }
    $uninstallerExitCode = Invoke-BoundedProcess $uninstallPath @("/S", "_?=$installedLocation") 180
    Start-Sleep -Seconds 3
    if (Test-Path -LiteralPath $gui -PathType Leaf) {
        Throw "Uninstall left the primary Tauri executable behind."
    }
    $uninstalled = $true
} finally {
    # Evidence is produced even when a required operation failed. Never
    # claim success just because NSIS returned exit code zero.
    $success = ($installerExitCode -eq 0 -and $uninstallerExitCode -eq 0 -and
        $runtimePresent -and $backendPresent -and $uninstalled -and $installedRuntimeVerified)
    $report = [ordered]@{
        schema = "jarvis-installer-smoke-v1"
        platform = "ephemeral-github-windows-runner"
        installer_sha256 = $hash
        installer_size_bytes = $length
        installed_location = $installedLocation
        expected_executable = "jarvis-studio-gui.exe"
        installer_exit_code = $installerExitCode
        frozen_backend_found = [bool]$backendPresent
        installed_runtime_verified = [bool]$installedRuntimeVerified
        installed_runtime_error = $installedRuntimeError
        runtime_receipt = "jarvis-installed-runtime-proof.json"
        gui_executable_found = [bool]$runtimePresent
        uninstaller_exit_code = $uninstallerExitCode
        uninstall_removed_gui = [bool]$uninstalled
        installer_code_signature_status = (Get-AuthenticodeSignature -LiteralPath $Installer).Status.ToString()
        installation_mode = "currentUser"
        gui_launched = [bool]$installedRuntimeVerified
        application_functional_acceptance = $false
        installed_runtime_ws_acceptance = [bool]$installedRuntimeVerified
        physical_power_loss_certified = $false
        success = [bool]$success
    }
    $report | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
    Write-Host "Installer smoke receipt: $ReceiptPath"
}
if (-not $success) { Throw "Installer smoke acceptance failed" }
Write-Host "PASS: NSIS installed jarvis-studio-gui.exe + backend and uninstalled successfully. SHA256=$hash"
