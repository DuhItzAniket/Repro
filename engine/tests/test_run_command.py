"""``repro run``, ``replay`` and ``serve`` with the cockpit (C08), on fixture repositories."""

import json
import re
import socket
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from typer.testing import CliRunner

from api_support import AUTH, TOKEN, known_token
from cli_support import clean_env, free_port
from gitrepo import Repo
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader
from repro_events.log import read_log, validate_log
from repro_events.schemas import load_schema_set

runner = CliRunner()
#: These tests are about the build stage and the cockpit: no target code runs (D06 has its own).
ANALYSE = ["--analyse-only"]


@pytest.fixture(autouse=True)
def session_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """The servers these tests start get a known session token (T13)."""
    return known_token(monkeypatch)


BASE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def f():\n    return 1\n",
    "pkg/api.py": "from pkg.core import f\n",
    "tests/test_api.py": "import pkg.api\n",
}
HEAD = {"pkg/core.py": "def f():\n    return 2\n", "pkg/broken.py": "def broken(:\n"}


@pytest.fixture
def change(tmp_path: Path) -> tuple[Path, str, str]:
    repo = Repo(tmp_path / "target")
    base = repo.commit(BASE)
    head = repo.commit(HEAD)
    return repo.path, base, head


def stored_events(tmp_path: Path, env: dict[str, str]) -> list[dict[str, Any]]:
    settings = load_settings(env=env)
    with StoreReader(settings.paths.database) as reader:
        (run,) = reader.runs(10)
        return [json.loads(event.body) for event in reader.events(run.id, 0, 100_000)]


def scratch_dirs(env: dict[str, str]) -> list[Path]:
    root = load_settings(env=env).paths.run_root
    return list(root.iterdir()) if root.exists() else []


def test_run_records_the_build_stage_and_cleans_up(
    tmp_path: Path, change: tuple[Path, str, str]
) -> None:
    repo, base, head = change
    env = clean_env(tmp_path, REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    argv = ["run", "--repo", str(repo), "--base", base, "--head", head, "--no-serve", *ANALYSE]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 0, result.output
    # The last line says how the run ended and, without a cockpit to show it, its card (H06).
    assert re.search(r"run_[0-9A-Z]{26} completed \(.*\): the card is [A-Z]+$", result.output, re.M)
    events = stored_events(tmp_path, env)
    kinds = Counter(event["kind"] for event in events)
    assert kinds["snapshot.ready"] == 2
    assert kinds["symbol.changed"] == 1  # f's body; pkg/broken.py cannot be read
    assert kinds["blast.computed"] == 1
    assert kinds["graph.node"] == 6  # five modules (pkg.broken too) and the changed function
    assert events[-1]["kind"] == "run.finished"
    (blast,) = [e["payload"] for e in events if e["kind"] == "blast.computed"]
    assert blast["affected"] == [
        {"symbol_id": "pkg.api:<module>#0", "distance": 1},
        {"symbol_id": "test_api:<module>#0", "distance": 2},
    ]
    missing = [e["payload"]["missing"] for e in events if e["kind"] == "missing.recorded"]
    assert [(m["reason"], m["targets"]) for m in missing] == [
        ("unsupported_project", [{"file": "pkg/broken.py"}]),  # symbols: head does not parse
        ("unsupported_project", [{"file": "pkg/broken.py"}]),  # the head import graph
    ]
    snapshots = {
        e["payload"]["side"]: e["payload"] for e in events if e["kind"] == "snapshot.ready"
    }
    assert (snapshots["base"]["file_count"], snapshots["head"]["file_count"]) == (4, 5)
    assert scratch_dirs(env) == []
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines, issues = read_log(log)
    assert issues + validate_log(load_schema_set(), lines) == []


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--base", "HEAD~5", "--head", "HEAD"], "not a git repository"),
        (["--base", "nope", "--head", "HEAD"], "nope"),
    ],
)
def test_run_refuses_what_it_cannot_reproduce(
    tmp_path: Path, change: tuple[Path, str, str], argv: list[str], message: str
) -> None:
    repo, _, _ = change
    target = tmp_path / "not-a-repo" if message == "not a git repository" else repo
    target.mkdir(exist_ok=True)
    result = runner.invoke(
        app, ["run", "--repo", str(target), *argv, "--no-serve", *ANALYSE], env=clean_env(tmp_path)
    )
    assert result.exit_code == 2
    assert message in result.output


