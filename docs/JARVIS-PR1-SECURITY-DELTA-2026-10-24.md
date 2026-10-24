# JARVIS Windows PR #1 — security and release delta audit
Date: 2026-10-24

**Merge decision: BLOCKED. Public release: BLOCKED.**

## Evidence scope

The GitHub PR changed-file API returned 351 paths at this review point:
219 Python; 39 JS/JSX/TS; 3 Rust; 12 PowerShell scripts;
13 Actions workflows; 25 Markdown files (groups do not cover all types).
These counts change as commits are added. A keyword-based risk screen
found 56 paths matching security/auth/permissions/release/voice terms.

Targeted inspection of code and PR patches included:
- `jarvis-studio-backend/authorized_git_transaction.py`
- `jarvis-studio-backend/server/websocket_server.py`
- `jarvis-studio-backend/app_secrets.py`
- `jarvis-studio-gui/src/hooks/useWebSocket.js`
- `jarvis-studio-gui/src-tauri/build.rs`
- `scripts/verify-release-signature.ps1`
- `scripts/package-backend.ps1`, `jarvis-backend.spec`, release workflow
- Wake detection, its regression suites and FULL offline preflight.

This is a risk-based **partial code/patch review**, NOT complete semantic
review of all 351 paths or a formal external penetration test.

## Findings and changes

### P1 — Noncommercial pre-trained openWakeWord files could be distributed
Upstream code is Apache 2.0 but pretrained model assets CC BY-NC-SA 4.0.
Previous `package-backend.ps1` downloaded these weights and PyInstaller
collected the package data. The clean build uses:
`JARVIS_WAKE_PACKAGE_MODE=whisper_local`, omits openWakeWord pretrained
weights from PyInstaller, installs an engine-enforcing PyInstaller runtime
hook, and audits the actual staged FULL file tree for forbidden model assets.
A strict public-release precheck still requires an explicit owner rights
review. **A green build is not legal clearance.**

Alternative offline recognizer: Whisper base converted model (MIT card),
2.88 s audio windows and 1.92 s hop, no initial `Jarvis` text prompt,
no acoustic openWakeWord weights. It returns 0/1, which are NOT calibrated
acoustic scores and must not be compared as probabilities. This is an
opt-in prototype, not the default development detector; physical benchmark,
CPU and memory measurement, latency, and human positives are still open.
The historical `wake-acoustic-real` benchmark retains its 0.4 threshold
and its false-positive control; no criteria were loosened.

Sources:
https://github.com/dscripka/openWakeWord#license
https://github.com/openai/whisper#license
https://huggingface.co/Systran/faster-whisper-base

### P1 — The default Piper voice had restricted lineage
The previous `en_GB-alan-medium` Piper model card links to
`MycroftAI/mimic3-voices/voices/en_UK/apope_low`, whose LICENSE says
`All Rights Reserved`. An upstream model repository's broad MIT badge
is not sufficient evidence for each distinct training dataset.

Replaced the app, model acceptance test and prefetch default with
`en_US-john-medium`, whose individual model card describes public-domain
LibriVox recordings, and explicitly removes/rejects stale Alan weights
in clean build caches / staged resources. The substitute is **US English
male**, not the prior British voice; any request to restore a voice that
resembles a public figure must independently satisfy voice rights.
Its exact final model bytes, train/fine-tune chain and redistribution
conditions should still be signed off before public distribution.

Sources:
https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_GB/alan/medium/MODEL_CARD
https://github.com/MycroftAI/mimic3-voices/blob/master/voices/en_UK/apope_low/LICENSE
https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/john/medium/MODEL_CARD

### P1 — Persistent preload cache was copied without a top-level allowlist
Original packaging used `Copy-Item -Path (Join-Path $Cache "*")`.
Replaced with explicit only `ms-playwright`, `whisper-base` and `piper`
roots plus symlink / junction checks. A preflight recursively scans staged
assets, hashes essential binaries and denies restricted model bytes.
Remaining risk: nested unexpected regular files and third-party package
dependency supply chain. Independently pin asset checksums and source
revisions and verify complete SBOM before shipment.

### P1 — Wake misrecognition and known acoustic false activations
Fixed `Hey Travis` and `Chervis` text acceptance and added UI regression.
An experimental transcript-only alternative is added for measured local
evaluations; it does not claim to solve the OWW false-activation gate.
The prior hard negative `Jarvis is a digital assistant` remains mandatory.

### P2 — Full installer authenticity / physical testing
`release.yml` now attempts an actual FULL clean asset preflight after
packaging, before signing and installed runtime E2E. Its gate distinguishes
asset availability from installed runtime certification. A valid trusted
Authenticode signer is STILL required. No Windows physical device is linked
for microphone, real power-cut, or acoustically independent certification.
No signed FULL installer has been certified in this intervention.

## Outstanding audit / release gates

1. Wait for ALL final-commit GitHub jobs to complete; inspect failures on
   the same SHA. An earlier green result is not approval for the latest HEAD.
2. Measure real `whisper_local` accuracy and latency/memory on Windows,
   including the recorded negative clips and false-wake stress cases.
3. Build/install/uninstall the genuine FULL offline NSIS bundle and prove
   Qwen, WebView2, authenticated WebSocket and recovery/rollback from the
   installed process, not only Lean's staging.
4. Validate all distributed model and browser binaries against externally
   pinned hashes and complete SPDX/SBOM/license notices. Review individual
   Piper model cards; do not infer rights from an organization-level badge.
5. Review ALL remaining PR diffs for authorization boundaries, path
   traversal, command execution, secrets, UI permission escalation, crash
   recovery and transitive dependencies; this review did not do so.
6. Validate trusted Authenticode on the exact final executable, not a
   previous file or an unsigned CI artifact.
7. Independently evaluate with real, permissioned human positive clips
   and hardware. Synthetic-only tests cannot certify human false rejects.

**The owner remains the sole repository maintainer; no additional human
GitHub approval is assumed. Blocking gates reflect technical and rights
requirements, not a second-reviewer requirement.**
