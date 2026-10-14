"""The read-only REST API: runs, evidence, verified artifacts, cards (C04)."""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repro.api import create_app
from repro.ids import new_evidence_id, new_run_id
from repro.store import ArtifactStore, StoreWriter
from store_support import evidence_created, evidence_record, log_line, run_record, started_writer

TIMEOUT = 30


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


@pytest.fixture
def client(tmp_path: Path, writer: StoreWriter) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path / "repro.db"), base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def run_id(writer: StoreWriter) -> str:
    run = run_record()
    writer.create_run(run).result(TIMEOUT)
    writer.submit(log_line(run.id)).result(TIMEOUT)
    return run.id


def test_runs_are_listed_newest_first_with_their_last_seq(
    client: TestClient, writer: StoreWriter, run_id: str
) -> None:
    other = run_record()
    writer.create_run(other).result(TIMEOUT)
    response = client.get("/runs")
    assert response.status_code == 200
    runs = response.json()
    assert [run["id"] for run in runs] == [other.id, run_id]
    assert (runs[1]["last_seq"], runs[1]["status"]) == (1, "running")
    assert client.get("/runs?limit=1").json()[0]["id"] == other.id
    assert client.get("/runs?limit=0").status_code == 422


def test_one_run(client: TestClient, run_id: str) -> None:
    run = client.get(f"/runs/{run_id}").json()
    assert (run["id"], run["repo"], run["last_seq"]) == (run_id, "fixture/honest-fix", 1)
    assert client.get(f"/runs/{new_run_id()}").status_code == 404
    assert client.get("/runs/not-a-run").status_code == 422


def test_evidence_is_served_within_its_run(
    client: TestClient, writer: StoreWriter, run_id: str
) -> None:
    record = evidence_record(run_id)
    writer.submit(evidence_created(run_id, record)).result(TIMEOUT)
    response = client.get(f"/runs/{run_id}/evidence/{record['id']}")
    assert response.json() == {**record, "seq": 2}
    other = run_record()
    writer.create_run(other).result(TIMEOUT)
    assert client.get(f"/runs/{other.id}/evidence/{record['id']}").status_code == 404
    assert client.get(f"/runs/{run_id}/evidence/{new_evidence_id()}").status_code == 404


def test_artifacts_are_served_only_while_their_digest_matches(
    client: TestClient, writer: StoreWriter, run_id: str, tmp_path: Path
) -> None:
    store = ArtifactStore(tmp_path / "runs", writer)
    data = b"<testsuite/>"
    ref = store.put_bytes(run_id, "junit/head.xml", data, "application/xml")
    response = client.get(f"/runs/{run_id}/artifacts/{ref.sha256}")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"].startswith("application/xml")
    assert client.get(f"/runs/{run_id}/artifacts/{'0' * 64}").status_code == 404
    assert client.get(f"/runs/{run_id}/artifacts/NOTHEX").status_code == 422
    (tmp_path / "runs" / run_id / "junit" / "head.xml").write_bytes(b"tampered")
    assert client.get(f"/runs/{run_id}/artifacts/{ref.sha256}").status_code == 410
    assert hashlib.sha256(data).hexdigest() == ref.sha256


def test_a_run_has_no_card_until_one_is_made(client: TestClient, run_id: str) -> None:
    response = client.get(f"/runs/{run_id}/card")
    assert response.status_code == 404
    assert response.json()["detail"] == "this run has no card yet"
    assert client.get(f"/runs/{new_run_id()}/card").json()["detail"] == "no such run"


def test_the_api_changes_nothing(client: TestClient, run_id: str) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(f"/runs/{run_id}").status_code == 405


def test_no_store_yet_is_a_clear_503(tmp_path: Path) -> None:
    app = create_app(tmp_path / "empty" / "repro.db")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/runs")
    assert response.status_code == 503
    assert "not available" in response.json()["detail"]
