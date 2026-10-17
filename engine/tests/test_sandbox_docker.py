"""The container sandbox, L3 (D02).

Roadmap D02: "escape suite (raw `_socket`, `ctypes`, subprocess `curl`, writes outside the work
dir, host `.git` tampering) is blocked at L3. The card reports `network: enforced` only here."

These tests need Docker with Linux containers. They are skipped where it is missing, except
where ``REPRO_REQUIRE_DOCKER=1`` (CI's Linux job), where its absence is a failure. With
``REPRO_DOCKER_RUNTIME=runsc`` (CI's gVisor job), every container here runs under gVisor, L4
(H03): the same escapes must be blocked there too.
"""

import hashlib
import os
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gitrepo import Entry, Repo
from repro.gitops import Git
from repro.sandbox import MIB, Limits, SandboxError
from repro.sandbox.docker import GVISOR, DockerSandbox, docker_available
from repro_events.models import SandboxReadyPayload

if not docker_available():
    if os.environ.get("REPRO_REQUIRE_DOCKER") == "1":
        raise RuntimeError(
            "REPRO_REQUIRE_DOCKER=1, but Docker with Linux containers is not available"
        )
    pytest.skip("Docker with Linux containers is not available", allow_module_level=True)

#: The containers' runtime: unset (Docker's default, L3) or gVisor's (L4).
RUNTIME = os.environ.get("REPRO_DOCKER_RUNTIME") or None
LEVEL = "L4" if RUNTIME == GVISOR else "L3"


ESCAPES = {
    # Each prints one line: "blocked: ..." or "ESCAPED: ...".
    "raw_socket.py": """
        import _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect(("1.1.1.1", 443))
            print("ESCAPED: raw _socket connected")
        except OSError as exc:
            print(f"blocked: raw _socket: {exc.errno}")
    """,
    "ctypes_socket.py": """
        import ctypes, ctypes.util, socket, struct
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        address = struct.pack("!HH4s8x", socket.AF_INET, 443, socket.inet_aton("1.1.1.1"))
        result = libc.connect(fd, address, len(address))  # no Python audit event: unseen by L1
        if result == 0:
            print("ESCAPED: libc connect succeeded")
        else:
            print(f"blocked: libc connect: errno {ctypes.get_errno()}")
    """,
    "subprocess_network.py": """
        import shutil, subprocess, sys
        fetch = "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)"
        if shutil.which("curl"):
            command = ["curl", "-sS", "--max-time", "5", "https://pypi.org"]
        else:  # the image has no curl: a separate Python process instead
            command = [sys.executable, "-c", fetch]
        done = subprocess.run(command, capture_output=True, text=True)
        print("ESCAPED: subprocess reached the network" if done.returncode == 0
              else f"blocked: subprocess network: exit {done.returncode}")
    """,
    "write_outside.py": """
        failures = []
        for path in ("/etc/repro-escape", "/usr/local/lib/repro-escape", "/opt/repro/hook/x.py",
                     "/root/repro-escape"):
            try:
                open(path, "w").write("x")
                failures.append(path)
            except OSError:
                pass
        print(f"ESCAPED: wrote {failures}" if failures else "blocked: writes outside")
    """,
    "host_git.py": """
        import os
        found = [os.path.join(root, ".git") for root, dirs, _ in os.walk("/")
                 if ".git" in dirs and not root.startswith(("/proc", "/sys"))]
        print(f"ESCAPED: a .git is reachable: {found}" if found else "blocked: no .git anywhere")
    """,
    # H03: the rest of the escape suite.
    "become_root.py": """
        import os
        try:
            os.setuid(0)
            print("ESCAPED: became root")
        except PermissionError as exc:
            print(f"blocked: setuid: {exc.errno}")
    """,
    "raw_socket_capability.py": """
        import socket
        try:
            socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            print("ESCAPED: opened a raw socket")
        except OSError as exc:
            print(f"blocked: raw socket: {exc.errno}")
    """,
    "mount.py": """
        import ctypes, ctypes.util, os
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        target = "/tmp/repro-mount"
        os.makedirs(target, exist_ok=True)
        result = libc.mount(b"none", target.encode(), b"tmpfs", 0, None)
        print("ESCAPED: mounted a filesystem" if result == 0
              else f"blocked: mount: errno {ctypes.get_errno()}")
    """,
    "docker_socket.py": """
        import os
        found = [p for p in ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd")
                 if os.path.exists(p)]
        print(f"ESCAPED: {found}" if found else "blocked: no container engine socket")
    """,
    "kernel_settings.py": """
        try:
            with open("/proc/sys/kernel/hostname", "w") as handle:
                handle.write("escaped")
            print("ESCAPED: wrote a kernel setting")
        except OSError as exc:
            print(f"blocked: /proc/sys: {exc.errno}")
    """,
    "kernel_devices.py": """
        opened = []
        for device in ("/dev/mem", "/dev/kmem", "/dev/sda", "/dev/kmsg"):
            try:
                open(device, "rb").close()
                opened.append(device)
            except OSError:
                pass
        print(f"ESCAPED: opened {opened}" if opened else "blocked: no kernel devices")
    """,
    "host_environment.py": """
        import os
        seen = sorted(k for k in os.environ if k.startswith("REPRO_ESCAPE_"))
        print(f"ESCAPED: saw {seen}" if seen else "blocked: no host variables")
    """,
}


