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
$uninstallPath = $null
try {
    $installerExitCode = Invoke-BoundedProcess $Installer @("/S", "/D=$root") 180
    $deadline = (Get-Date).AddSeconds(100)
    $gui = Join-Path $root "JARVIS.exe"
    $backendCandidates = @(
        (Join-Path $root "jarvis-backend\jarvis-backend.exe"),
        (Join-Path $root "resources\jarvis-backend\jarvis-backend.exe")
    )
    do {
        $runtimePresent = Test-Path -LiteralPath $gui -PathType Leaf
        $backendPresent = @($backendCandidates | Where-Object {
            Test-Path -LiteralPath $_ -PathType Leaf
        }).Count -gt 0
        if ($runtimePresent -and $backendPresent) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $runtimePresent -or -not $backendPresent) {
        Throw "Installation did not contain JARVIS.exe and frozen jarvis-backend.exe."
    }

    $uninstaller = @(Get-ChildItem -LiteralPath $root -File |
        Where-Object { $_.Name -match '^(?i:uninstall|unins.*)\.exe$' })
    if ($uninstaller.Count -ne 1) {
        Throw "Exactly one NSIS uninstall executable is required."
    }
    $uninstallPath = $uninstaller[0].FullName
    $uninstallerExitCode = Invoke-BoundedProcess $uninstallPath @("/S", "_?=$root") 180
    Start-Sleep -Seconds 3
    if (Test-Path -LiteralPath $gui -PathType Leaf) {
        Throw "Uninstall left the primary JARVIS.exe executable behind."
    }
    $uninstalled = $true
} finally {
    # Evidence is produced even when a required operation failed. Never
    # claim success just because NSIS returned exit code zero.
    $success = ($installerExitCode -eq 0 -and $uninstallerExitCode -eq 0 -and
        $runtimePresent -and $backendPresent -and $uninstalled)
    $report = [ordered]@{
        schema = "jarvis-installer-smoke-v1"
        platform = "ephemeral-github-windows-runner"
        installer_sha256 = $hash
        installer_size_bytes = $length
        installer_exit_code = $installerExitCode
        frozen_backend_found = [bool]$backendPresent
        gui_executable_found = [bool]$runtimePresent
        uninstaller_exit_code = $uninstallerExitCode
        uninstall_removed_gui = [bool]$uninstalled
        installer_code_signature_status = (Get-AuthenticodeSignature -LiteralPath $Installer).Status.ToString()
        installation_mode = "currentUser"
        gui_launched = $false
        application_functional_acceptance = $false
        physical_power_loss_certified = $false
        success = [bool]$success
    }
    $report | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
    Write-Host "Installer smoke receipt: $ReceiptPath"
}
if (-not $success) { Throw "Installer smoke acceptance failed" }
Write-Host "PASS: NSIS installed JARVIS.exe + backend and uninstalled successfully. SHA256=$hash"
