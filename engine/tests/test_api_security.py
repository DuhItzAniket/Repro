"""The API answers only local hosts, WebSockets only allowed origins (C04; THREAT_MODEL T16),
and with a session token, only requests that carry it (H03; T13)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Origin

from api_support import AUTH, TOKEN, Server
from repro.api import create_app
from repro.store import StoreWriter
from store_support import log_line, run_record, started_writer

OWN_ORIGIN = "http://127.0.0.1:8780"


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


@pytest.fixture
def run_id(writer: StoreWriter) -> str:
    run = run_record()
    writer.create_run(run).result(30)
    writer.submit(log_line(run.id)).result(30)
    return run.id


@pytest.fixture
def client(tmp_path: Path, writer: StoreWriter) -> Iterator[TestClient]:
    app = create_app(tmp_path / "repro.db", allowed_origins={OWN_ORIGIN})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]", "127.0.0.1:8780"])
def test_local_hosts_are_answered(client: TestClient, host: str) -> None:
    assert client.get("/runs", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "0.0.0.0"])  # noqa: S104 - a Host header that must be refused
def test_other_hosts_are_refused(client: TestClient, host: str) -> None:
    """DNS rebinding: a page whose domain now points at 127.0.0.1 still names its own host."""
    response = client.get("/runs", headers={"host": host})
    assert response.status_code == 400


def stream(client: TestClient, run_id: str, origin: str | None) -> str:
    headers = {} if origin is None else {"origin": origin}
    with client.websocket_connect(f"ws://127.0.0.1/runs/{run_id}/events", headers=headers) as ws:
        frames = []
        try:
            while True:
                frames.append(ws.receive_text())
        except WebSocketDisconnect as closed:
            return f"closed {closed.code}"


@pytest.mark.parametrize("origin", [OWN_ORIGIN, OWN_ORIGIN + "/", OWN_ORIGIN.upper(), None])
def test_allowed_origins_and_non_browser_clients_may_stream(
    client: TestClient, run_id: str, origin: str | None
) -> None:
    assert stream(client, run_id, origin) == "closed 1000"


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://127.0.0.1:5173", "http://localhost:8780", "null"]
)
def test_a_foreign_origin_cannot_open_the_stream(
    client: TestClient, run_id: str, origin: str
) -> None:
    """Cross-site WebSocket hijacking: a page in the user's browser must not read the run."""
    with pytest.raises(WebSocketDisconnect) as refused:  # the test client's view of a refusal
        stream(client, run_id, origin)
    assert refused.value.code == 1008


def test_a_real_server_refuses_a_foreign_origin_with_403(
    tmp_path: Path, writer: StoreWriter, run_id: str
) -> None:
    app = create_app(tmp_path / "repro.db", allowed_origins={OWN_ORIGIN})
    with Server(app) as server:
        uri = f"ws://127.0.0.1:{server.port}/runs/{run_id}/events"
        with pytest.raises(InvalidStatus) as refused:
            connect(uri, origin=Origin("https://evil.example"), open_timeout=10)
        assert refused.value.response.status_code == 403
        with connect(uri, origin=Origin(OWN_ORIGIN), open_timeout=10) as socket:
            first = json.loads(socket.recv(timeout=10))
        assert first["type"] == "events"
        assert [event["seq"] for event in first["events"]] == [1]


def open_and_close(client: TestClient, url: str, headers: dict[str, str] | None = None) -> None:
    with client.websocket_connect(url, headers=headers or {}):
        pass


def test_a_websocket_to_a_foreign_host_is_refused(client: TestClient, run_id: str) -> None:
    with pytest.raises(WebSocketDenialResponse) as denied:
        open_and_close(client, f"ws://evil.example/runs/{run_id}/events")
    assert denied.value.status_code == 400


@pytest.fixture
def guarded(tmp_path: Path, writer: StoreWriter) -> Iterator[TestClient]:
    """The API with a session token, the cockpit's files and a log to replay."""
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>Repro</title>", "utf-8")
    log = tmp_path / "replay.jsonl"
    log.write_text("{}\n", "utf-8")
    app = create_app(
        tmp_path / "repro.db", allowed_origins={OWN_ORIGIN}, ui_dir=ui, replay_log=log, token=TOKEN
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_with_a_token_the_engines_data_needs_it(guarded: TestClient, run_id: str) -> None:
    for path in ("/runs", "/fleet", f"/runs/{run_id}", f"/runs/{run_id}/card", "/replay.jsonl"):
        refused = guarded.get(path)
        assert refused.status_code == 401, path
        assert refused.headers["www-authenticate"] == "Bearer"
        assert "open the URL repro printed" in refused.text
        assert guarded.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        # Only the event stream takes the token in its query: request lines get logged.
        assert guarded.get(f"{path}?token={TOKEN}").status_code == 401
    assert guarded.get("/runs", headers=AUTH).json()[0]["id"] == run_id
    assert guarded.get("/replay.jsonl", headers=AUTH).status_code == 200
    assert guarded.get("/").text.startswith("<!doctype html>")  # the cockpit's files: no data


def test_with_a_token_the_stream_needs_it(guarded: TestClient, run_id: str) -> None:
    url = f"ws://127.0.0.1/runs/{run_id}/events"
    for refused_url, headers in (
        (url, {}),
        (f"{url}?token=wrong", {}),
        (url, {"Authorization": "Bearer wrong"}),
        (f"{url}?token={TOKEN}", {"origin": "https://evil.example"}),  # the origin still counts
    ):
        with pytest.raises(WebSocketDisconnect) as refused:
            open_and_close(guarded, refused_url, headers)
        assert refused.value.code == 1008, (refused_url, headers)
    for allowed_url, headers in ((f"{url}?token={TOKEN}", {"origin": OWN_ORIGIN}), (url, AUTH)):
        with guarded.websocket_connect(allowed_url, headers=headers) as socket:
            assert socket.receive_json()["type"] == "events"


def test_a_real_server_refuses_a_stream_without_its_token_with_403(
    tmp_path: Path, writer: StoreWriter, run_id: str
) -> None:
    app = create_app(tmp_path / "repro.db", allowed_origins={OWN_ORIGIN}, token=TOKEN)
    with Server(app) as server:
        uri = f"ws://127.0.0.1:{server.port}/runs/{run_id}/events"
        with pytest.raises(InvalidStatus) as refused:
            connect(uri, origin=Origin(OWN_ORIGIN), open_timeout=10)
        assert refused.value.response.status_code == 403
        with connect(f"{uri}?token={TOKEN}", origin=Origin(OWN_ORIGIN), open_timeout=10) as socket:
            assert json.loads(socket.recv(timeout=10))["type"] == "events"