@dataclass(frozen=True)
class Target:
    box: DockerSandbox
    host_git: Path  # the repository's own .git, on the host


@pytest.fixture(scope="module")
def target(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Target]:
    root = tmp_path_factory.mktemp("docker")
    repo = Repo(root / "repo")
    files: dict[str, Entry] = {
        f"escapes/{name}": textwrap.dedent(body) for name, body in ESCAPES.items()
    }
    files["run.sh"] = ("#!/bin/sh\necho executable\n", "100755")
    files["link-to-run"] = ("run.sh", "120000")
    sha = repo.commit(files)
    limits = Limits(timeout_s=60, memory_bytes=512 * MIB)
    with DockerSandbox(root / "work", Git(repo.path), sha, limits=limits, runtime=RUNTIME) as box:
        yield Target(box, repo.path / ".git")


@pytest.fixture
def box(target: Target) -> DockerSandbox:
    return target.box


def git_fingerprint(git_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(git_dir.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(git_dir).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize("escape", sorted(ESCAPES))
def test_the_escape_suite_is_blocked(
    target: Target, escape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPRO_ESCAPE_SECRET", "s3cr3t")  # the host's: host_environment.py looks
    before = git_fingerprint(target.host_git)
    run = target.box.run(["python", f"escapes/{escape}"])
    output = run.stdout.decode().strip()
    assert run.returncode == 0, run.stderr.decode()
    assert output.startswith("blocked:"), output
    assert git_fingerprint(target.host_git) == before


def test_blocked_attempts_are_still_detected(box: DockerSandbox) -> None:
    run = box.run(["python", "escapes/raw_socket.py"])
    assert [(d.kind, d.detail) for d in run.detections.items] == [("network", "1.1.1.1:443")]


def test_the_container_is_hardened(box: DockerSandbox) -> None:
    probe = (
        "import os; status = open('/proc/self/status').read();"
        "field = lambda name: status.split(name + ':')[1].split()[0];"
        "print(os.getuid(), field('CapEff'), field('NoNewPrivs'))"
    )
    run = box.run(["python", "-c", probe])
    uid, capabilities, no_new_privileges = run.stdout.decode().split()
    assert (uid, capabilities, no_new_privileges) == ("1000", "0000000000000000", "1")


def test_files_keep_their_modes_and_links_and_tmp_is_executable(box: DockerSandbox) -> None:
    run = box.run(["sh", "-c", "./run.sh && readlink link-to-run && cp run.sh /tmp/x && /tmp/x"])
    assert run.stdout.decode().split() == ["executable", "run.sh", "executable"]


def test_the_work_directory_persists_across_runs(box: DockerSandbox) -> None:
    box.run(["sh", "-c", "mkdir -p out && echo kept > out/result.txt"])
    assert box.read_file("out/result.txt") == b"kept\n"
    assert box.read_file("out/missing.txt") is None


def test_a_timeout_kills_the_container(box: DockerSandbox) -> None:
    run = box.run(["sleep", "60"], timeout_s=3)
    assert run.outcome == "timeout"
    assert run.duration_s < 30


def test_a_memory_hog_is_killed(box: DockerSandbox) -> None:
    run = box.run(["python", "-c", "x = bytearray(2 * 1024 ** 3)"])  # 2 GiB against 512 MiB
    assert run.outcome == "exited"
    assert run.returncode != 0
    # The allocation fails (MemoryError) or the kernel kills the process (SIGKILL: 128 + 9).
    # Docker's OOMKilled flag says so too, but not every time: E05's CI run had exit 137
    # with the flag false. The sandbox itself kills only on a timeout or a stop, which are
    # other outcomes, so an exited run's 137 is the kernel's.
    assert run.oom_killed or run.returncode == 137 or b"MemoryError" in run.stderr


def test_a_fork_bomb_meets_the_pids_limit(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "repo")
    bomb = textwrap.dedent(
        """
        import os, subprocess, sys, time
        depth = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        with open("/work/started.txt", "a") as log:
            log.write(f"{os.getpid()}\\n")
        if depth < 6:  # at most 127 processes, even with no limit at all
            for _ in range(2):
                try:
                    subprocess.Popen([sys.executable, __file__, str(depth + 1)])
                except OSError:
                    pass
        time.sleep(60)
        """
    )
    sha = repo.commit({"bomb.py": bomb})
    limit = 16
    with DockerSandbox(
        tmp_path / "work", Git(repo.path), sha, limits=Limits(processes=limit), runtime=RUNTIME
    ) as box:
        run = box.run(["python", "bomb.py"], timeout_s=15)
        started = (box.read_file("started.txt") or b"").split()
    assert 1 <= len(started) <= limit
    if RUNTIME == GVISOR:
        # Under gVisor the limit counts the sandbox's own threads too, and reaching it ends the
        # whole container (measured on CI's gvisor job, H03): contained, but not by a timeout.
        assert run.outcome == "timeout" or run.returncode != 0, run
    else:  # runc: the forks fail, and the bomb sleeps on until its timeout
        assert run.outcome == "timeout"


def test_the_ready_payload_reports_the_network_enforced(box: DockerSandbox) -> None:
    payload = box.ready_payload("base")
    SandboxReadyPayload.model_validate(payload)
    assert (payload["isolation_level"], payload["network"]) == (LEVEL, "enforced")
    assert (f"runtime {RUNTIME}" in payload["platform"]) == (RUNTIME is not None)


def test_a_runtime_docker_does_not_have_is_refused_before_anything_starts(tmp_path: Path) -> None:
    """H03: a card never claims gVisor's layer without it; a missing runtime is an error."""
    repo = Repo(tmp_path / "repo")
    sha = repo.commit({"a.txt": "a"})
    with pytest.raises(SandboxError, match="Docker has no runtime 'no-such-runtime'"):
        DockerSandbox(tmp_path / "work", Git(repo.path), sha, runtime="no-such-runtime")


@pytest.mark.skipif(RUNTIME != GVISOR, reason="gVisor's runtime is not in use (CI's gVisor job)")
def test_commands_run_under_gvisor(box: DockerSandbox) -> None:
    """The kernel the target sees is gVisor's, not the host's."""
    run = box.run(["sh", "-c", "dmesg 2>/dev/null | head -n 3; uname -r"])
    assert run.returncode == 0, run.stderr
    assert b"gVisor" in run.stdout, run.stdout


def test_paths_outside_the_snapshot_are_refused(box: DockerSandbox) -> None:
    with pytest.raises(SandboxError, match="outside the snapshot"):
        box.run(["true"], cwd="../etc")
