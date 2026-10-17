"""The process sandbox, L0 to L2 (D01).

Roadmap D01: "fork-bomb, memory-hog and timeout fixtures are contained. Detected network and
subprocess attempts become evidence". Every hostile fixture is bounded, so that a containment
failure cannot take the machine running the tests down with it.
"""

import io
import json
import os
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

from repro.bus import EventBus
from repro.sandbox import (
    MIB,
    Detection,
    Limits,
    ProcessSandbox,
    SandboxError,
    containment,
    detection_evidence,
    read_detections,
)
from repro.sandbox.detect import HOOK_DIR
from repro.sandbox.docker import hook_archive
from repro_events.models import Evidence, SandboxReadyPayload
from store_support import run_record, started_writer

PY = sys.executable


if sys.platform == "win32":
    import ctypes

    _SYNCHRONIZE = 0x00100000
    _WAIT_TIMEOUT = 0x102

    def alive(pid: int) -> bool:
        """Whether the process is still running (its handle is not signalled yet)."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return int(kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0)) == _WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

else:

    def alive(pid: int) -> bool:
        """Whether the process still exists (a zombie counts until it is reaped)."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def gone(pids: list[int], within_s: float = 10) -> bool:
    """Whether every process has ended (a killed POSIX process lingers until it is reaped)."""
    deadline = time.monotonic() + within_s
    while any(alive(pid) for pid in pids):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def script(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    directory = tmp_path / "snapshot"
    directory.mkdir()
    return directory


@pytest.fixture
def box(tmp_path: Path) -> ProcessSandbox:
    return ProcessSandbox(tmp_path / "work", Limits(timeout_s=60))


def test_a_command_sees_a_minimal_environment(
    box: ProcessSandbox, cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPRO_TEST_SECRET", "s3cr3t")  # a host variable it must not see
    show = script(cwd / "env.py", "import json, os\nprint(json.dumps(dict(os.environ)))\n")
    run = box.run([PY, str(show)], cwd=cwd, env={"EXTRA": "1"})
    env = json.loads(run.stdout)
    assert run.outcome == "exited"
    assert run.returncode == 0
    assert "REPRO_TEST_SECRET" not in env
    assert env["EXTRA"] == "1"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(HOOK_DIR)
    home = Path(env["HOME"])
    assert home.is_relative_to(box.work)
    assert Path(env["TMPDIR"]).is_relative_to(box.work)


def test_network_subprocess_and_file_attempts_are_detected(
    box: ProcessSandbox, cwd: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    attempt = script(
        cwd / "attempt.py",
        f"""
        import socket, subprocess, sys
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 9))
        except OSError:
            pass
        subprocess.run([sys.executable, "-c", "pass"])
        open({str(outside)!r}, "w").write("x")
        open("inside.txt", "w").write("y")
        """,
    )
    run = box.run([PY, str(attempt)], cwd=cwd)
    assert run.returncode == 0, run.stderr
    found = {(d.kind, d.event) for d in run.detections.items}
    assert {
        ("network", "socket.connect"),
        ("subprocess", "subprocess.Popen"),
        ("file", "open"),
    } <= found  # a platform may also report its own spawn call (os.posix_spawn)
    (network,) = [d for d in run.detections.items if d.kind == "network"]
    assert network.detail == "127.0.0.1:9"
    (written,) = [d for d in run.detections.items if d.kind == "file"]
    assert written.detail == str(outside)  # inside.txt, in its own directory, is not reported


def directory_link(link: Path, target: Path) -> None:
    """A link to a directory that needs no privilege: a junction on Windows, else a symlink."""
    if sys.platform == "win32":
        import _winapi  # noqa: PLC0415 - Windows only

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_write_is_judged_by_where_its_path_resolves(
    box: ProcessSandbox, cwd: Path, tmp_path: Path
) -> None:
    """H03: a link inside the run's directory that leads out is a write outside; a path from
    outside that leads in, as a redirected folder does, is not."""
    outside = tmp_path / "outside"
    outside.mkdir()
    directory_link(cwd / "leads-out", outside)
    directory_link(tmp_path / "leads-in", cwd)
    escape, inside = cwd / "leads-out" / "x.txt", tmp_path / "leads-in" / "y.txt"
    attempt = script(
        cwd / "write.py",
        f"open({str(escape)!r}, 'w').write('x')\nopen({str(inside)!r}, 'w').write('y')\n",
    )
    run = box.run([PY, str(attempt)], cwd=cwd)
    assert run.returncode == 0, run.stderr
    assert (outside / "x.txt").is_file()
    assert (cwd / "y.txt").is_file()
    written = [d.detail for d in run.detections.items if d.kind == "file"]
    assert written == [str(escape)]


def test_the_environments_own_sitecustomize_still_runs(
    box: ProcessSandbox, cwd: Path, tmp_path: Path
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    script(site / "sitecustomize.py", "print('its own sitecustomize ran')\n")
    run = box.run([PY, "-c", "print('main')"], cwd=cwd, env={"PYTHONPATH": str(site)})
    assert run.stdout.decode().split() == ["its", "own", "sitecustomize", "ran", "main"]


def test_a_timeout_kills_the_whole_tree(box: ProcessSandbox, cwd: Path) -> None:
    sleeper = script(
        cwd / "sleeper.py",
        """
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open("child.pid", "w").write(str(child.pid))
        time.sleep(60)
        """,
    )
    started = time.monotonic()
    run = box.run([PY, str(sleeper)], cwd=cwd, timeout_s=3)
    assert run.outcome == "timeout"
    assert run.returncode is None
    assert time.monotonic() - started < 30
    assert gone([int((cwd / "child.pid").read_text())])


def test_processes_left_running_are_killed_and_reported(box: ProcessSandbox, cwd: Path) -> None:
    leaver = script(
        cwd / "leaver.py",
        """
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open("child.pid", "w").write(str(child.pid))
        """,
    )
    run = box.run([PY, str(leaver)], cwd=cwd)
    assert (run.outcome, run.returncode) == ("exited", 0)
    assert run.left_running
    assert gone([int((cwd / "child.pid").read_text())])


def test_a_memory_hog_is_contained(tmp_path: Path, cwd: Path) -> None:
    box = ProcessSandbox(tmp_path / "work", Limits(timeout_s=60, memory_bytes=512 * MIB))
    hog = script(
        cwd / "hog.py",
        """
        blocks = []
        for _ in range(64):
            blocks.append(bytearray(64 * 1024 * 1024))  # 4 GiB in all, if nothing stops it
        print("allocated everything")
        """,
    )
    run = box.run([PY, str(hog)], cwd=cwd)
    assert run.outcome == "exited"
    assert run.returncode != 0
    assert b"MemoryError" in run.stderr
    assert b"allocated everything" not in run.stdout
    if run.peak_memory_bytes is not None:  # Windows: the job's own measure
        # Far below the 4 GiB asked for. It may pass the limit by what the process committed
        # while suspended, before it joined the job: "Memory operations performed by the
        # process before it was associated with the job are not examined" (Microsoft Learn,
        # AssignProcessToJobObject). About 9 MiB was measured here.
        assert run.peak_memory_bytes <= 512 * MIB + 64 * MIB


def test_a_fork_bomb_is_contained(tmp_path: Path, cwd: Path) -> None:
    limit = 12
    box = ProcessSandbox(tmp_path / "work", Limits(timeout_s=20, processes=limit))
    bomb = script(
        cwd / "bomb.py",
        """
        import os, subprocess, sys, time
        depth = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        with open("started.txt", "a") as log:
            log.write(f"{os.getpid()}\\n")
        children = []
        if depth < 6:  # at most 127 processes, even with no containment at all
            for _ in range(2):
                try:
                    children.append(subprocess.Popen([sys.executable, __file__, str(depth + 1)]))
                except OSError:
                    pass  # refused: the limit at work
        time.sleep(60)
        """,
    )
    run = box.run([PY, str(bomb)], cwd=cwd)
    assert run.outcome == "timeout"
    started = [int(line) for line in (cwd / "started.txt").read_text().split()]
    # Unbounded, 127 would start. Windows caps the job's processes exactly (and each Python
    # start from a virtual environment is two: its launcher and the interpreter). Linux caps
    # the threads the user may add, so others coming and going shift the count a little.
    bound = limit if sys.platform == "win32" else 2 * limit
    assert 1 <= len(started) <= bound
    assert gone(started)


def test_a_stop_request_ends_the_command(box: ProcessSandbox, cwd: Path) -> None:
    deadline = time.monotonic() + 1
    run = box.run(
        [PY, "-c", "import time; time.sleep(60)"], cwd=cwd, stop=lambda: time.monotonic() > deadline
    )
    assert run.outcome == "stopped"
    assert run.duration_s < 30


def test_output_is_kept_up_to_its_limit(tmp_path: Path, cwd: Path) -> None:
    box = ProcessSandbox(tmp_path / "work", Limits(output_bytes=1000))
    run = box.run([PY, "-c", "print('x' * 5000)"], cwd=cwd)
    assert len(run.stdout) == 1000
    assert run.output_truncated


def test_a_missing_command_is_refused(box: ProcessSandbox, cwd: Path) -> None:
    with pytest.raises(SandboxError, match="not a command"):
        box.run(["repro-no-such-command"], cwd=cwd)


def test_a_flood_of_attempts_is_capped(box: ProcessSandbox, cwd: Path) -> None:
    flood = script(
        cwd / "flood.py",
        """
        import socket
        for port in range(1500):
            s = socket.socket()
            s.setblocking(False)
            try:
                s.connect(("127.0.0.1", 9))
            except OSError:
                pass
            s.close()
        """,
    )
    run = box.run([PY, str(flood)], cwd=cwd)
    assert len(run.detections.items) == 1000
    assert run.detections.truncated


def test_a_tampered_audit_log_is_not_trusted(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    good = {"kind": "network", "event": "socket.connect", "detail": "h:1", "pid": 1, "test": None}
    lines = [json.dumps(good), "not json", json.dumps({**good, "kind": "root"}), "[1, 2]"]
    log.write_text("\n".join(lines), encoding="utf-8")
    detections = read_detections(log)
    assert [d.detail for d in detections.items] == ["h:1"]
    assert detections.dropped == 3


def test_the_ready_payload_states_what_is_achieved(box: ProcessSandbox) -> None:
    payload = box.ready_payload("head")
    SandboxReadyPayload.model_validate(payload)
    assert payload["network"] == "detected-only"  # only a container enforces the network
    assert payload["isolation_level"] == ("L2" if containment() else "L1")
    assert containment() is not None  # both CI platforms contain


def test_detections_become_evidence(tmp_path: Path) -> None:
    seen = [
        Detection("network", "socket.connect", "10.0.0.1:443", 7, "tests/test_a.py::test_x"),
        Detection("network", "socket.connect", "10.0.0.1:443", 8, "tests/test_a.py::test_x"),
        Detection("subprocess", "subprocess.Popen", "git status", 7, None),
        Detection("file", "open", "/etc/hosts", 7, None),
    ]
    run = run_record()
    records = detection_evidence(
        seen, run_id=run.id, side="head", fallback_target={"file": "tests/test_a.py"}
    )
    assert [r["type"] for r in records] == ["network_attempt", "subprocess_attempt", "file_attempt"]
    assert records[0]["data"]["count"] == 2
    assert records[0]["targets"] == [{"test": "tests/test_a.py::test_x"}]
    assert records[1]["targets"] == [{"file": "tests/test_a.py"}]
    for record in records:
        Evidence.model_validate({**record, "seq": 1})
    with started_writer(tmp_path / "repro.db") as writer:
        writer.create_run(run).result(30)
        bus = EventBus(writer)
        for record in records:
            stored = bus.emit(
                run.id,
                "evidence.created",
                stage="run",
                status="warn",
                payload={"evidence": record},
            ).result(30)
            assert stored[0].kind == "evidence.created"


def test_the_container_hook_archive_holds_every_hook_file_readable_by_all() -> None:
    """The container sandbox copies the hook into a volume from this archive (H06)."""
    with tarfile.open(fileobj=io.BytesIO(hook_archive())) as tar:
        members = {m.name: m for m in tar.getmembers()}
        contents = {name: tar.extractfile(m).read() for name, m in members.items()}  # type: ignore[union-attr]
    files = {path.name: path.read_bytes() for path in HOOK_DIR.iterdir() if path.is_file()}
    assert "repro_pytest.py" in files
    assert contents == files
    assert {(m.mode, m.uid, m.isfile()) for m in members.values()} == {(0o644, 0, True)}
