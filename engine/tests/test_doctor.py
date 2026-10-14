"""``repro doctor``: every outcome of every check, without the tools installed (C01)."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repro.doctor import (
    Check,
    Machine,
    ProbeResult,
    ProbeTimeoutError,
    Report,
    SubprocessProbe,
    check_data_dir,
    check_docker,
    check_git,
    check_long_paths,
    check_python,
    check_run_root,
    check_sqlite,
    check_uv,
    diagnose,
    parse_version,
)

DOCKER_OK = {
    "Client": {"Version": "29.8.2", "Os": "windows", "Arch": "amd64"},
    "Server": {
        "Version": "29.8.2",
        "Os": "linux",
        "Arch": "amd64",
        "KernelVersion": "6.6.87.2-microsoft-standard-WSL2",
    },
}


#: What a fake program answers: its output, None (not installed) or ProbeTimeoutError.
Answer = ProbeResult | type[Exception] | None


class FakeProbe:
    """Answers by program name: a result, ``None`` (not installed) or a timeout."""

    def __init__(self, answers: Mapping[str, Answer]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult | None:
        self.calls.append(list(argv))
        assert timeout > 0
        answer = self.answers.get(argv[0])
        if answer is ProbeTimeoutError:
            raise ProbeTimeoutError(argv[0])
        assert not isinstance(answer, type)
        return answer


def said(stdout: str, returncode: int = 0, stderr: str = "") -> ProbeResult:
    return ProbeResult(returncode, stdout, stderr)


HEALTHY: dict[str, Answer] = {
    "git": said("git version 2.55.0.windows.3\n"),
    "uv": said("uv 0.13.0 (4ecd0eff2 2026-10-09 x86_64-pc-windows-msvc)\n"),
    "docker": said(json.dumps(DOCKER_OK)),
}


@pytest.mark.parametrize(
    ("text", "pattern", "expected"),
    [
        ("git version 2.55.0.windows.3", r"git version (\d+)\.(\d+)(?:\.(\d+))?", (2, 55, 0)),
        ("git version 2.39.5 (Apple Git-154)", r"git version (\d+)\.(\d+)(?:\.(\d+))?", (2, 39, 5)),
        ("git version 2.40", r"git version (\d+)\.(\d+)(?:\.(\d+))?", (2, 40)),
        ("uv 0.12.18 (abc 2026-07-01)", r"uv (\d+)\.(\d+)\.(\d+)", (0, 12, 18)),
        ("not a version", r"uv (\d+)\.(\d+)\.(\d+)", None),
    ],
)
def test_parse_version(text: str, pattern: str, expected: tuple[int, ...] | None) -> None:
    assert parse_version(text, pattern) == expected


@pytest.mark.parametrize(
    ("version", "status"), [((3, 13, 13), "ok"), ((3, 12, 0), "ok"), ((3, 11, 9), "fail")]
)
def test_python_needs_3_12(version: tuple[int, ...], status: str) -> None:
    check = check_python(version, "CPython")
    assert (check.status, check.required) == (status, True)
    if status == "fail":
        assert check.hint is not None
        assert "3.12" in check.hint


@pytest.mark.parametrize(
    ("answer", "status", "summary"),
    [
        (said("git version 2.55.0.windows.3\n"), "ok", "git 2.55.0"),
        (said("git version 2.40.0\n"), "ok", "git 2.40.0"),
        (said("git version 2.39.5 (Apple Git-154)\n"), "fail", "older than 2.40"),
        (None, "fail", "not found"),
        (ProbeTimeoutError, "fail", "timed out"),
        (said("", 1, "fatal: broken\n"), "fail", "fatal: broken"),
        (said("hello\n"), "fail", "failed: hello"),
    ],
)
def test_git(answer: Answer, status: str, summary: str) -> None:
    check = check_git(FakeProbe({"git": answer}))
    assert check.status == status
    assert check.required
    assert summary in check.summary
    if status == "fail":
        assert check.hint is not None
        assert "2.40" in check.hint


@pytest.mark.parametrize(
    ("answer", "status", "words"),
    [
        (said("uv 0.13.0 (x 2026-10-09)\n"), "ok", "uv 0.13.0"),
        (said("uv 0.14.2\n"), "ok", "uv 0.14.2"),
        (said("uv 0.12.20\n"), "warn", "baseline 0.13"),
        (said("uv 0.11.6\n"), "warn", "older than 0.12.18"),
        (None, "warn", "not found"),
        (ProbeTimeoutError, "warn", "timed out"),
    ],
)
def test_uv_is_recommended_until_stage_d(answer: Answer, status: str, words: str) -> None:
    check = check_uv(FakeProbe({"uv": answer}))
    assert (check.status, check.required) == (status, False)
    assert words in check.summary
    if words == "older than 0.12.18":
        assert check.hint is not None
        assert "path traversal" in check.hint


def test_docker_reports_server_and_kernel() -> None:
    check = check_docker(FakeProbe({"docker": said(json.dumps(DOCKER_OK))}), windows=True)
    assert check.status == "ok"
    assert check.summary == "Docker 29.8.2 (linux/amd64)"
    assert check.detail == "kernel 6.6.87.2-microsoft-standard-WSL2"
    assert not check.required


def test_docker_without_a_daemon_is_a_warning_saying_what_happens_instead() -> None:
    stdout = json.dumps({"Client": {"Version": "29.8.2"}, "Server": None})
    stderr = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n"
    check = check_docker(FakeProbe({"docker": said(stdout, 1, stderr)}), windows=False)
    assert check.status == "warn"
    assert check.summary == "Docker CLI 29.8.2, but the daemon is not reachable"
    assert check.hint is not None
    assert "isolation: process" in check.hint
    assert check.detail is not None
    assert "Cannot connect" in check.detail


@pytest.mark.parametrize("windows", [True, False])
def test_docker_missing_names_the_right_install(windows: bool) -> None:
    check = check_docker(FakeProbe({"docker": None}), windows=windows)
    assert check.status == "warn"
    assert check.hint is not None
    assert ("WSL2" in check.hint) is windows


def test_docker_with_windows_containers_is_a_warning() -> None:
    info = {"Client": {"Version": "29"}, "Server": {"Version": "29", "Os": "windows"}}
    check = check_docker(FakeProbe({"docker": said(json.dumps(info))}), windows=True)
    assert check.status == "warn"
    assert "not Linux containers" in check.summary


@pytest.mark.parametrize("stdout", ["", "garbage", "[]"])
def test_docker_with_unreadable_output_is_a_warning(stdout: str) -> None:
    check = check_docker(FakeProbe({"docker": said(stdout, 1)}), windows=False)
    assert check.status == "warn"
    assert "daemon is not reachable" in check.summary


def test_docker_timeout_is_a_warning() -> None:
    assert check_docker(FakeProbe({"docker": ProbeTimeoutError}), windows=False).status == "warn"


def test_data_dir_writable_and_left_as_found(tmp_path: Path) -> None:
    check = check_data_dir(tmp_path)
    assert check.status == "ok"
    assert "writable" in check.summary
    assert list(tmp_path.iterdir()) == []  # the write test removed its file


def test_a_missing_data_dir_is_not_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / ".repro"
    check = check_data_dir(target)
    assert check.status == "ok"
    assert "created on first use" in check.summary
    assert not (tmp_path / "a").exists()


def test_a_file_in_place_of_the_data_dir_fails(tmp_path: Path) -> None:
    blocker = tmp_path / "data"
    blocker.write_text("not a directory", encoding="utf-8")
    check = check_data_dir(blocker)
    assert (check.status, check.required) == ("fail", True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_a_read_only_data_dir_fails(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert check_data_dir(locked).status == "fail"
        assert check_data_dir(locked / "child").status == "fail"
    finally:
        locked.chmod(0o700)


def test_run_root_budget_applies_on_windows_only() -> None:
    long = Path("x" * 100)
    on_windows = check_run_root(long, windows=True)
    assert on_windows.status == "warn"
    assert on_windows.hint is not None
    assert "REPRO_RUN_ROOT" in on_windows.hint
    assert check_run_root(long, windows=False).status == "ok"
    assert check_run_root(Path("short"), windows=True).status == "ok"


@pytest.mark.parametrize(("enabled", "status"), [(True, "ok"), (False, "warn"), (None, "warn")])
def test_long_paths(enabled: bool | None, status: str) -> None:
    assert check_long_paths(enabled).status == status


def machine(answers: Mapping[str, Answer], *, windows: bool) -> Machine:
    return Machine(
        probe=FakeProbe(answers),
        python=(3, 13, 13),
        sqlite=(3, 50, 4),
        implementation="CPython",
        windows=windows,
        long_paths=lambda: True,
    )


def test_a_healthy_machine_is_ready(tmp_path: Path) -> None:
    report = diagnose(
        data_dir=tmp_path, run_root=Path("scratch"), version="0.3.0",
        machine=machine(HEALTHY, windows=True),
    )  # fmt: skip
    assert report.ok
    assert [check.name for check in report.checks] == [
        "python", "sqlite", "git", "uv", "docker", "data dir", "run root", "long paths",
    ]  # fmt: skip
    assert report.to_text().splitlines()[-1] == "Ready: every required check passed."
    assert report.to_text().isascii()


def test_long_paths_are_checked_on_windows_only(tmp_path: Path) -> None:
    report = diagnose(
        data_dir=tmp_path, run_root=tmp_path, version="0", machine=machine(HEALTHY, windows=False)
    )
    assert "long paths" not in [check.name for check in report.checks]


def test_missing_optional_tools_warn_but_do_not_fail(tmp_path: Path) -> None:
    answers = {**HEALTHY, "uv": None, "docker": None}
    report = diagnose(
        data_dir=tmp_path, run_root=tmp_path, version="0", machine=machine(answers, windows=False)
    )
    assert report.ok
    assert report.to_text().splitlines()[-1] == "Ready: every required check passed (2 warnings)."


def test_a_missing_required_tool_makes_the_machine_not_ready(tmp_path: Path) -> None:
    answers = {**HEALTHY, "git": None}
    report = diagnose(
        data_dir=tmp_path, run_root=tmp_path, version="0", machine=machine(answers, windows=False)
    )
    assert not report.ok
    text = report.to_text()
    assert text.splitlines()[-1] == "Not ready: git failed."
    assert "-> Install git 2.40 or newer" in text


def test_extra_checks_come_first(tmp_path: Path) -> None:
    problem = Check("config", "fail", "REPRO_CONCURRENCY: bad", required=True)
    report = diagnose(
        data_dir=tmp_path, run_root=tmp_path, version="0",
        machine=machine(HEALTHY, windows=False), extra=[problem],
    )  # fmt: skip
    assert report.checks[0] == problem
    assert not report.ok


def test_the_json_report_is_complete(tmp_path: Path) -> None:
    report = diagnose(
        data_dir=tmp_path, run_root=tmp_path, version="0.3.0",
        machine=machine(HEALTHY, windows=False),
    )  # fmt: skip
    data = json.loads(report.to_json())
    assert data["repro"] == "0.3.0"
    assert data["ok"] is True
    assert set(data["checks"][0]) == {"name", "status", "summary", "hint", "detail", "required"}
    assert report.to_json().isascii()


def test_report_ok_ignores_warnings() -> None:
    warn = Check("docker", "warn", "not found")
    assert Report((warn,), "0", "test").ok


def test_subprocess_probe_runs_a_real_program() -> None:
    assert shutil.which(sys.executable) is not None  # a full path resolves to itself
    result = SubprocessProbe().run([sys.executable, "-c", "print('hi')"], timeout=60)
    assert result is not None
    assert (result.returncode, result.stdout.strip()) == (0, "hi")


def test_subprocess_probe_reports_missing_programs_and_timeouts() -> None:
    assert SubprocessProbe().run(["repro-no-such-program-c01"], timeout=5) is None
    with pytest.raises(ProbeTimeoutError):
        SubprocessProbe().run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)


def test_doctor_runs_on_this_machine(tmp_path: Path) -> None:
    """The real tools on the CI runner (Ubuntu and Windows): required checks pass."""
    env = {**os.environ, "REPRO_DATA_DIR": str(tmp_path / "data")}
    env.pop("REPRO_CONFIG", None)
    completed = subprocess.run(
        [sys.executable, "-m", "repro", "doctor", "--json"],
        capture_output=True, text=True, env=env, check=False, timeout=120,
    )  # fmt: skip
    assert completed.returncode == 0, completed.stdout + completed.stderr
    data = json.loads(completed.stdout)
    statuses = {check["name"]: check["status"] for check in data["checks"]}
    assert statuses["python"] == "ok"
    assert statuses["git"] == "ok"
    assert statuses["data dir"] == "ok"
    assert statuses["uv"] in {"ok", "warn"}
    assert statuses["docker"] in {"ok", "warn"}
    assert not (tmp_path / "data").exists()  # doctor did not create it


@pytest.mark.parametrize(
    ("version", "status"), [((3, 50, 4), "ok"), ((3, 37, 0), "ok"), ((3, 36, 9), "fail")]
)
def test_sqlite_needs_strict_tables(version: tuple[int, ...], status: str) -> None:
    check = check_sqlite(version)
    assert (check.status, check.required) == (status, True)
