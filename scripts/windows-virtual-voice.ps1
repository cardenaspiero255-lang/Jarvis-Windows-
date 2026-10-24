# Windows SAPI synthesis is REAL local OS audio generation, but NOT
# physical JARVIS mic/voice hardware nor a JARVIS Piper output test.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "Virtual audio is restricted to a disposable Windows Actions runner"
}
Add-Type -AssemblyName System.Speech
$folder = Join-Path $env:RUNNER_TEMP ("jarvis-virtual-voice-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$wake = Join-Path $folder "wake.wav"
$negative = Join-Path $folder "negative.wav"
$receipt = Join-Path $env:RUNNER_TEMP "jarvis-virtual-voice-acceptance.json"
$voice = $null
try {
    $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if (@($voice.GetInstalledVoices() | Where-Object { $_.Enabled }).Count -lt 1) {
        throw "Windows SAPI voice absent: no TTS inference claim"
    }
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    foreach ($sample in @(
        @{path=$wake; text="Hey Jarvis, what time is it right now?"},
        @{path=$negative; text="The quick brown fox jumps over the lazy dog in the garden."}
    )) {
        $voice.SetOutputToWaveFile($sample.path, $format)
        $voice.Speak($sample.text)
        $voice.SetOutputToNull()
        if (-not (Test-Path -LiteralPath $sample.path)) {
            throw "Windows SAPI did not generate WAV"
        }
    }
    python ./jarvis-studio-backend/windows_virtual_voice_probe.py `
        --wake $wake --negative $negative --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw "Real synthesized-wave / local Whisper virtual acceptance FAILED" }
} finally {
    if ($null -ne $voice) {
        $voice.Dispose()
    }
    # PCM samples are ephemeral and are NEVER uploaded to workflow artifacts.
    Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
}
