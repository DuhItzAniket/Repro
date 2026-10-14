"""The API answers only local hosts, and WebSockets only allowed origins (C04; THREAT_MODEL T16)."""

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

from api_support import Server
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


def open_and_close(client: TestClient, url: str) -> None:
    with client.websocket_connect(url):
        pass


def test_a_websocket_to_a_foreign_host_is_refused(client: TestClient, run_id: str) -> None:
    with pytest.raises(WebSocketDenialResponse) as denied:
        open_and_close(client, f"ws://evil.example/runs/{run_id}/events")
    assert denied.value.status_code == 400
