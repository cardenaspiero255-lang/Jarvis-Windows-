#!/usr/bin/env bash
# Trusted on-runner setup of real Ollama, then test ONLY a pinned fixture in Docker.
# NEVER executes third-party repo code on Windows or outside the Docker fixture.
set -euo pipefail
version="v0.34.0"
sha="cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804"
url="https://github.com/ollama/ollama/releases/download/$version/ollama-linux-amd64.tar.zst"
root="$RUNNER_TEMP/jarvis-real-ollama"
mkdir -p "$root/bin" "$root/models"
archive="$root/ollama-linux-amd64.tar.zst"
curl --fail --location --silent --show-error --retry 2 --connect-timeout 30 --max-time 360 \
  --output "$archive" "$url"
echo "$sha  $archive" | sha256sum --check --status
tar --zstd -xf "$archive" -C "$root"
rm -f "$archive"
test -x "$root/bin/ollama"
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="$root/models"
export OLLAMA_NO_CLOUD="1"
export OLLAMA_NUM_PARALLEL="1"
export OLLAMA_KEEP_ALIVE="0"
export CUDA_VISIBLE_DEVICES="-1"
"$root/bin/ollama" serve >"$root/ollama.log" 2>&1 &
ollama_pid=$!
cleanup() {
  kill "$ollama_pid" 2>/dev/null || true
  wait "$ollama_pid" 2>/dev/null || true
}
trap cleanup EXIT
ready=0
for i in $(seq 1 90); do
  if curl --fail --silent --max-time 2 "http://127.0.0.1:11434/api/tags" >/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$ollama_pid" 2>/dev/null; then
    echo "ERROR: real Ollama daemon exited before startup"
    exit 1
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "ERROR: real Ollama daemon did not start"
  exit 1
fi
"$root/bin/ollama" pull qwen2.5-coder:0.5b
image_ref="$(docker image inspect --format '{{index .RepoDigests 0}}' python:3.11-slim-bookworm)"
python jarvis-studio-backend/isolated_repo_runner.py \
  --ci-demo --real-ollama --image-ref "$image_ref"

# After the original trusted Docker oracle, verify an independent real GGUF
# proposal inside a QEMU TCG Linux guest, then stage an explicitly authorized
# disposable Git branch. This NEVER executes an external repository.
JARVIS_REAL_GGUF_VM=1 bash scripts/qemu-fixture-proof.sh
