# Ephemeral Windows SAPI synthetic test speech. No human recordings.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "Wake research runs only on disposable Windows GitHub Actions"
}
Add-Type -AssemblyName System.Speech
$format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
    16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)
$voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$manifest = Join-Path $env:RUNNER_TEMP "jarvis-local-whisper-wake-manifest.json"
$receipt = Join-Path $env:RUNNER_TEMP "jarvis-local-whisper-wake-receipt.json"
$model = Join-Path $env:RUNNER_TEMP "jarvis-whisper-base"
$clips = @(
    @{ label = "synthetic_positive"; text = "Hey Jarvis, open the calendar." },
    @{ label = "synthetic_positive"; text = "Hey Jarvis, tell me the date." },
    @{ label = "synthetic_positive"; text = "Hey Jarvis, what is the weather?" },
    @{ label = "synthetic_positive"; text = "Hey Jarvis, set a reminder." },
    @{ label = "synthetic_negative"; text = "Hey Travis, open the calendar." },
    @{ label = "synthetic_negative"; text = "Jarvis is a digital assistant." },
    @{ label = "synthetic_negative"; text = "Hi Travis, what is the weather?" },
    @{ label = "synthetic_negative"; text = "They discussed Jarvis in that movie." }
)
$generated = [System.Collections.Generic.List[object]]::new()
try {
    $voices = @($voice.GetInstalledVoices() | Where-Object { $_.Enabled })
    if ($voices.Count -lt 1) { throw "No Windows SAPI voice present" }
    for ($i = 0; $i -lt $clips.Count; $i++) {
        $entry = $clips[$i]
        $installed = $voices[$i % $voices.Count].VoiceInfo
        $voice.SelectVoice($installed.Name)
        $voice.Rate = if ($i % 2 -eq 0) { 0 } else { 1 }
        $wav = ("jarvis-local-whisper-{0:D2}.wav" -f $i)
        $path = Join-Path $env:RUNNER_TEMP $wav
        $voice.SetOutputToWaveFile($path, $format)
        try { $voice.Speak([string]$entry.text) }
        finally { $voice.SetOutputToNull() }
        $generated.Add(@{file = $wav; label = $entry.label})
    }
    ConvertTo-Json -InputObject @($generated.ToArray()) -Depth 4 | Set-Content -LiteralPath $manifest -Encoding utf8
    # Model downloaded once in CI; actual inference must use only local files.
    & python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-base', local_dir=r'$model')"
    if ($LASTEXITCODE -ne 0) { throw "Official model download failed" }
    & python "./jarvis-studio-backend/real_whisper_local_windows.py" --manifest $manifest --bundled-model $model --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw "Real local Whisper wake inference failed" }
} finally {
    $voice.Dispose()
    foreach ($row in $generated) {
        Remove-Item -LiteralPath (Join-Path $env:RUNNER_TEMP $row.file) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $manifest -Force -ErrorAction SilentlyContinue
}
