#!/usr/bin/env bash
# Trusted fixed Python fixture only; no foreign projects or tests are executed.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
WORK="$RUNNER_TEMP/jarvis-qemu-tcg"
mkdir -p "$WORK/rootfs"
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends qemu-system-x86 cpio gzip

# Versioned official Alpine virtual kernel; digest reported for pinning.
KERNEL_URL="https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/netboot-3.24.2/vmlinuz-virt"
curl --fail --location --silent --show-error --retry 2 --max-time 240 "$KERNEL_URL" -o "$WORK/vmlinuz-virt"
kernel_sha="$(sha256sum "$WORK/vmlinuz-virt" | cut -d' ' -f1)"
echo "Official Alpine virtual kernel SHA256: $kernel_sha"
EXPECTED_KERNEL_SHA256="40f620bc8c93d952e57dd8dfc0f94fca1759d192a4fc4a260705d50ca378559c"
test "$kernel_sha" = "$EXPECTED_KERNEL_SHA256" || {
  echo "::error::Pinned kernel SHA256 mismatch"
  exit 1
}
echo "Pinned kernel SHA256 PASS"

# Guest Python runtime from a trusted public OCI image. No Docker socket or
# host directories are mounted into QEMU.
PYTHON_GUEST_IMAGE="python@sha256:03c8e956bf1eee7763faf3a9fbb24b3ff9c0496cc2dbc5bcb0d6ac1f6268a287"
docker pull "$PYTHON_GUEST_IMAGE"
guest_id="$(docker create "$PYTHON_GUEST_IMAGE" /bin/true)"
trap 'docker rm -f "$guest_id" >/dev/null 2>&1 || true' EXIT
docker export "$guest_id" | tar -xf - -C "$WORK/rootfs" --no-same-owner --no-same-permissions
docker rm -f "$guest_id"
trap - EXIT
rootfs="$WORK/rootfs"
test -e "$rootfs/usr/local/bin/python3"
test -e "$rootfs/bin/sh"
test -e "$rootfs/bin/busybox"
docker_image="$(docker image inspect --format '{{index .RepoDigests 0}}' "$PYTHON_GUEST_IMAGE")"
echo "Python guest OCI image: $docker_image"

# Fixed AST-valid source for initial guest boot. A second integration step
# will use a real GGUF-produced proposal instead of this known fixture patch.
cat > "$WORK/pricing.py" <<'PY'
def line_total(unit_price, quantity):
    return quantity * unit_price
PY
source_sha="$(sha256sum "$WORK/pricing.py" | cut -d' ' -f1)"
if [ "${JARVIS_REAL_GGUF_VM:-0}" = "1" ]; then
  # Model server is started by trusted real-ollama-linux.sh on this runner.
  # Actual GGUF output, never the prewritten fallback, drives the VM/Git proof.
  python jarvis-studio-backend/real_guest_repair_e2e.py \
    --trusted-fixture --rootfs "$rootfs" --kernel "$WORK/vmlinuz-virt"
else
  python jarvis-studio-backend/qemu_tcg_guest.py \
    --trusted-fixture --rootfs "$rootfs" --kernel "$WORK/vmlinuz-virt" \
    --source-file "$WORK/pricing.py" --source-sha256 "$source_sha"
fi
