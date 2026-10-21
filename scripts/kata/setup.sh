#!/usr/bin/env bash
# K10: a Docker engine whose containers can each run in their own microVM, through Kata
# Containers with Cloud Hypervisor, for Repro's `docker_runtime = "kata"` (L5; ADR-0018,
# option C as built). Linux with KVM only; WSL2 with nested virtualization works (Windows 11's
# default). Run once, as root:
#
#     sudo bash scripts/kata/setup.sh
#
# What it installs, pinned:
# - Docker Engine 29.8.2 from Docker's apt repository, whose signing key is checked by its
#   fingerprint (docs.docker.com/engine/install/ubuntu, read on 2026-10-21);
# - Kata Containers 4.2.0's static release under /opt/kata (its Rust runtime, its guest kernel
#   and image, Cloud Hypervisor and virtiofsd), checked by the release's SHA-256 (GitHub's
#   asset digest, read on 2026-10-21);
# - the shim `containerd-shim-kata-clh-v2`: Kata's shim with its shipped Cloud Hypervisor
#   configuration, and Docker's runtime `kata`, which names it (docs.docker.com/engine/daemon/
#   alternative-runtimes: a shim's path may be the runtime's `runtimeType`).
# Cloud Hypervisor shares directories with the microVM (virtio-fs), so Repro's volumes work as
# they do in a container. Firecracker cannot (its storage is block devices only), which is why
# it is not used.
# The user who ran sudo joins the `docker` group: membership is control of the engine, so of
# this machine's root.
#
# It ends by running a container in a microVM, its kernel the guest's, not the host's, with a
# volume. Everything it does is logged to /var/log/repro-kata-setup.log.
set -euo pipefail

DOCKER_VERSION=5:29.8.2-1~ubuntu.24.04~noble
DOCKER_KEY_FINGERPRINT=9DC858229FC7DD38854AE2D88D81803C0EBFCD88
KATA_VERSION=4.2.0
KATA_SHA256=b828904fa3f1e49ddd7dc799c72cb1503cd1e772d354c3987c8d4189b2a623a8

CACHE=/var/cache/repro-kata
KATA_SHIM=/opt/kata/runtime-rs/bin/containerd-shim-kata-v2
KATA_CLH_CONFIG=/opt/kata/share/defaults/kata-containers/runtime-rs/configuration-clh-runtime-rs.toml
SHIM=/usr/local/bin/containerd-shim-kata-clh-v2
TEST_IMAGE=docker.io/library/busybox:1.37.0
LOG=/var/log/repro-kata-setup.log

exec > >(tee -a "$LOG") 2>&1
echo "== repro kata setup (Cloud Hypervisor), $(date -u +%FT%TZ)"

[ "$(id -u)" -eq 0 ] || { echo "run it with sudo"; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "amd64 only"; exit 1; }
[ -c /dev/kvm ] || { echo "no /dev/kvm: this host cannot run microVMs"; exit 1; }
[ "$(ps -p 1 -o comm=)" = systemd ] || { echo "systemd is needed (WSL: [boot] systemd=true)"; exit 1; }
. /etc/os-release
[ "${VERSION_CODENAME:-}" = noble ] || { echo "Ubuntu 24.04 (noble) only: the pins are noble's"; exit 1; }

# The first version of this script (containerd and nerdctl for Firecracker) stopped before it
# configured anything; what it unpacked goes, and Docker's own containerd takes its place.
if [ -f "$CACHE/containerd.tar.gz" ]; then
	echo "== removing the first attempt's containerd and nerdctl"
	rm -f /usr/local/bin/containerd /usr/local/bin/containerd-shim-runc-v2 \
		/usr/local/bin/containerd-stress /usr/local/bin/ctr /usr/local/bin/nerdctl \
		/etc/systemd/system/containerd.service
	rm -rf /opt/cni
	rm -f "$CACHE/containerd.tar.gz" "$CACHE/containerd.service" "$CACHE/nerdctl.tar.gz" "$CACHE/cni.tgz"
	systemctl daemon-reload
fi

echo "== packages"
apt-get update -qq
apt-get install -y -qq zstd ca-certificates curl gnupg >/dev/null

echo "== Docker Engine $DOCKER_VERSION"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
found=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr/ {print $10; exit}')
[ "$found" = "$DOCKER_KEY_FINGERPRINT" ] || { echo "Docker's key is $found, not $DOCKER_KEY_FINGERPRINT"; exit 1; }
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $VERSION_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update -qq
apt-get install -y -qq "docker-ce=$DOCKER_VERSION" "docker-ce-cli=$DOCKER_VERSION" containerd.io \
	docker-buildx-plugin >/dev/null

echo "== Kata Containers $KATA_VERSION (about 1 GB, cached after the first time)"
mkdir -p "$CACHE"
file="$CACHE/kata-static.tar.zst"
if [ ! -f "$file" ] || ! echo "$KATA_SHA256  $file" | sha256sum -c --status; then
	curl -fsSL --retry 3 -o "$file.part" \
		"https://github.com/kata-containers/kata-containers/releases/download/$KATA_VERSION/kata-static-$KATA_VERSION-amd64.tar.zst"
	mv "$file.part" "$file"
fi
echo "$KATA_SHA256  $file" | sha256sum -c --quiet || { echo "Kata: checksum mismatch"; exit 1; }
tar -C / --zstd -xf "$file"
for needed in "$KATA_SHIM" /opt/kata/bin/cloud-hypervisor /opt/kata/libexec/virtiofsd "$KATA_CLH_CONFIG"; do
	[ -e "$needed" ] || { echo "Kata $KATA_VERSION has no $needed"; exit 1; }
done
cat > "$SHIM" <<EOF
#!/bin/bash
# Kata's shim with its shipped Cloud Hypervisor configuration (repro scripts/kata/setup.sh).
KATA_CONF_FILE=$KATA_CLH_CONFIG exec $KATA_SHIM "\$@"
EOF
chmod 0755 "$SHIM"

echo "== Docker's runtime kata"
mkdir -p /etc/docker
python3 - "$SHIM" <<'EOF'
import json, sys
from pathlib import Path
path = Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
config.setdefault("runtimes", {})["kata"] = {"runtimeType": sys.argv[1]}
path.write_text(json.dumps(config, indent=2) + "\n")
EOF
systemctl enable docker.service >/dev/null
systemctl restart docker.service
[ -n "${SUDO_USER:-}" ] && usermod -aG docker "$SUDO_USER"

echo "== a microVM, with a volume"
docker pull -q "$TEST_IMAGE" >/dev/null
guest=$(docker run --rm --runtime kata --network none "$TEST_IMAGE" uname -r)
echo "host kernel:  $(uname -r)"
echo "guest kernel: $guest"
[ -n "$guest" ] && [ "$guest" != "$(uname -r)" ] || { echo "the container did not run in a microVM"; exit 1; }
docker volume rm -f repro-kata-check >/dev/null 2>&1 || true
docker volume create repro-kata-check >/dev/null
shared=$(docker run --rm --runtime kata --network none -v repro-kata-check:/w "$TEST_IMAGE" \
	sh -c 'echo shared > /w/f && cat /w/f')
docker volume rm -f repro-kata-check >/dev/null
[ "$shared" = shared ] || { echo "the microVM could not use a volume"; exit 1; }
echo "volume: ok"
echo "== done: Docker runs containers in Kata microVMs here (runtime kata). Log: $LOG"
echo "   ${SUDO_USER:-your user} is in docker: run 'wsl --shutdown' (or log in again) for it to apply."