def test_run_on_a_busy_port_stops_before_the_run_starts(
    tmp_path: Path, change: tuple[Path, str, str]
) -> None:
    repo, base, head = change
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        argv = [
            "run",
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--port",
            str(port),
            *ANALYSE,
        ]
        result = runner.invoke(app, argv, env=clean_env(tmp_path))
    assert result.exit_code == 2
    assert f"cannot listen on 127.0.0.1:{port}" in result.output
    assert not (tmp_path / "data" / "repro.db").exists()


def follow(api: Any, run_id: str) -> list[dict[str, Any]]:
    """Every event of a run over the WebSocket, until the server closes it normally."""
    events: list[dict[str, Any]] = []

    def receive_until_closed(ws: Any) -> None:
        while True:
            events.extend(ws.receive_json().get("events", []))

    with (
        TestClient(api, base_url="http://127.0.0.1", headers=AUTH) as client,
        client.websocket_connect(f"ws://127.0.0.1/runs/{run_id}/events") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        receive_until_closed(ws)
    assert closed.value.code == 1000
    return events


def test_run_streams_live_to_the_cockpit_and_cleans_up(
    tmp_path: Path, change: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, head = change
    env = clean_env(tmp_path, REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    seen: dict[str, Any] = {}

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        sock.close()
        with TestClient(api, base_url="http://127.0.0.1", headers=AUTH) as client:
            (run,) = client.get("/runs").json()
        seen["events"] = follow(api, run["id"])

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    port = free_port()
    argv = [
        "run",
        "--repo",
        str(repo),
        "--base",
        base,
        "--head",
        head,
        "--port",
        str(port),
        *ANALYSE,
    ]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 0, result.output
    assert re.search(
        rf"cockpit at http://127.0.0.1:{port}/\?run=run_[0-9A-Z]{{26}}#token={TOKEN}", result.output
    )
    assert [e["kind"] for e in seen["events"]] == [e["kind"] for e in stored_events(tmp_path, env)]
    assert seen["events"][-1]["kind"] == "run.finished"
    assert scratch_dirs(env) == []


def test_replay_serves_a_stored_run_from_the_start(
    tmp_path: Path, change: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, head = change
    env = clean_env(tmp_path)
    argv = ["run", "--repo", str(repo), "--base", base, "--head", head, "--no-serve", *ANALYSE]
    assert runner.invoke(app, argv, env=env).exit_code == 0
    stored = stored_events(tmp_path, env)
    run_id = stored[0]["run_id"]
    seen: dict[str, Any] = {}

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        sock.close()
        seen["events"] = follow(api, run_id)

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    result = runner.invoke(app, ["replay", run_id, "--port", str(free_port())], env=env)
    assert result.exit_code == 0, result.output
    assert f"?run={run_id}&replay" in result.output
    assert seen["events"] == stored

    unknown = "run_" + "0" * 26
    result = runner.invoke(app, ["replay", unknown], env=env)
    assert result.exit_code == 2
    assert f"no run {unknown}" in result.output


def test_replay_serves_a_valid_event_log_and_refuses_an_invalid_one(
    tmp_path: Path, change: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, head = change
    env = clean_env(tmp_path)
    argv = ["run", "--repo", str(repo), "--base", base, "--head", head, "--no-serve", *ANALYSE]
    assert runner.invoke(app, argv, env=env).exit_code == 0
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in stored_events(tmp_path, env)), "utf-8")
    seen: dict[str, Any] = {}

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        sock.close()
        with TestClient(api, base_url="http://127.0.0.1", headers=AUTH) as client:
            seen["log"] = client.get("/replay.jsonl").content

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    result = runner.invoke(app, ["replay", str(log), "--port", str(free_port())], env=env)
    assert result.exit_code == 0, result.output
    assert "?log=/replay.jsonl" in result.output
    assert seen["log"] == log.read_bytes()

    broken = tmp_path / "broken.jsonl"
    broken.write_text(log.read_text("utf-8").replace('"seq": 2,', '"seq": 7,'), "utf-8")
    result = runner.invoke(app, ["replay", str(broken)], env=env)
    assert result.exit_code == 1
    assert "the log is not used" in result.output


def test_serve_serves_the_built_cockpit_beside_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>Repro</title>", "utf-8")
    (ui / "assets" / "app.js").write_text("export {};", "utf-8")
    seen: dict[str, Any] = {}

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        sock.close()
        with TestClient(api, base_url="http://127.0.0.1", headers=AUTH) as client:
            seen["index"] = client.get("/").text
            seen["asset"] = client.get("/assets/app.js").status_code
            seen["runs"] = client.get("/runs").status_code
            seen["without"] = client.get("/runs", headers={"Authorization": ""}).status_code
            seen["escape"] = client.get("/../pyproject.toml").status_code

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    env = clean_env(tmp_path, REPRO_UI_DIR=str(ui))
    result = runner.invoke(app, ["serve", "--port", str(free_port())], env=env)
    assert result.exit_code == 0, result.output
    assert seen["index"].startswith("<!doctype html>")
    assert (seen["asset"], seen["escape"]) == (200, 404)
    assert seen["runs"] in {200, 503}  # the API, not a file (503: no store yet)
    assert seen["without"] == 401  # the engine's data needs the session token (T13)

    result = runner.invoke(
        app,
        ["serve", "--port", str(free_port())],
        env=clean_env(tmp_path, REPRO_UI_DIR=str(tmp_path)),
    )
    assert "the cockpit is not built" in result.output


def test_entries_a_snapshot_leaves_out_are_a_warning(tmp_path: Path) -> None:
    """A submodule is not written to a snapshot; the run says so, as a schema-valid warning."""
    repo = Repo(tmp_path / "target")
    base = repo.commit({**BASE, "vendored": ("a" * 40, "160000")})
    head = repo.commit(HEAD)
    env = clean_env(tmp_path, REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    argv = ["run", "--repo", str(repo.path), "--base", base, "--head", head, "--no-serve"]
    result = runner.invoke(app, [*argv, *ANALYSE], env=env)
    assert result.exit_code == 0, result.output
    warnings = [
        e["payload"]["message"]
        for e in stored_events(tmp_path, env)
        if e["kind"] == "log.line" and e["payload"]["level"] == "warning"
    ]
    assert sorted(w.split(":", 1)[0] for w in warnings if "entries not written" in w) == [
        "snapshot base",
        "snapshot head",
    ]


def run_started_backend(events: list[dict[str, Any]]) -> str:
    (started,) = [e["payload"] for e in events if e["kind"] == "run.started"]
    return str(started["mode"]["sandbox_backend"])


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"REPRO_SANDBOX": "process"}, "process"),
        ({"REPRO_SANDBOX": "docker"}, "docker"),
        ({"REPRO_SANDBOX": "docker", "REPRO_DOCKER_RUNTIME": "runsc"}, "gvisor"),
        ({"REPRO_SANDBOX": "docker", "REPRO_DOCKER_RUNTIME": "kata"}, "kata"),
        ({"REPRO_SANDBOX": "auto"}, "process"),  # nothing runs: Docker is not asked
    ],
)
def test_run_started_names_the_configured_backend(
    tmp_path: Path,
    change: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    variables: dict[str, str],
    expected: str,
) -> None:
    def no_docker_question() -> bool:
        raise AssertionError("an analysis does not ask Docker")

    monkeypatch.setattr("repro.run_stage.docker_available", no_docker_question)
    repo, base, head = change
    env = clean_env(tmp_path, **variables)
    argv = ["run", "--repo", str(repo), "--base", base, "--head", head, "--no-serve", *ANALYSE]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 0, result.output
    assert run_started_backend(stored_events(tmp_path, env)) == expected


def test_run_started_names_the_backend_auto_chose_for_the_sandboxes(
    tmp_path: Path, change: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``auto`` and Docker answering, run.started says ``docker``, as the sandbox jobs do:
    Docker is asked once for the run, not once per side."""
    asked: list[bool] = []

    def docker_answers() -> bool:
        asked.append(True)
        return True

    monkeypatch.setattr("repro.run_stage.docker_available", docker_answers)
    repo, base, head = change
    env = clean_env(
        tmp_path,
        REPRO_SANDBOX="auto",
        REPRO_RUN_ROOT=str(tmp_path / "scratch"),
        DOCKER_HOST="tcp://127.0.0.1:9",  # no daemon answers here: the containers cannot start
    )
    argv = ["run", "--repo", str(repo), "--base", base, "--head", head, "--no-serve"]
    runner.invoke(app, argv, env=env)
    events = stored_events(tmp_path, env)
    assert run_started_backend(events) == "docker"
    assert len(asked) == 1
    missing = [e["payload"]["missing"] for e in events if e["kind"] == "missing.recorded"]
    sandboxes = [m["detail"] for m in missing if "the sandbox could not start" in m["detail"]]
    assert sorted(detail.split(":", 1)[0] for detail in sandboxes) == ["base", "head"]
