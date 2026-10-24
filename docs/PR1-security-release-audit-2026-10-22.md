# PR #1 — Security and release audit (22 October 2026)

**Decision: BLOCK MERGE / BLOCK PUBLIC RELEASE.** This is a risk-based audit with
executable regression coverage, **not** a claim that every changed line was
independently semantically reviewed. The report is intentionally fail-closed.

## Change inventory

An API inventory of the PR enumerated **295 changed paths** as of commit
`c47302861418515393388f2a06b5e832eebc8c14` (counts will change
as audit fixes are committed):

- 185 Python files (including 92 named test files across file types)
- 38 JavaScript/JSX/TS/TSX files
- 3 Rust files
- 8 PowerShell scripts
- 7 GitHub Actions workflows
- 9 image/binary assets
- 16 Markdown/plain-text documentation files

Categories overlap, particularly tests and workflow-adjacent text files.
The file list is captured from GitHub's paginated PR diff. Binary visual
assets have **not** been manually examined pixel by pixel, and automatic
tests do not constitute an independent semantic review of every file.

## Confirmed P1 findings and mitigations

### P1: Native localhost client could spoof an approved WebView Origin

Previously `server/websocket_server.py::_authorized` accepted any localhost
socket that sent the `Origin: tauri://localhost` header, without requiring
the ephemeral bearer. A non-browser local process can set that header
arbitrarily. The origin check is a CSRF boundary, **not identity proof**.
Mitigation: every loopback client must present a valid per-session bearer;
origin allow-list still applies separately. Regression:
`test_local_websocket_origin_auth.py` exercises forged origins, wrong
bearers, valid native/WebView bearers, unconfigured bearers and cross-origin
denial. The installed-WebSocket probe additionally submits an origin-spoofed
connection and rejects it. A local attacker with access to the GUI process
itself remains outside this limited transport threat model.

### P1: Version tags could publish an unsigned Windows executable

Originally `.github/workflows/release.yml` published on version tag with
no Authenticode check. Mitigation: public release requires an explicit
`ENABLE_SIGNED_RELEASE` variable, a private expected publisher certificate
thumbprint, an installer with Windows `Get-AuthenticodeSignature` status
`Valid`, a matching publisher certificate, positive runtime receipts for the
**full, non-Lean** installer, and tag commit ancestry in `main`.
`verify-release-signature.ps1` fails closed when unsigned, tampered or
untrusted, while CI must prove an unsigned setup cannot be released.
**No signing certificate was supplied; signing is NOT certified and automatic
public release stays disabled.** A successful unsigned private CI artifact
is not a signed public release.

### P2: WebView production CSP previously allowed dynamic script evaluation

Removed `'unsafe-eval'` from `script-src` in Tauri `tauri.conf.json`.
`test_release_publication_gate.py` rejects any regression. The actual
installed Windows WebView2 CDP navigation smoke must also pass to ensure
no runtime breakage was introduced.

## Recovery and permission checks

- Durable Git journal pre-mutation, verified ZIP hashes, ref/index/source
  restoration, idempotent mid-rollback hard-crash tests: implemented and
  covered by `test_durable_git_recovery.py`. **Not** a physical power-loss
  validation on Windows disk hardware.
- ZIP intake, hash-bound user approval, no external code execution, negative
  malicious AST tests: dedicated repository review suites. Actual installed
  Ollama/Qwen proposal, AST review, approved memory-copy export and rollback:
  gated by Windows NSIS Acceptance.
- Remote device authentication and default-deny signed-message dispatch:
  dedicated `server/test_remote_handshake.py`,
  `server/test_tailscale_transport.py` and permission protocol tests.
- High-impact local actions (power, delete, app termination) are classified
  by `actions.needs_permission`; this is a **code-path review**, not an
  exhaustive runtime authorization proof across 185 Python files.
- The GUI exposes WebSocket bearer through a Tauri permission. Review further
  whether all auxiliary windows need that permission; do not widen scope.
- CSP uses `'unsafe-inline'` for styles. It is not a dynamic-script
  permission; style hardening remains possible.

## Windows product acceptance evidence

- Previous validated CI: real NSIS **Lean** setup, installed Tauri GUI and
  frozen Python child, authenticated WebSocket and rejected actions, local
  Ollama/Qwen model, reviewed ZIP and rollback, child cleanup, uninstall.
- New test: real **installed** WebView2 via Playwright/CDP in a disposable
  GitHub-hosted Windows runner. It must open ZIP review, reject pre-approval
  UI, close it, open Settings and upload a real screenshot. The CI-only CDP
  port is not configured in production.
- Voice UI: Talk/microphone control visibility is checked but **does not**
  demonstrate actual microphone input, acoustic wake detection, physical
  speech-to-text latency or audible playback.
- The full release installer bundles Whisper, Piper and browser assets,
  whereas ordinary PR acceptance uses `build.ps1 -Lean`. A **full offline
  installed test** has not been certified; the public release workflow now
  refuses publication without its own full-installer native E2E.
- The Windows system microphone and physical loudspeakers are unavailable
  through the current connected hosts (SentinelX inventory was empty).
  **Physical voice acceptance: NOT CERTIFIED.**
- Hyper-V virtual power-cut harness exists but has not run on an authorized
  Windows Hyper-V host. Real electrical power-loss testing is **NOT
  CERTIFIED**.

## Dependency/reproducibility and supply-chain risks

- npm has `package-lock.json`; Rust has `Cargo.lock`, with CI/frontend
  lint/build/tests and cargo checks. They are build/test evidence, not a
  substitute for current CVE scans on resolved packages.
- Python `requirements-release.txt` uses numerous `>=` ranges and
  PyInstaller is installed without an exact version/hash pin in
  `scripts/package-backend.ps1`. Fresh builds can resolve different
  versions: **release reproducibility not certified**.
- An `npm audit`, Python SBOM/vulnerability scan and complete review of
  binary resources/license distribution are recommended before promoting a
  paid or public release. The repository's rights and third-party model
  weights were **not independently adjudicated** in this code audit.

## Verification and release decision rules

1. Re-run all checks on the **exact final HEAD** after the last audit commit.
   Historic green workflows on older commits do not suffice.
2. Require a positive Windows NSIS **installed WebView2/UI/Qwen/rollback**
   result, uploaded receipts and screenshot. Inspect any failures rather
   than treating the runner's success alone as visual certification.
3. Require clean security, Rust, frontend, backend, isolated Linux, Windows
   GGUF and QEMU gates; preserve rollback evidence.
4. For public distribution require signed full installer and independent
   real installation proofs. Do not imply unsigned artifacts are signed.
5. Do not claim physical microphone or power-loss certification without
   the correct authorized hardware and real recorded tests.
6. **Do not merge PR #1** until blockers applicable to the requested
   release are resolved and the broader review is complete. The user
   owns the repository; no second human approval is being demanded.

This report separates *verified CI evidence*, *planned/verifying CI gates*
and *not-certified hardware/commercial claims*. It does not turn absence
of a detected bug into proof that the 295 changed files are defect-free.
