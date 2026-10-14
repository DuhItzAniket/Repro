"""Artifacts: content-addressed, written atomically, confined to their run's directory (C02)."""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from repro.store import ArtifactError, ArtifactStore, StoreReader, StoreWriter, safe_relative_path
from store_support import evidence_created, evidence_record, run_record, started_writer

TIMEOUT = 30


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


@pytest.fixture
def run_id(writer: StoreWriter) -> str:
    run = run_record()
    writer.create_run(run).result(TIMEOUT)
    return run.id


@pytest.fixture
def store(tmp_path: Path, writer: StoreWriter) -> ArtifactStore:
    return ArtifactStore(tmp_path / "runs", writer)


def test_put_writes_the_file_and_records_its_digest(
    store: ArtifactStore, run_id: str, tmp_path: Path
) -> None:
    data = b"<testsuite tests='1'/>\n"
    ref = store.put_bytes(run_id, "junit/base.xml", data, "application/xml")
    assert ref.sha256 == hashlib.sha256(data).hexdigest()
    assert (ref.path, ref.size_bytes, ref.media_type) == (
        "junit/base.xml",
        len(data),
        "application/xml",
    )
    assert (tmp_path / "runs" / run_id / "junit" / "base.xml").read_bytes() == data
    with store.open(run_id, ref) as handle:
        assert handle.read() == data
    with StoreReader(tmp_path / "repro.db") as reader:
        row = reader.artifact(run_id, ref.sha256)
    assert row is not None
    assert (row.path, row.size_bytes) == ("junit/base.xml", len(data))


def test_no_temporary_file_is_left_behind(
    store: ArtifactStore, run_id: str, tmp_path: Path
) -> None:
    store.put_bytes(run_id, "logs/base.txt", b"x" * 3_000_000, "text/plain")
    assert [p.name for p in (tmp_path / "runs" / run_id / "logs").iterdir()] == ["base.txt"]


def test_the_same_content_at_the_same_path_is_stored_once(
    store: ArtifactStore, run_id: str
) -> None:
    first = store.put_bytes(run_id, "obs/a.cbor", b"same", "application/cbor")
    second = store.put_bytes(run_id, "obs/a.cbor", b"same", "application/cbor")
    assert first == second


def test_other_content_at_a_taken_path_is_refused(
    store: ArtifactStore, run_id: str, tmp_path: Path
) -> None:
    store.put_bytes(run_id, "obs/a.cbor", b"first", "application/cbor")
    with pytest.raises(ArtifactError, match="already holds other content"):
        store.put_bytes(run_id, "obs/a.cbor", b"second", "application/cbor")
    assert (tmp_path / "runs" / run_id / "obs" / "a.cbor").read_bytes() == b"first"


def test_put_file_streams_from_disk(store: ArtifactStore, run_id: str, tmp_path: Path) -> None:
    source = tmp_path / "big.bin"
    source.write_bytes(bytes(range(256)) * 20_000)
    ref = store.put_file(run_id, "snapshots/manifest.bin", source, "application/octet-stream")
    assert ref.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_a_changed_file_no_longer_opens(store: ArtifactStore, run_id: str, tmp_path: Path) -> None:
    ref = store.put_bytes(run_id, "obs/a.cbor", b"original", "application/cbor")
    (tmp_path / "runs" / run_id / "obs" / "a.cbor").write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="no longer matches"):
        store.open(run_id, ref)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../escape.txt",
        "obs/../../escape.txt",
        "obs/./a",
        "obs//a",
        "obs\\a",
        "C:/Windows/a",
        "c:a",
        "obs/con.txt",
        "NUL",
        "obs/trailing.",
        "obs/trailing ",
        "obs/\x00null",
        "obs/new\nline",
        "a" * 1025,
        "obs/" + "b" * 256,
    ],
)
def test_unsafe_paths_are_refused(path: str) -> None:
    with pytest.raises(ArtifactError):
        safe_relative_path(path)


@pytest.mark.parametrize(
    "path", ["junit/base.xml", "obs/head/tests_test_dates.py__test_tz.cbor", "a"]
)
def test_ordinary_paths_are_kept(path: str) -> None:
    assert str(safe_relative_path(path)) == path


def test_run_ids_are_checked_before_they_name_a_directory(store: ArtifactStore) -> None:
    with pytest.raises(ArtifactError, match="not a run ID"):
        store.run_dir("../run_01J9ZQ4R6M3X8T2K5V7N0P1QWE")


def test_evidence_can_cite_a_stored_artifact(
    store: ArtifactStore, writer: StoreWriter, run_id: str, tmp_path: Path
) -> None:
    ref = store.put_bytes(run_id, "obs/head/a.cbor", b"\xa1ax\x01", "application/cbor")
    record = evidence_record(run_id, artifacts=[ref.model_dump()])
    writer.submit(evidence_created(run_id, record)).result(TIMEOUT)
    with StoreReader(tmp_path / "repro.db") as reader:
        stored = reader.evidence(record["id"])
        assert stored is not None
        (cited,) = stored["artifacts"]
        assert reader.artifact(run_id, cited["sha256"]) is not None
