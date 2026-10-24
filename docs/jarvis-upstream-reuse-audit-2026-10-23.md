# JARVIS Windows — external feature reuse assessment (2026-10-23)

Objective: reuse complete, legitimately licensed, independently verifiable components instead of building duplicate implementations. **Do not delete an existing authorized implementation until a drop-in replacement has passed TDD, license/dependency review, Windows integration E2E and rollback tests.** A repository README advertising a feature is not that proof.

| Repository | Source license verified | Relevant completed/advertised feature | Integration assessment |
|---|---|---|---|
| [AnaaySampat/jarvis-windows](https://github.com/AnaaySampat/jarvis-windows) | MIT | Tauri+React Windows GUI, Python backend, voice, local Ollama | Same base architecture as this project. Reuse already present; avoid duplicating upstream modules. Third-party wake-word pretrained models have separate noncommercial terms. |
| [ndunl075/Jarvis](https://github.com/ndunl075/Jarvis) | MIT | Local Ollama, clipboard history, command palette, logs | Candidate for an isolated, bounded clipboard-history module, **only after** checking the actual storage policy, tests, Windows dependencies and owner confirmation. Not a replacement for the authenticated Git transaction / WebSocket security core. |
| [RizN91/jarvis](https://github.com/RizN91/jarvis) | MIT | Mature push-to-talk, Windows dictation, wake word, installer and smoke tests | Candidate for an opt-in Windows dictation adapter; its documented default speech recognition calls a paid OpenAI API. Do not silently replace offline Whisper or copy cloud credentials. |
| [SrDarkoll/JARVIS](https://github.com/SrDarkoll/JARVIS) | MIT (check bundled model and third-party notices) | Guarded Windows UI automation, optional speaker verification, Piper | Alpha project. Examine tests and permission boundaries before any targeted import; never directly copy OS command dispatch to bypass explicit owner approval. |
| [Dodaios/Dodaios](https://github.com/Dodaios/Dodaios) | Apache-2.0 | Multi-agent workflows, coding CLI orchestration, voice/dictation, desktop install | Larger separate architecture. Candidate for an *isolated* integration/adaptor, not a blind replacement of JARVIS Tauri/Python or local Git sandbox. Apache notices and attribution mandatory. |
| [LYiHub/pub-local-jarvis](https://github.com/LYiHub/pub-local-jarvis) | MIT repository source | MiniCPM-o GGUF multimodal desktop pet and NSIS packaging | Heavy model, different architecture; model files require separate licensing assessment. Does not establish suitable full voice/desktop control replacement. |
| [psycoks/Jarvis](https://github.com/psycoks/Jarvis) | **No root LICENSE verified** (as checked) | Wake word, Kokoro, speaker verification, Gemini agent | **Do not copy** until redistribution rights can be verified; model/provider behavior not compatible with strict offline mode by default. |

## Safe reuse already implemented

The local Python backend **already implements** `set_provider_mode("offline")`, Ollama routing, `has_llm_credentials()` in offline mode, and `needs_setup()`. What was incomplete was the first-run *GUI* exposing this path. The added first-run "Use local Ollama (no API key)" checkbox reuses this tested backend end-to-end through `set_config` and storage selection. No new LLM adapter, copied vendor code, fake API key, or compromised auth gate was required. The installed WebView2 Playwright test now follows that legitimate offline onboarding path before clicking "Review ZIP".

## Acceptance requirements for future upstream transplants

1. Pin a source repository, revision, files, license and copyright attribution; read transitive dependency and pretrained-model licenses separately.
2. Prove the candidate feature works in its source project on Windows without requiring elevated privileges or unapproved external network.
3. Build tests for the existing JARVIS contract, including denial/revocation, offline behavior, crash recovery and no unsanctioned shell or subprocess execution.
4. Integrate **one module at a time** behind a feature flag, with permission scoping, clear ownership of state and rollback.
5. Remove duplicated old code only after the replacement passes a real installed Windows E2E; record origin and licenses in a third-party notice.

**No external source modules were pasted during this assessment.** A license alone is not evidence of quality or API compatibility. The installer acceptance, crash/power-loss validation, WebSocket authorization and release signature gates stay fail-closed. PR remains draft; public release remains blocked without verified Authenticode and installed acceptance.
