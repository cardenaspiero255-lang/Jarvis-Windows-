# JARVIS Windows — Wake-word security and commercial release review (24 October 2026)

## Current source-level findings, not an exhaustive 345-file semantic audit

### P1: pretrained wake-word model packaging

The existing PyInstaller spec executes `collect_data_files("openwakeword")`;
the backend packager executes `openwakeword.utils.download_models()`.
Those steps prefetch and bundle pre-trained openWakeWord assets. The official
openWakeWord upstream states that **code** is Apache 2.0 while **included
pretrained models** are licensed CC BY-NC-SA 4.0. A distributable product
cannot presume unrestricted commercial rights to that model.

Source:
- https://github.com/dscripka/openWakeWord#license
- https://huggingface.co/davidscripka/openwakeword

A new release gate now blocks **both** the runtime's built-in pretrained
model fallback and the packaging directives that embed/download restricted
weights. The presence and hashes of the approval model and an owner rights
review are required. This is still a *technical precondition*, not proof of
rights to training data, imported model weights, or publisher certification.

**Not yet corrected:** a legally usable replacement for the built-in
`hey_jarvis` pretrained model has not been delivered. Therefore the present
package must not be approved for commercial public publication. Do not simply
rename/download another model; its actual rights and training provenance are
necessary. The current development-only baseline may be used strictly within
its licensing terms.

### P1: runtime transcription accepts near-miss proper names

The older `wake_word/capture.py` accepted `(j|ch|tr)` prefixes, causing
transcript text `Hey Travis` to be approved as a wake phrase. Replaced with
a narrower `j` prefix while keeping intended `Jarvis`/`Jervis` common
spellings. Adversarial unit tests cover direct calls to `heard_wake_phrase`
and the production `command_after_wake` path.

This does **not** fix false triggers from the initial acoustic model: the
unchanged 0.4 threshold may still produce peak scores above threshold on
isolated mentions of `Jarvis`. The original `wake-acoustic-real` workflow
and that negative phrase remain mandatory and blocking.

### P1: independent evaluation of an alternative Whisper prompt

The existing synthetic development campaign suggested better *synthetic*
recognition without the initial `Jarvis` prompt. The development scores must
not be used to claim independent validation. A separate 48-condition test
uses 12 additional **fixed and nonoverlapping sentences**, divided between
six synthetic positive and six synthetic negative utterances, with the same
acoustic variants and two transcription prompts. The threshold remains 0.4.
Its speakers still come from the installed SAPI voice pool, so this tests
novel *text*, not speaker independence. A valid human-positive FNR remains
unknown and the alternative transcription prompt is not deployed.

### P2: FULL offline installer and release signing

`scripts/build.ps1` defaults to the non-Lean packaged backend. The
`scripts/package-backend.ps1` workflow also downloads Chromium, Whisper and
Piper assets into a preload cache; the source comments and unpinned model
downloads are not cryptographic reproducibility evidence. The
`verify-release-signature.ps1` source refuses a missing or invalid
Authenticode signature. The `release.yml` workflow checks tag ancestry
and a signed installer, then requires installed-runtime receipts during
public publication. It does not prove these checks already happened on an
authorized physical PC, nor does a green Lean NSIS smoke certify FULL.

**Still required for commercial release:**
- licensed, hash-pinned custom wake model and a clean package asset inventory;
- independently checked rights for Piper voice models and other distributed weights;
- exact FULL installer/offline dependency hash inventory + installed E2E;
- valid Windows trusted code-signing certificate and verification on final binary;
- user-authorized Windows / Hyper-V physical failure-injection certification;
- comprehensive security audit of the broader PR and unresolved findings.

## Evidence policy

Do not silence failed wake gates, tune the 0.4 threshold against holdout, relabel
synthetic audio as human, claim low false alarms/hour from isolated clips, or
ship restricted model weights based only on a self-attestation flag. Changes
remain in the draft pull request until independent failures are resolved.
