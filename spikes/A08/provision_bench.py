"""A08 spike: provisioning a real project's environment inside a container, cold vs warm.

Project: pallets/click at a pinned tag (BSD-3-Clause, uv.lock, offline test suite).
The repository is cloned on the host but never executed there: only `git archive` runs on the
host, and every install and test runs inside containers.

Scenarios, each with a fresh project volume:
  cold          empty uv cache volume, network on
  warm          the same cache volume again, network on
  warm_offline  the same cache volume, --network none and UV_OFFLINE=1 (the D03 target design)
Then the full test suite runs in the hardened, network-less container.

Usage (from the repository root):  uv run python spikes/A08/provision_bench.py
"""

import json
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPO = "https://github.com/pallets/click"
TAG = "8.5.0"
IMAGE = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
SYNC = "uv sync --locked --no-default-groups --group tests --link-mode copy"
HARDENED = [
    "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,exec,size=256m", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--user", "1000:1000", "--pids-limit", "512",
    "--memory", "2g", "--cpus", "4", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
]  # fmt: skip


def run(
    *args: str, stdin: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(list(args), input=stdin, capture_output=True, check=check)


def seconds(fn: Any) -> tuple[float, Any]:
    start = time.perf_counter()
    result = fn()
    return round(time.perf_counter() - start, 3), result


def scenario(name: str, snapshot: bytes, cache: str, *, offline: bool) -> dict[str, Any]:
    volume = f"repro-spike-{uuid.uuid4().hex[:8]}"
    out: dict[str, Any] = {"scenario": name}
    try:
        run("docker", "volume", "create", volume)
        out["snapshot_copy_s"], _ = seconds(
            lambda: run(
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "-v",
                f"{volume}:/work",
                IMAGE,
                "tar",
                "-x",
                "-C",
                "/work",
                stdin=snapshot,
            )
        )
        network = ["--network", "none", "-e", "UV_OFFLINE=1"] if offline else []
        out["provision_s"], provision = seconds(
            lambda: run(
                "docker",
                "run",
                "--rm",
                *network,
                "-v",
                f"{volume}:/work",
                "-v",
                f"{cache}:/cache",
                "-e",
                "UV_CACHE_DIR=/cache",
                "-w",
                "/work",
                IMAGE,
                "sh",
                "-c",
                SYNC,
                check=False,
            )
        )
        out["provision_exit"] = provision.returncode
        if provision.returncode != 0:
            out["provision_error"] = provision.stderr.decode()[-800:]
            return out
        out["test_run_s"], tests = seconds(
            lambda: run(
                "docker",
                "run",
                "--rm",
                *HARDENED,
                "-v",
                f"{volume}:/work:ro",
                "-w",
                "/work",
                IMAGE,
                "/work/.venv/bin/python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp=/tmp/pytest",
                "tests",
                check=False,
            )
        )
        out["pytest_exit"] = tests.returncode
        out["pytest_summary"] = tests.stdout.decode().strip().splitlines()[-1:]
    finally:
        run("docker", "volume", "rm", "-f", volume, check=False)
    return out


def main() -> int:
    run("docker", "pull", "-q", IMAGE)
    digest = (
        run("docker", "image", "inspect", IMAGE, "--format", "{{index .RepoDigests 0}}")
        .stdout.decode()
        .strip()
    )
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "click"
        clone_s, _ = seconds(
            lambda: run("git", "clone", "-q", "--depth", "1", "--branch", TAG, REPO, str(clone))
        )
        commit = run("git", "-C", str(clone), "rev-parse", "HEAD").stdout.decode().strip()
        snapshot = run("git", "-C", str(clone), "archive", "--format=tar", "HEAD").stdout
        files = len(run("git", "-C", str(clone), "ls-files").stdout.splitlines())
    cache = f"repro-spike-cache-{uuid.uuid4().hex[:8]}"
    run("docker", "volume", "create", cache)
    try:
        results = [
            scenario("cold", snapshot, cache, offline=False),
            scenario("warm", snapshot, cache, offline=False),
            scenario("warm_offline", snapshot, cache, offline=True),
        ]
    finally:
        run("docker", "volume", "rm", "-f", cache, check=False)
    report = {
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "image": digest,
        "project": {
            "repo": REPO,
            "tag": TAG,
            "commit": commit,
            "files": files,
            "snapshot_bytes": len(snapshot),
        },
        "clone_s": clone_s,
        "sync_command": SYNC,
        "scenarios": results,
    }
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
