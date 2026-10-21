#!/usr/bin/env bash
# K10: a containerd host whose containers can run in Firecracker microVMs (Kata Containers),
# for Repro's Kata sandbox (ADR-0018, option C). Linux with KVM only; WSL2 with nested
# virtualization works (Windows 11's default). Run once, as root:
#
#     sudo bash scripts/kata/setup.sh
#
# What it installs, each pinned by version and SHA-256 (the release's published checksum, equal
# to GitHub's asset digest, both read on 2026-10-21):
# - containerd 2.4.2 and its systemd unit;
# - nerdctl 2.4.1, and the CNI plugins 1.9.1 (networks for the install containers);
# - Kata Containers 4.2.0's static release (its runtime, guest kernel and image, Firecracker
#   v1.12.1 and the jailer, as its versions.yaml pins them), under /opt/kata.
# Then, as Kata's guide to Firecracker says for 4.2.0
# (docs/how-to/how-to-use-kata-containers-with-firecracker.md):
# - a devmapper thin-pool on two sparse files (100 GB of data, 10 GB of metadata; they use
#   only what is written), re-created at each boot by a systemd unit;
# - containerd's devmapper snapshotter on that pool;
# - the shim `containerd-shim-kata-fc-v2`, Kata's shim with its shipped Firecracker
#   configuration.
# The containerd socket's group is `repro-sandbox`, and the user who ran sudo joins it: like
# Docker's group, membership is control of the containers, so of this machine's root.
#
# It ends by starting a microVM: a container whose kernel is the guest's, not the host's.
# Everything it does is logged to /var/log/repro-kata-setup.log.
set -euo pipefail

CONTAINERD_VERSION=2.4.2
CONTAINERD_SHA256=35880c1dd4627e8ce56526bfabb39c144e83458ffdb197ce6f05d17d94d7d91e
CONTAINERD_UNIT_SHA256=1941362cbaa89dd591b99c32b050d82c583d3cd2e5fa63085d7017457ec5fca8
NERDCTL_VERSION=2.4.1
NERDCTL_SHA256=f6bbf02fd8a299cbcbc71a0bad113c1b63b3f33689bbb7d51b0fa98c6d361d5e
CNI_VERSION=1.9.1
CNI_SHA256=b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303
KATA_VERSION=4.2.0
KATA_SHA256=b828904fa3f1e49ddd7dc799c72cb1503cd1e772d354c3987c8d4189b2a623a8

CACHE=/var/cache/repro-kata
POOL_DIR=/var/lib/containerd/devmapper
POOL_NAME=devpool
GROUP=repro-sandbox
KATA_FC_CONFIG=/opt/kata/share/defaults/kata-containers/configuration-fc.toml
LOG=/var/log/repro-kata-setup.log

exec > >(tee -a "$LOG") 2>&1
echo "== repro kata setup, $(date -u +%FT%TZ)"

[ "$(id -u)" -eq 0 ] || { echo "run it with sudo"; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "amd64 only: Kata's Firecracker shim is"; exit 1; }
[ -c /dev/kvm ] || { echo "no /dev/kvm: this host cannot run microVMs"; exit 1; }
[ "$(ps -p 1 -o comm=)" = systemd ] || { echo "systemd is needed (WSL: [boot] systemd=true)"; exit 1; }

echo "== packages"
apt-get update -qq
apt-get install -y -qq zstd dmsetup iptables curl ca-certificates >/dev/null

fetch() { # url sha256 name
	mkdir -p "$CACHE"
	local file="$CACHE/$3"
	if [ ! -f "$file" ] || ! echo "$2  $file" | sha256sum -c --status; then
		echo "fetching $3"
		curl -fsSL --retry 3 -o "$file.part" "$1"
		mv "$file.part" "$file"
	fi
	echo "$2  $file" | sha256sum -c --quiet || { echo "$3: checksum mismatch"; exit 1; }
}

echo "== containerd $CONTAINERD_VERSION"
fetch "https://github.com/containerd/containerd/releases/download/v$CONTAINERD_VERSION/containerd-$CONTAINERD_VERSION-linux-amd64.tar.gz" \
	"$CONTAINERD_SHA256" containerd.tar.gz
tar -C /usr/local -xzf "$CACHE/containerd.tar.gz"
fetch "https://raw.githubusercontent.com/containerd/containerd/v$CONTAINERD_VERSION/containerd.service" \
	"$CONTAINERD_UNIT_SHA256" containerd.service
install -m 0644 "$CACHE/containerd.service" /etc/systemd/system/containerd.service

echo "== nerdctl $NERDCTL_VERSION, CNI plugins $CNI_VERSION"
fetch "https://github.com/containerd/nerdctl/releases/download/v$NERDCTL_VERSION/nerdctl-$NERDCTL_VERSION-linux-amd64.tar.gz" \
	"$NERDCTL_SHA256" nerdctl.tar.gz
