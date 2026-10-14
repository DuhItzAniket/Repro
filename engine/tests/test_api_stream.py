"""The WebSocket stream: every event exactly once, in order, from any moment (C04).

Written before the stream itself (IMPLEMENTATION_PLAN §6, Stage C).
"""

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from api_support import Server
from repro.api import create_app
from repro.bus import EventBus
from repro.store import StoreWriter
from store_support import run_record, started_writer


def local_client(app: Any) -> TestClient:
    """A test client that addresses the server as a local host, as the Host check requires."""
    return TestClient(app, base_url="http://127.0.0.1")


LOG = {"level": "info", "verb": "run", "message": "x" * 200}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "repro.db"


@pytest.fixture
def writer(db: Path) -> Iterator[StoreWriter]:
    with started_writer(db) as writer:
        yield writer


@pytest.fixture
def bus(writer: StoreWriter) -> EventBus:
    return EventBus(writer)


def new_run(writer: StoreWriter) -> str:
    run = run_record()
    writer.create_run(run).result(30)
    return run.id


def produce(bus: EventBus, run_id: str, count: int, *, pause_every: int = 0) -> None:
    """Emits ``count`` log lines, then run.finished, waiting for the last commit."""
    last = None
    for i in range(count):
        last = bus.emit(run_id, "log.line", stage="run", status="progress", payload=LOG)
        if pause_every and i % pause_every == 0:
            time.sleep(0.002)
    if last is not None:
        last.result(60)
    finished = {
        "outcome": "completed",
        "card_status": None,
        "duration_ms": 1,
        "counts": {"events": count + 1, "evidence": 0, "missing": 0},
    }
    bus.emit(run_id, "run.finished", stage="card", status="ok", payload=finished).result(60)


def read_all(client: TestClient, path: str) -> tuple[list[int], list[dict[str, Any]]]:
    """Every event seq the server sends until it closes, and the control frames."""
    seqs: list[int] = []
    control: list[dict[str, Any]] = []
    # Absolute: the test client otherwise addresses WebSockets to its own 'testserver' host.
    with client.websocket_connect(f"ws://127.0.0.1{path}") as socket:
        while True:
            try:
                frame = socket.receive_json()
            except WebSocketDisconnect as closed:
                control.append({"type": "closed", "code": closed.code})
                break
            if frame["type"] == "events":
                seqs.extend(event["seq"] for event in frame["events"])
            else:
                control.append(frame)
    return seqs, control


def test_a_client_after_the_end_replays_everything_once(
    bus: EventBus, writer: StoreWriter, db: Path
) -> None:
    run_id = new_run(writer)
    produce(bus, run_id, 1_500)
    with local_client(create_app(db, bus=bus)) as client:
        seqs, control = read_all(client, f"/runs/{run_id}/events")
    assert seqs == list(range(1, 1_502))
    assert control == [{"type": "caught_up", "seq": 1_501}, {"type": "closed", "code": 1000}]


def test_replay_starts_after_from(bus: EventBus, writer: StoreWriter, db: Path) -> None:
    run_id = new_run(writer)
    produce(bus, run_id, 50)
    with local_client(create_app(db, bus=bus)) as client:
        seqs, _ = read_all(client, f"/runs/{run_id}/events?from=40")
    assert seqs == list(range(41, 52))


@pytest.mark.parametrize("delay", [0.0, 0.05, 0.3])
def test_clients_connecting_mid_run_see_no_gap_and_no_duplicate(
    bus: EventBus, writer: StoreWriter, db: Path, delay: float
) -> None:
    """Roadmap C04: a client that connects while events are being written."""
    run_id = new_run(writer)
    count = 4_000
    producer = threading.Thread(
        target=produce, args=(bus, run_id, count), kwargs={"pause_every": 50}
    )
    with local_client(create_app(db, bus=bus)) as client:
        producer.start()
        time.sleep(delay)
        seqs, control = read_all(client, f"/runs/{run_id}/events")
        producer.join(60)
    assert seqs == list(range(1, count + 2))  # every event, once, in order, then run.finished
    caught_up = [frame for frame in control if frame["type"] == "caught_up"]
    assert len(caught_up) == 1
    assert control[-1] == {"type": "closed", "code": 1000}


def test_several_clients_at_once(bus: EventBus, writer: StoreWriter, db: Path) -> None:
    run_id = new_run(writer)
    results: list[list[int]] = []
    with local_client(create_app(db, bus=bus)) as client:
        readers = [
            threading.Thread(
                target=lambda: results.append(read_all(client, f"/runs/{run_id}/events")[0])
            )
            for _ in range(4)
        ]
        for reader in readers:
            reader.start()
        time.sleep(0.1)
        produce(bus, run_id, 1_000, pause_every=100)
        for reader in readers:
            reader.join(60)
    assert len(results) == 4
    assert all(seqs == list(range(1, 1_002)) for seqs in results)


def test_an_unknown_run_is_refused(bus: EventBus, db: Path, writer: StoreWriter) -> None:
    new_run(writer)
    with local_client(create_app(db, bus=bus)) as client:
        _, control = read_all(client, "/runs/run_01J9ZQ4R6M3X8T2K5V7N0P1QWE/events")
    assert control == [{"type": "closed", "code": 4404}]


@pytest.mark.parametrize("bad", ["-1", "abc", "1.5"])
def test_a_bad_from_is_refused(bus: EventBus, writer: StoreWriter, db: Path, bad: str) -> None:
    run_id = new_run(writer)
    with local_client(create_app(db, bus=bus)) as client:
        _, control = read_all(client, f"/runs/{run_id}/events?from={bad}")
    assert control[-1]["code"] == 4400


def drain(socket: Any, seqs: list[int]) -> tuple[int, str] | None:
    """Reads event frames into ``seqs`` until the server closes; its close code and reason."""
    try:
        while True:
            frame = json.loads(socket.recv(timeout=30))
            if frame["type"] == "events":
                seqs.extend(event["seq"] for event in frame["events"])
    except ConnectionClosed as closed:
        received = closed.rcvd
        return None if received is None else (received.code, received.reason)


def test_a_slow_client_is_dropped_and_recovers_with_from(
    bus: EventBus, writer: StoreWriter, db: Path
) -> None:
    """Roadmap C04: a client that stops reading is closed with resync, then resumes losslessly."""
    run_id = new_run(writer)
    count = 60_000
    app = create_app(db, bus=bus, max_pending=500)
    seqs: list[int] = []
    with Server(app) as server:
        uri = f"ws://127.0.0.1:{server.port}/runs/{run_id}/events"
        with connect(uri, max_size=None) as socket:
            first = json.loads(socket.recv(timeout=10))
            assert first == {"type": "caught_up", "seq": 0}
            produce(bus, run_id, count)  # the client reads nothing meanwhile
            closed_with = drain(socket, seqs)
        assert closed_with == (4000, "resync")
        assert seqs == list(range(1, len(seqs) + 1))  # what it got before the drop is gap-free
        assert len(seqs) < count + 1
        with connect(f"{uri}?from={seqs[-1] if seqs else 0}", max_size=None) as socket:
            assert drain(socket, seqs) == (1000, "finished")
    assert seqs == list(range(1, count + 2))  # nothing lost, nothing twice
