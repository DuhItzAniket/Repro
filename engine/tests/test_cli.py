import json
import logging
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from api_support import AUTH, known_token
from cli_support import clean_env, free_port
from repro import __version__
from repro.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def session_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """The servers these tests start get a known session token (T13)."""
    return known_token(monkeypatch)


def test_version_comes_from_installed_metadata() -> None:
    assert __version__ == version("repro-engine")


def test_version_flag_prints_version_and_exits_cleanly() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"repro {__version__}\n"


def test_no_arguments_shows_usage() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_module_entry_point_runs_in_a_fresh_interpreter() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "repro", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"repro {__version__}"


def test_run_requires_its_refs(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--repo", "."], env=clean_env(tmp_path))
    assert result.exit_code == 2
    # Both refs, or a pull request (I01) that names them.
    assert "give --repo, --base and --head, or --pr" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


def test_a_configuration_error_stops_a_command_with_its_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["replay", "x"], env=clean_env(tmp_path, REPRO_CONCURRENCY="lots"))
    assert result.exit_code == 2
    assert "configuration error: REPRO_CONCURRENCY" in result.output


def test_doctor_reports_a_configuration_error_and_still_checks(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"], env=clean_env(tmp_path, REPRO_SANDBOX="vm"))
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    first = report["checks"][0]
    assert (first["name"], first["status"]) == ("config", "fail")
    assert "REPRO_SANDBOX" in first["summary"]
    assert {check["name"] for check in report["checks"]} >= {"python", "git", "data dir"}


def test_doctor_prints_text_by_default(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor"], env=clean_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(f"repro {__version__} doctor - ")
    assert "Ready: every required check passed" in result.stdout


def test_global_options_override_the_environment(tmp_path: Path) -> None:
    other = tmp_path / "other"
    result = runner.invoke(
        app,
        ["--data-dir", str(other), "--log-format", "text", "doctor", "--json"],
        env=clean_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    data_dir = next(c for c in json.loads(result.stdout)["checks"] if c["name"] == "data dir")
    assert str(other) in data_dir["summary"]


def test_config_option_names_the_file(tmp_path: Path) -> None:
    config = tmp_path / "custom.toml"
    config.write_text('sandbox = "nonsense"\n', encoding="utf-8")
    result = runner.invoke(app, ["--config", str(config), "replay", "x"], env=clean_env(tmp_path))
    assert result.exit_code == 2
    assert "custom.toml (sandbox)" in result.output


def test_serve_listens_on_loopback_only(tmp_path: Path) -> None:
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"], env=clean_env(tmp_path))  # noqa: S104
    assert result.exit_code == 2
    assert "not a loopback address" in result.output


def test_the_browser_is_opened_on_a_private_page_not_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T13: the browser's command line names a page only this user can read; the page sends it
    on to the cockpit's URL, token and all; the page goes when the server stops."""
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>Repro</title>", "utf-8")
    port = free_port()
    page = tmp_path / "data" / f"open-{port}.html"  # clean_env's data directory
    opened: list[str] = []
    seen: dict[str, Any] = {}

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        sock.close()
        seen["page"] = page.read_text(encoding="utf-8")
        seen["mode"] = page.stat().st_mode & 0o777

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    monkeypatch.setattr("webbrowser.open", fake_open)
    env = clean_env(tmp_path, REPRO_UI_DIR=str(ui))
    result = runner.invoke(app, ["serve", "--port", str(port), "--open"], env=env)
    assert result.exit_code == 0, result.output
    assert opened == [page.as_uri()]  # no token on the browser's command line
    assert f"url=http://127.0.0.1:{port}/#token=" in seen["page"]
    if sys.platform != "win32":  # Windows: the data directory's ACL, the user's profile
        assert seen["mode"] == 0o600
    assert not page.exists()


def test_the_server_logs_no_request_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The event stream's request line carries the session token (T13): no access log."""
    import uvicorn  # noqa: PLC0415

    from repro.cli import _run_server  # noqa: PLC0415

    seen: dict[str, Any] = {}

    class Recorded:
        def __init__(self, config: uvicorn.Config) -> None:
            seen["config"] = config

        def run(self, sockets: object) -> None:
            seen["ran"] = True

    monkeypatch.setattr(uvicorn, "Server", Recorded)
    ours, theirs = logging.getLogger("repro"), logging.getLogger("uvicorn")
    monkeypatch.setattr(theirs, "handlers", list(theirs.handlers))
    monkeypatch.setattr(theirs, "propagate", theirs.propagate)
    _run_server(object(), None, "info")  # type: ignore[arg-type]
    assert seen["ran"]
    assert seen["config"].access_log is False
    # H06: uvicorn logs each WebSocket it accepts with its query, the token in it. Its lines go
    # through Repro's handler, which redacts it (test_logs.py), not uvicorn's own.
    assert seen["config"].log_config is None
    assert theirs.handlers == ours.handlers
    assert theirs.propagate is False


def test_serve_starts_the_api_with_its_own_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

    from store_support import log_line, run_record, started_writer  # noqa: PLC0415

    run = run_record()
    with started_writer(tmp_path / "data" / "repro.db") as writer:
        writer.create_run(run).result(30)
        writer.submit(log_line(run.id)).result(30)
    started: dict[str, Any] = {}

    def fake_server(api: Any, sock: Any, log_level: str) -> None:
        started.update(api=api, address=sock.getsockname()[:2], log_level=log_level)
        sock.close()

    monkeypatch.setattr("repro.cli._run_server", fake_server)
    port = free_port()
    result = runner.invoke(
        app,
        ["serve", "--port", str(port), "--allow-origin", "http://localhost:5173"],
        env=clean_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    assert started["address"] == ("127.0.0.1", port)  # bound before the server started
    url = f"ws://127.0.0.1/runs/{run.id}/events"
    with TestClient(started["api"], base_url="http://127.0.0.1", headers=AUTH) as client:
        own = (f"http://127.0.0.1:{port}", f"http://localhost:{port}", "http://localhost:5173")
        for origin in own:
            with client.websocket_connect(url, headers={"origin": origin}) as socket:
                assert socket.receive_json()["type"] == "events"
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect(url, headers={"origin": "https://evil.example"}),
        ):
            pass
        assert refused.value.code == 1008
