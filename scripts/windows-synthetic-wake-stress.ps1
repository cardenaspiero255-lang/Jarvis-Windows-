# Windows SAPI generates synthetic WAVs ONLY on ephemeral GitHub Windows runners.
# Does not access microphones, record humans, upload speech, or train models.
param(
    [ValidateSet("smoke", "campaign")]
    [string] $Profile = "smoke",
    [switch] $WithWhisper
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "Synthetic generation requires disposable Windows GitHub Actions runner"
}
Add-Type -AssemblyName System.Speech
$voicesynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
    16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$positive = @(
    "Hey Jarvis, what time is it?",
    "Hey Jarvis, open the calendar.",
    "Hey Jarvis, show the weather forecast.",
    "Hey Jarvis, take a short note.",
    "Hey Jarvis, please stop playing music.",
    "Hey Jarvis, how is the computer doing?",
    "Hey Jarvis, open my documents.",
    "Hey Jarvis, what is my next task?",
    "Hey Jarvis, tell me the current date.",
    "Hey Jarvis, lower the system volume.",
    "Hey Jarvis, help me write a message.",
    "Hey Jarvis, start the timer please.",
    "Hey Jarvis, check the network status.",
    "Hey Jarvis, open the file explorer.",
    "Hey Jarvis, cancel the last request."
)
$negative = @(
    "Jarvis is a digital assistant created for computers.",
    "The quick brown fox jumps over the lazy dog.",
    "Hey Travis, what time is it?",
    "The film mentioned a robot named Jarvis.",
    "Hey, did you leave the computer on?",
    "Could you open the calendar tomorrow?",
    "This is a documentary about voice assistants.",
    "I heard the name Jarvis on the news.",
    "Hello, this is an ordinary conversation.",
    "Jarvis technology is being discussed today.",
    "How do I open the document folder?",
    "My laptop has a built in microphone.",
    "Hey, the internet connection is slow.",
    "Let's practice speaking English sentences.",
    "Can you lower the sound on the speakers?"
)
$manifestPath = Join-Path $env:RUNNER_TEMP "jarvis-synthetic-manifest.json"
$receipt = Join-Path $env:RUNNER_TEMP "jarvis-synthetic-wake-receipt.json"
$records = [System.Collections.Generic.List[object]]::new()
try {
    $voices = @($voicesynth.GetInstalledVoices() | Where-Object { $_.Enabled })
    if ($voices.Count -lt 1) {
        throw "No installed Windows SAPI voice available. Cannot invent synthetic sources."
    }
    $limit = if ($Profile -eq "smoke") { 3 } else { 15 }
    $rates = if ($Profile -eq "smoke") { @(0) } else { @(0, 2) }
    $num = 0
    foreach ($label in @("synthetic_positive", "synthetic_negative")) {
        $phrases = if ($label -eq "synthetic_positive") { $positive } else { $negative }
        for ($i = 0; $i -lt $limit; $i++) {
            foreach ($rate in $rates) {
                $installed = $voices[$num % $voices.Count].VoiceInfo
                $voicesynth.SelectVoice($installed.Name)
                $voicesynth.Rate = $rate
                $voicesynth.Volume = 100
                $name = "sapi-{0:D3}.wav" -f $num
                $out = Join-Path $env:RUNNER_TEMP $name
                $voicesynth.SetOutputToWaveFile($out, $format)
                try {
                    $voicesynth.Speak([string] $phrases[$i])
                } finally {
                    $voicesynth.SetOutputToNull()
                }
                $sha = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLowerInvariant()
                $locale = if ([string]::IsNullOrWhiteSpace($installed.Culture.Name)) {
                    "und"
                } else {
                    [string] $installed.Culture.Name
                }
                $records.Add(@{
                    file = $name
                    sha256 = $sha
                    voice_id = [string] $installed.Name
                    locale = $locale
                    rate = [int] $rate
                    text = [string] $phrases[$i]
                    label = $label
                    source_kind = "windows_sapi_synthetic"
                })
                $num++
            }
        }
    }
    $manifest = @{
        schema = 1
        profile = $Profile
        samples = @($records.ToArray())
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    $args = @(
        "./jarvis-studio-backend/synthetic_wake_stress.py",
        "--manifest", $manifestPath,
        "--receipt", $receipt
    )
    if ($WithWhisper) { $args += "--with-whisper" }
    & python @args
    if ($LASTEXITCODE -ne 0) { throw "Synthetic wake benchmark failed; receipt contains failure type" }
} finally {
    $voicesynth.Dispose()
    foreach ($row in $records) {
        Remove-Item -LiteralPath (Join-Path $env:RUNNER_TEMP $row.file) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
}
