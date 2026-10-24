# Synthesized Windows SAPI fixtures exercise real ONNX wake-word inference.
# Only in disposable GitHub runners: no microphone, speaker or user recording.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "Wake fixtures require ephemeral Windows GitHub Actions environment"
}
Add-Type -AssemblyName System.Speech
$work = Join-Path $env:RUNNER_TEMP ("jarvis-wake-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$receipt = Join-Path $env:RUNNER_TEMP "jarvis-neural-wake-receipt.json"
$voice = $null
try {
    $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if (@($voice.GetInstalledVoices() | Where-Object { $_.Enabled }).Count -lt 1) {
        throw "No Windows SAPI voice installed; do not fabricate a positive wake"
    }
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    $specs = @(
        @{name="positive-a.wav"; text="Hey Jarvis, what time is it?"},
        @{name="positive-b.wav"; text="Hey Jarvis, open the calendar."},
        @{name="negative-a.wav"; text="The quick brown fox jumps over the lazy dog."},
        @{name="negative-b.wav"; text="Jarvis is a digital assistant created for computers."}
    )
    foreach ($item in $specs) {
        $out = Join-Path $work $item.name
        $voice.SetOutputToWaveFile($out, $format)
        $voice.Speak($item.text)
        $voice.SetOutputToNull()
        if (-not (Test-Path -LiteralPath $out -PathType Leaf)) {
            throw "SAPI WAV fixture was not produced"
        }
    }
    python ./jarvis-studio-backend/real_neural_voice_e2e.py wake `
        --receipt $receipt `
        --positive (Join-Path $work "positive-a.wav") (Join-Path $work "positive-b.wav") `
        --negative (Join-Path $work "negative-a.wav") (Join-Path $work "negative-b.wav")
    if ($LASTEXITCODE -ne 0) { throw "Real acoustic wake model gate not satisfied" }
} finally {
    if ($null -ne $voice) { $voice.Dispose() }
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
