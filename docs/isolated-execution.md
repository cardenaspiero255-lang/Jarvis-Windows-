# JARVIS isolated execution — initial verification

## Current scope

The initial sandbox validates a **trusted, pinned educational fixture** with three Python modules (`pricing`, `coupons`, `orders`) and eleven checks. It does not automatically clone, install dependencies, execute arbitrary model commands, accept untrusted repositories, or edit GitHub PRs.

JARVIS's Windows backend does not run the fixture's tests. GitHub Actions uses a separate, disposable `ubuntu-latest` host and Docker container. The Linux host's orchestrator copies known fixture files and invokes Docker using a fixed argument list. Only the container imports and runs the project code.

Proof: the deliberately incorrect baseline fails. The legacy deterministic smoke uses a vetted, hardcoded correction; the separate **real-gguf-sandbox** job obtains an actual local Ollama/Qwen proposal, constrains it with JSON + AST + arithmetic checks, constructs the patched bytes from that validated AST, and tests those actual bytes in Docker. Both paths require the 11 checks to pass, with SHA-256 evidence. This demonstrates a trusted-fixture repair only, not autonomous repair of arbitrary repositories.

## Container restrictions

- `--network=none` blocks external networking for the container (verified by a socket test).
- `--read-only`, a read-only `/code` bind mount, and a small `/tmp` tmpfs restrict writes (verified by a file-write test).
- `--user=65534:65534`, `--cap-drop=ALL`, `--security-opt=no-new-privileges` remove root and Linux capabilities from this process.
- `--pids-limit=64`, `--memory=256m`, `--memory-swap=256m`, `--cpus=1` and an outer Python timeout limit resources.
- Docker starts a fixed Python unittest command, never a command emitted by an LLM.
- Only a checked-in fixture is provided. A file inventory rejects symlinks, Git metadata, oversized files and non-allowlisted extensions.
- The Docker image is pulled by the CI host first, then invoked **by its observed SHA256 digest**, with `--pull=never`. The digest is included in the receipt.
- GitHub job has `contents: read`, checkout does not persist credentials, and no secrets are passed into the Docker subprocess.

## Security limitations and next gate

**Docker shares the host's Linux kernel**. A container is not a proven boundary against all malicious code or kernel vulnerabilities. The current Python orchestrator also uses captured child-process output and is designed **only for this small, known fixture**, not for arbitrary hostile workloads that could flood stdout/stderr.

Before accepting untrusted repository ZIPs or dependency installers:

1. Use disposable VM or microVM isolation, rather than relying only on Docker, and remove any host Docker socket.
2. Validate archive entries against path traversal, link targets, case-insensitive collisions, decompression bombs and executable hooks.
3. Cap subprocess logs and disk consumption, and enforce detached container kill/cleanup after timeout.
4. Acquire trusted container images and tools by reviewed immutable digests, use isolated build caches and zero network by default.
5. Require explicit user permission for every external checkout/test job and separately for publishing a branch or PR; preserve SHA and test evidence.
6. Run a deliberately hostile benchmark against the isolation boundary and review results before broadening permissions.

No installation of Docker on the user's Windows computer is assumed. Local Windows integration and actual microphone/installer testing remain separate, outstanding milestones.


## October 22 — External repository inspection and fail-closed VM gate

The new external_repo_preview.py module permits **read-only examination of a user-supplied ZIP snapshot**, without executing its code. Accepted source formats are Python, JS/JSX, TS/TSX, Kotlin/KTS, Markdown and JSON. It limits archive bytes, file count, decompressed bytes and compression ratio; rejects traversal/absolute/drive paths, backslashes, Windows reserved names, hidden metadata including Git internals, duplicate/case-colliding entries, symlinks, encrypted members, unsupported executables, and non-UTF-8 contents. Python files are parsed for syntax **without importing them**.

The patch preview is **deliberately narrow**: with explicit read permission, it can accept one JSON return-expression proposal for a top-level, two-argument Python arithmetic function. It validates the AST against the bounded arithmetic subset, constructs the returned bytes from the validated AST rather than copying raw model text, and emits an in-memory diff and SHA-256. It does **not** execute the patch or change the source ZIP, workspace files, user's repository, Git remotes or PRs. Source context is not automatically sent to a model; the caller must decide separately if local inference on sensitive source is authorized. This is not broad Python/JS/TS/Kotlin repair.

The vm_execution_gate.py module probes Linux /dev/kvm without launching a guest. The separate MicroVM Readiness and External ZIP Preview GitHub workflow stores a small capability receipt. **The execution gate stays denied even with KVM and explicit user consent** because VM boot, kernel isolation, guest lifecycle and authenticity are not yet independently verified. Caller JSON/environment flags cannot override it. A disposable GitHub-hosted Linux runner plus Docker is not a substitute for a verified guest boundary for malicious repositories.

The next security milestone is a genuine disposable VM/microVM guest on a suitable KVM-enabled runner (or a separately validated full-VM software-emulation implementation), with pinned guest image/kernel, no host filesystem/credentials/socket exposure, offline-by-default networking, execution time/memory/log limits, hard cleanup, attested guest lifecycle, adversarial escape testing, and explicit separate approvals for read, execution and publication. **Until that proof exists, external repository tests remain disabled by design.**


## External ZIP review in the Windows GUI — staged copy and rollback

The Windows desktop now exposes a **Review ZIP** dialog connected to `main.py` over a local-only, sender-scoped WebSocket event. The backend routes it through `repository_review_api.py` to `repository_review_sessions.py`. Paired remote devices and remote tasks are not allowlisted to use this event. A session belongs to one local WebSocket client and expires after ten minutes. The user explicitly selects a ZIP and separately opts into local Ollama inspection for a chosen Python file and two-argument function.

1. **Inspect**: ZIP bytes are size bounded and validated without extracting or executing them. A basic language inventory and Python syntax-error count are shown. The source does not leave the host at this step.
2. **Propose/review**: a localhost-only `qwen2.5-coder:0.5b` proposal is validated as a single arithmetic Python return expression. The preview displays a diff and SHA-256, clearly marked **syntax only / no external tests**. Unsupported functions, model imports, instructions in files, arbitrary commands and additional model output fields are rejected.
3. **Approve copy**: a second explicit click is bound to the SHA-256 of the exact reviewed Python output. The backend reconstructs the patch from the AST, rechecks its hash, and makes an **in-memory ZIP copy**. Other files retain their contents. No original folder, repository, Git remote or user file is edited. The user must explicitly request export and then save the copy.
4. **Rollback/discard**: cancels the review, removes both the original ZIP and modified-copy bytes held by that session, and invalidates its authorization. Closing the panel also requests discard. Rejected requests remain revocable only by their original local client.

The dedicated `MicroVM Readiness and External ZIP Preview` job runs the ZIP and review adversarial matrix: directory traversal, absolute/drive paths, Windows reserved and ambiguous path components, raw ZIP backslashes, case collisions, duplicates, ZIP size/compression abuse, malformed headers, invalid model AST, wrong hash, nonboolean approval, expired/forged sessions, remote sender rejection and staged-copy revocation.

**Limits:** These passing regression tests show the tested controls behave as specified, not that untrusted ZIP ingestion is penetration-tested or certified against every possible exploit. The GUI review does not yet run external tests in QEMU, modify user repositories in place, verify app installation or provide a persistent user-workspace backup/restore transaction. The existing QEMU work runs only the preapproved arithmetic fixture; `vm_execution_gate.py` still denies running third-party code. The rollback here discards an *unexported, in-memory modified copy*, not edits to a real user's existing repository.
