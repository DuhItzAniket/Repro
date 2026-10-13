"""A08 spike: Docker sandbox round trip (ADR-0004 layer L3).

Builds the honest-fix fixture, exports a .git-less snapshot of head, and times each step of:
  copy snapshot into a fresh volume -> provision a venv (network on, index only in principle)
  -> run pytest with --network none and a hardened container -> prove network is blocked
  -> collect JUnit -> remove the volume.

Usage (from the repository root):  uv run python spikes/A08/sandbox_roundtrip.py --repeats 3
Requires Docker. The uv image is pinned by digest in IMAGE.
"""

import argparse
import io
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "tests"))
from fixtures.repo_builder import build_repo
from fixtures.specs import HONEST_FIX

IMAGE = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
PROVISION = "uv venv -q /work/.venv && uv pip install -q --python /work/.venv/bin/python pytest"
HARDENED = [
    "--network", "none",
    "--read-only",
    "--tmpfs", "/tmp:rw,exec,size=64m",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--user", "1000:1000",
    "--pids-limit", "256",
    "--memory", "1g",
    "--cpus", "2",
    "-e", "PYTHONDONTWRITEBYTECODE=1",
    "-e", "HOME=/tmp",
]  # fmt: skip
NETWORK_PROBE = (
    "import socket\n"
    "for target in [('1.1.1.1', 443), ('pypi.org', 443)]:\n"
    "    try:\n"
    "        socket.create_connection(target, timeout=3).close()\n"
    "        print('REACHABLE', target)\n"
    "    except OSError as exc:\n"
    "        print('BLOCKED', target, type(exc).__name__, exc)\n"
)


def docker(
    *args: str, stdin: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, check=check)


def snapshot_tar(repo: Path, ref: str) -> bytes:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", ref], cwd=repo, capture_output=True, check=True
    ).stdout
    # Add a world-writable output directory for the unprivileged test run.
    buffer = io.BytesIO(archive)
    out = io.BytesIO()
    with tarfile.open(fileobj=buffer) as src, tarfile.open(fileobj=out, mode="w") as dst:
        for member in src.getmembers():
            dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        info = tarfile.TarInfo("out")
        info.type = tarfile.DIRTYPE
        info.mode = 0o777
        dst.addfile(info)
    return out.getvalue()


def timed(step: str, timings: dict[str, float], fn: Any) -> Any:
    start = time.perf_counter()
    result = fn()
    timings[step] = round(time.perf_counter() - start, 3)
    return result


def round_trip(snapshot: bytes) -> dict[str, Any]:
    volume = f"repro-spike-{uuid.uuid4().hex[:8]}"
    timings: dict[str, float] = {}
    try:
        timed("volume_create", timings, lambda: docker("volume", "create", volume))
        timed(
            "snapshot_copy",
            timings,
            lambda: docker(
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
            ),
        )
        timed(
            "provision",
            timings,
            lambda: docker(
                "run",
                "--rm",
                "-v",
                f"{volume}:/work",
                "-e",
                "UV_LINK_MODE=copy",
                IMAGE,
                "sh",
                "-c",
                PROVISION,
            ),
        )
        tests = timed(
            "test_run_sandboxed",
            timings,
            lambda: docker(
                "run",
                "--rm",
                *HARDENED,
                "-v",
                f"{volume}:/work",
                "-w",
                "/work",
                IMAGE,
                "/work/.venv/bin/python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--junitxml=/work/out/junit.xml",
                "tests",
                check=False,
            ),
        )
        probe = timed(
            "network_probe",
            timings,
            lambda: docker(
                "run", "--rm", *HARDENED, IMAGE, "python", "-c", NETWORK_PROBE, check=False
            ),
        )
        junit = timed(
            "collect_junit",
            timings,
            lambda: docker(
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{volume}:/work:ro",
                IMAGE,
                "cat",
                "/work/out/junit.xml",
            ),
        )
    finally:
        timed("volume_remove", timings, lambda: docker("volume", "rm", "-f", volume, check=False))
    return {
        "timings_s": timings,
        "total_s": round(sum(timings.values()), 3),
        "pytest_exit_code": tests.returncode,
        "pytest_summary": tests.stdout.decode().strip().splitlines()[-1:],
        "junit_bytes": len(junit.stdout),
        "network_probe": probe.stdout.decode().strip().splitlines(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    pull_start = time.perf_counter()
    docker("pull", "-q", IMAGE)
    pull_s = round(time.perf_counter() - pull_start, 3)
    digest = (
        docker("image", "inspect", IMAGE, "--format", "{{index .RepoDigests 0}}")
        .stdout.decode()
        .strip()
    )
    server = (
        docker("version", "--format", "{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}")
        .stdout.decode()
        .strip()
    )
    with tempfile.TemporaryDirectory() as tmp:
        built = build_repo(HONEST_FIX, Path(tmp) / "repo")
        snapshot = snapshot_tar(built.path, built.head_shas["fix/parse-date-utc"])
    runs = [round_trip(snapshot) for _ in range(args.repeats)]
    result = {
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "docker_server": server,
        "image": digest,
        "image_pull_s": pull_s,
        "snapshot_bytes": len(snapshot),
        "runs": runs,
    }
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