tar -C /usr/local/bin -xzf "$CACHE/nerdctl.tar.gz" nerdctl
fetch "https://github.com/containernetworking/plugins/releases/download/v$CNI_VERSION/cni-plugins-linux-amd64-v$CNI_VERSION.tgz" \
	"$CNI_SHA256" cni.tgz
mkdir -p /opt/cni/bin
tar -C /opt/cni/bin -xzf "$CACHE/cni.tgz"

echo "== Kata Containers $KATA_VERSION (about 1 GB)"
fetch "https://github.com/kata-containers/kata-containers/releases/download/$KATA_VERSION/kata-static-$KATA_VERSION-amd64.tar.zst" \
	"$KATA_SHA256" kata-static.tar.zst
tar -C / --zstd -xf "$CACHE/kata-static.tar.zst"
for needed in /opt/kata/bin/containerd-shim-kata-v2 /opt/kata/bin/firecracker /opt/kata/bin/jailer "$KATA_FC_CONFIG"; do
	[ -e "$needed" ] || { echo "Kata $KATA_VERSION has no $needed"; exit 1; }
done
cat > /usr/local/bin/containerd-shim-kata-fc-v2 <<EOF
#!/bin/bash
# Kata's shim with its shipped Firecracker configuration (repro scripts/kata/setup.sh).
KATA_CONF_FILE=$KATA_FC_CONFIG exec /opt/kata/bin/containerd-shim-kata-v2 "\$@"
EOF
chmod 0755 /usr/local/bin/containerd-shim-kata-fc-v2

echo "== devmapper thin-pool $POOL_NAME"
cat > /usr/local/sbin/repro-devpool <<EOF
#!/bin/bash
# The thin-pool containerd's devmapper snapshotter uses, from its sparse files
# (repro scripts/kata/setup.sh, after Kata's guide to Firecracker).
set -euo pipefail
dmsetup status "$POOL_NAME" >/dev/null 2>&1 && exit 0
mkdir -p "$POOL_DIR"
[ -f "$POOL_DIR/data" ] || truncate -s 100G "$POOL_DIR/data"
[ -f "$POOL_DIR/meta" ] || truncate -s 10G "$POOL_DIR/meta"
data=\$(losetup --find --show "$POOL_DIR/data")
meta=\$(losetup --find --show "$POOL_DIR/meta")
sectors=\$(( \$(blockdev --getsize64 "\$data") / 512 ))
dmsetup create "$POOL_NAME" --table "0 \$sectors thin-pool \$meta \$data 128 32768"
EOF
chmod 0755 /usr/local/sbin/repro-devpool
cat > /etc/systemd/system/repro-devpool.service <<EOF
[Unit]
Description=The devmapper thin-pool for containerd (repro)
Before=containerd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/repro-devpool

[Install]
WantedBy=multi-user.target
EOF

echo "== containerd's configuration"
getent group "$GROUP" >/dev/null || groupadd "$GROUP"
[ -n "${SUDO_USER:-}" ] && usermod -aG "$GROUP" "$SUDO_USER"
mkdir -p /etc/containerd
cat > /etc/containerd/config.toml <<EOF
# repro scripts/kata/setup.sh: the devmapper snapshotter Kata's Firecracker needs, and a socket
# the group $GROUP may use.
version = 3

[grpc]
  gid = $(getent group "$GROUP" | cut -d: -f3)

[plugins.'io.containerd.snapshotter.v1.devmapper']
  pool_name = "$POOL_NAME"
  root_path = "$POOL_DIR"
  base_image_size = "10GB"
  discard_blocks = true
EOF

systemctl daemon-reload
systemctl enable --now repro-devpool.service
systemctl enable containerd.service
systemctl restart containerd.service
sleep 2
/usr/local/bin/ctr plugins ls | grep devmapper | grep -q ok || { echo "the devmapper snapshotter is not ok"; exit 1; }

echo "== a microVM"
nerdctl --snapshotter devmapper pull -q docker.io/library/busybox:1.37.0
guest=$(nerdctl --snapshotter devmapper run --rm --network none \
	--runtime io.containerd.kata-fc.v2 docker.io/library/busybox:1.37.0 uname -r)
echo "host kernel:  $(uname -r)"
echo "guest kernel: $guest"
[ -n "$guest" ] && [ "$guest" != "$(uname -r)" ] || { echo "the container did not run in a microVM"; exit 1; }
echo "== done: Firecracker microVMs run here. Log: $LOG"
echo "   ${SUDO_USER:-your user} is in $GROUP: open a new shell (or wsl --shutdown) for it to apply."
