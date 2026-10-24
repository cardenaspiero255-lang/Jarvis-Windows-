# Interactive physical Windows acceptance. Never runs unattended or in CI.
# Only reads OS/device/process state and writes a local, key-free JSON receipt.
# It never records microphone audio, changes microphone permission or kills tasks.
param(
    [Parameter(Mandatory=$true)][string]$JarvisExePath,
    [string]$ReceiptPath = (Join-Path $env:TEMP (
        "jarvis-physical-" + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss") +
        "-" + [Guid]::NewGuid().ToString("N") + ".json"))
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Requires a real Windows computer."
}
if ($env:GITHUB_ACTIONS -eq "true") {
    throw "Physical field acceptance must not run in GitHub Actions."
}
$guiPath = (Resolve-Path -LiteralPath $JarvisExePath -ErrorAction Stop).Path
if ([IO.Path]::GetFileName($guiPath) -ine "jarvis-studio-gui.exe") {
    throw "Expected an installed JARVIS GUI executable, not a test stub."
}
if (Test-Path -LiteralPath $ReceiptPath) {
    throw "Refusing to overwrite an existing acceptance receipt."
}
$sha = (Get-FileHash -LiteralPath $guiPath -Algorithm SHA256).Hash.ToLowerInvariant()
$running = $false
$adapter = $false
$virtualHint = $true
try {
    $running = @(
        Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { $_.Name -eq "jarvis-studio-gui.exe" -and
                       $_.ExecutablePath -ieq $guiPath }
    ).Count -gt 0
} catch { Write-Warning "Could not inspect JARVIS process; evidence remains blocked." }
try {
    # Adapter enumeration is a prerequisite, NOT proof of captured microphone audio.
    $adapter = @(Get-CimInstance Win32_SoundDevice -ErrorAction Stop).Count -gt 0
} catch { Write-Warning "Could not enumerate sound devices; evidence remains blocked." }
try {
    $system = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $kind = [string]$system.Manufacturer + " " + [string]$system.Model
    $virtualHint = $kind -match "Virtual|VMware|VirtualBox|QEMU|Hyper-V|KVM|Xen"
} catch { Write-Warning "Could not inspect computer model; evidence remains blocked." }

Write-Host "JARVIS PHASE 2: interactive operator observations on an authorized physical PC."
Write-Host "No audio is recorded by this script; every outcome must be observed in the real JARVIS GUI."
Write-Host "A pass is USER_ATTESTED only, not independent acoustic certification."
Write-Host "Run JARVIS yourself before starting. Close applications containing unsaved data before recovery tests."
$operatorConfirm = (Read-Host "Confirm that this is a physical Windows PC, with you able to see/hear it (SI/NO)").Trim().ToUpperInvariant()
if ($operatorConfirm -ne "SI") {
    Write-Warning "Physical operator presence not established; receipt will be NOT_CERTIFIED."
}
$challenge = Get-Random -Minimum 1000 -Maximum 9999
$checks = @(
    @{ id="mic_stt"; instruction="Press Talk; speak 'JARVIS prueba $challenge'; verify it recognizes YOUR speech on screen. Do not type the phrase." },
    @{ id="wake_word"; instruction="From idle, WITHOUT click or keyboard, say 'Hey Jarvis' then a simple question; verify wake and actual recognition." },
    @{ id="tts_audible"; instruction="Ask JARVIS to respond aloud. Listen to its ACTUAL audible reply through physical speakers/headphones." },
    @{ id="permission_denial"; instruction="Request an action that displays JARVIS permission dialog (do not request destructive actions). DENY; verify it did not execute." },
    @{ id="permission_safe_approval"; instruction="Request a safe, read-only action requiring approval. APPROVE only that action; confirm one authorized execution." },
    @{ id="cancel_listening"; instruction="Begin microphone listening, press stop/orb. Verify listening stops and a late recognition cannot trigger an action." },
    @{ id="cancel_speaking"; instruction="Start an audible LONG response, press stop/orb. Confirm playback actually stops and does not resume unexpectedly." },
    @{ id="cancel_readonly_task"; instruction="Start a safe, read-only longer task; cancel it. Confirm no further work or unapproved side effects." },
    @{ id="recover_relaunch"; instruction="Close JARVIS normally, launch the SAME installed executable again; confirm UI, backend and microphone are usable." },
    @{ id="recover_microphone_access"; instruction="If safe on YOUR machine: deny Windows mic access, confirm JARVIS handles denial; restore access and verify recognition again. Leave original settings restored." }
)
$cases = @()
foreach ($check in $checks) {
    Write-Host ""
    Write-Host ("CASE: " + $check.id)
    Write-Host $check.instruction
    do {
        $answer = (Read-Host "Observed result: P=PASS, F=FAIL, O=OMIT (not tested)").Trim().ToUpperInvariant()
    } until ($answer -in @("P", "F", "O"))
    $outcome = switch ($answer) { "P" { "pass" } "F" { "fail" } "O" { "skip" } }
    $cases += [ordered]@{
        id = $check.id
        outcome = $outcome
        evidence_mode = "human_observed"
    }
}
$physicalHost = ($operatorConfirm -eq "SI" -and -not $virtualHint)
$allPass = @($cases | Where-Object { $_.outcome -ne "pass" }).Count -eq 0
$attested = $physicalHost -and $running -and $adapter -and $allPass
$receipt = [ordered]@{
    schema = "jarvis-windows-physical-v1"
    created_utc = [DateTime]::UtcNow.ToString("o")
    platform = "windows"
    host_type = $(if ($physicalHost) { "physical_observed" } else { "unverified" })
    source = "interactive_operator"
    gui_exe_sha256 = $sha
    gui_process_observed = [bool]$running
    audio_adapter_detected = [bool]$adapter
    cases = $cases
    status = $(if ($attested) { "USER_ATTESTED_PHYSICAL" } else { "NOT_CERTIFIED" })
    independently_certified = $false
    physical_certified = $false
    signed_release_certified = $false
}
$parent = Split-Path -Parent $ReceiptPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
Write-Host ("Receipt saved locally: " + $ReceiptPath)
Write-Host ("Result: " + $receipt.status)
if (-not $attested) {
    throw "Physical acceptance NOT_CERTIFIED: at least one requirement was not observed."
}
