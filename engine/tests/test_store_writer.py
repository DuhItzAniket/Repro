"""The single writer: seq, batching, atomic groups, evidence, the run registry (C02)."""

import json
import sqlite3
import threading
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pytest

from repro.clock import now_timestamp
from repro.ids import new_run_id
from repro.store import StoredEvent, StoreReader, WriteError
from repro.store.writer import check_draft
from store_support import evidence_created, evidence_record, log_line, run_record, started_writer

TIMEOUT = 30


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "repro.db"


def seqs(events: Sequence[StoredEvent]) -> list[int]:
    return [event.seq for event in events]


def test_seq_counts_from_1_per_run_across_batches(db: Path) -> None:
    with started_writer(db, max_batch=4, max_delay=0.001) as writer:
        runs = [run_record(), run_record()]
        for run in runs:
            writer.create_run(run).result(TIMEOUT)
        futures = [writer.submit(log_line(runs[i % 2].id, f"line {i}")) for i in range(20)]
        stored = [future.result(TIMEOUT)[0] for future in futures]
    assert [event.seq for event in stored if event.run_id == runs[0].id] == list(range(1, 11))
    assert [event.seq for event in stored if event.run_id == runs[1].id] == list(range(1, 11))
    with StoreReader(db) as reader:
        for run in runs:
            assert reader.last_seq(run.id) == 10
            assert seqs(reader.events(run.id)) == list(range(1, 11))


def test_the_body_is_the_envelope_with_its_seq(db: Path) -> None:
    with started_writer(db) as writer:
        run = run_record()
        writer.create_run(run).result(TIMEOUT)
        draft = log_line(run.id, "héllo")
        (event,) = writer.submit(draft).result(TIMEOUT)
    assert event.envelope() == {**draft, "seq": 1}
    assert event.body == json.dumps(
        {**draft, "seq": 1}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_events_are_batched(db: Path) -> None:
    run = run_record()
    with started_writer(db, max_batch=1000, max_delay=0.5) as writer:
        writer.create_run(run).result(TIMEOUT)
        before = writer.transactions
        futures = [writer.submit(log_line(run.id, str(i))) for i in range(200)]
        for future in futures:
            future.result(TIMEOUT)
        batched = writer.transactions - before
    assert batched < 20  # 200 events in a handful of transactions, not 200


def test_a_batch_holds_at_most_max_batch_events(db: Path) -> None:
    run = run_record()
    sizes: list[int] = []
    with started_writer(
        db, max_batch=10, max_delay=0.5, on_commit=lambda e: sizes.append(len(e))
    ) as writer:
        writer.create_run(run).result(TIMEOUT)
        futures = [writer.submit(log_line(run.id, str(i))) for i in range(95)]
        for future in futures:
            future.result(TIMEOUT)
    assert sum(sizes) == 95
    assert max(sizes) <= 10


def test_a_group_commits_together_and_a_bad_group_fails_alone(db: Path) -> None:
    run = run_record()
    with started_writer(db, max_delay=0.2) as writer:
        writer.create_run(run).result(TIMEOUT)
        first = log_line(run.id, "first")
        good = writer.submit(first)
        # The same event ID again: the database refuses this group, and only this group.
        bad = writer.submit_group(
            [log_line(run.id, "fine"), {**log_line(run.id), "id": first["id"]}]
        )
        later = writer.submit_group([log_line(run.id, "a"), log_line(run.id, "b")])
        assert seqs(good.result(TIMEOUT)) == [1]
        with pytest.raises(WriteError, match="UNIQUE"):
            bad.result(TIMEOUT)
        assert seqs(later.result(TIMEOUT)) == [2, 3]  # no gap where the bad group was
    with StoreReader(db) as reader:
        messages = [event.envelope()["payload"]["message"] for event in reader.events(run.id)]
    assert messages == ["first", "a", "b"]


def stamp(fraction: str) -> str:
    return f"2026-10-20T11:56:58.{fraction}Z"


def stored_ts(db: Path, run_id: str) -> list[str]:
    """Each event's ``ts``, from its body and from the ``ts`` column, which must agree."""
    with StoreReader(db) as reader:
        bodies = [event.envelope()["ts"] for event in reader.events(run_id)]
    with closing(sqlite3.connect(db)) as connection:
        rows = connection.execute(
            "SELECT ts FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
    assert [row[0] for row in rows] == bodies
    return bodies


def test_a_runs_ts_never_goes_backwards(db: Path) -> None:
    """C03: ``ts`` is stamped before the writer assigns ``seq``, so events can arrive stamped
    out of order. One stamped before its run's latest gets that time (compared as instants,
    whatever the digits), within a transaction, across them and from a new writer."""
    a, b = run_record(), run_record()
    with started_writer(db) as writer:
        for run in (a, b):
            writer.create_run(run).result(TIMEOUT)
        writer.submit({**log_line(a.id), "ts": stamp("8")}).result(TIMEOUT)
        group = [{**log_line(a.id), "ts": stamp(digits)} for digits in ("83", "825")]
        writer.submit_group(group).result(TIMEOUT)
        writer.submit({**log_line(b.id), "ts": stamp("1")}).result(TIMEOUT)  # another run
        writer.submit({**log_line(a.id), "ts": stamp("9")}).result(TIMEOUT)
    with started_writer(db) as writer:  # this one reads the run's latest from the store
        writer.submit({**log_line(a.id), "ts": stamp("1")}).result(TIMEOUT)
    assert stored_ts(db, a.id) == [stamp(d) for d in ("8", "83", "83", "9", "9")]
    assert stored_ts(db, b.id) == [stamp("1")]


def test_a_group_that_fails_does_not_move_ts_forward(db: Path) -> None:
    run = run_record()
    with started_writer(db, max_delay=0.2) as writer:
        writer.create_run(run).result(TIMEOUT)
        first = {**log_line(run.id), "ts": stamp("100")}
        good = writer.submit(first)
        bad = writer.submit_group(
            [{**log_line(run.id), "ts": stamp("900")}, {**log_line(run.id), "id": first["id"]}]
        )
        later = writer.submit({**log_line(run.id), "ts": stamp("200")})
        for future in (good, later):
            future.result(TIMEOUT)
        with pytest.raises(WriteError, match="UNIQUE"):
            bad.result(TIMEOUT)
    assert stored_ts(db, run.id) == [stamp("100"), stamp("200")]


def test_evidence_is_stored_with_its_event(db: Path) -> None:
    run = run_record()
    with started_writer(db) as writer:
        writer.create_run(run).result(TIMEOUT)
        writer.submit(log_line(run.id)).result(TIMEOUT)
        record = evidence_record(run.id)
        (event,) = writer.submit(evidence_created(run.id, record)).result(TIMEOUT)
    assert event.seq == 2
    assert event.envelope()["payload"]["evidence"]["seq"] == 2
    with StoreReader(db) as reader:
        stored = reader.evidence(record["id"])
        assert stored == {**record, "seq": 2}
        assert reader.evidence_of(run.id) == [stored]


def test_events_for_an_unknown_run_are_refused(db: Path) -> None:
    with started_writer(db) as writer:
        future = writer.submit(log_line(new_run_id()))
        with pytest.raises(WriteError, match="FOREIGN KEY"):
            future.result(TIMEOUT)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: {**e, "seq": 7}, "assigns seq"),
        (lambda e: {k: v for k, v in e.items() if k != "kind"}, "not an event envelope"),
        (lambda e: {**e, "id": "evt_lowercase"}, "not an event envelope"),
        (lambda e: {**e, "kind": "evidence.created", "payload": {}}, "payload.evidence"),
    ],
)
def test_drafts_are_checked_before_they_are_queued(change: object, message: str) -> None:
    draft = change(log_line(new_run_id()))  # type: ignore[operator]
    with pytest.raises(WriteError, match=message):
        check_draft(draft)


def test_evidence_must_be_a_valid_record_of_the_same_run() -> None:
    run_id = new_run_id()
    broken = {**evidence_record(run_id), "type": "gossip"}
    with pytest.raises(WriteError, match="not an evidence record"):
        check_draft(evidence_created(run_id, broken))
    with pytest.raises(WriteError, match="belongs to the run"):
        check_draft(evidence_created(run_id, evidence_record(new_run_id())))


def test_the_run_registry(db: Path) -> None:
    run = run_record()
    with started_writer(db) as writer:
        writer.create_run(run).result(TIMEOUT)
        with pytest.raises(WriteError, match="UNIQUE"):
            writer.create_run(run).result(TIMEOUT)
        writer.finish_run(run.id, "completed", now_timestamp()).result(TIMEOUT)
        with pytest.raises(WriteError, match="not a running run"):
            writer.finish_run(run.id, "failed", now_timestamp()).result(TIMEOUT)
        other = run_record()
        writer.create_run(other).result(TIMEOUT)
    with StoreReader(db) as reader:
        finished = reader.run(run.id)
        assert finished is not None
        assert (finished.status, finished.finished_at is not None) == ("completed", True)
        assert [found.id for found in reader.runs()] == [other.id, run.id]  # newest first
        assert reader.run(new_run_id()) is None


def test_on_commit_sees_committed_events_in_order(db: Path) -> None:
    run = run_record()
    seen: list[int] = []
    visible: list[int] = []

    def on_commit(events: Sequence[StoredEvent]) -> None:
        seen.extend(seqs(events))
        with StoreReader(db) as reader:  # committed: another connection can read them
            visible.append(reader.last_seq(run.id))

    with started_writer(db, on_commit=on_commit) as writer:
        writer.create_run(run).result(TIMEOUT)
        for future in [writer.submit(log_line(run.id, str(i))) for i in range(50)]:
            future.result(TIMEOUT)
    assert seen == list(range(1, 51))
    assert visible[-1] == 50


def test_a_failing_hook_does_not_stop_the_writer(db: Path) -> None:
    run = run_record()

    def explode(_: Sequence[StoredEvent]) -> None:
        raise RuntimeError("subscriber broke")

    with started_writer(db, on_commit=explode) as writer:
        writer.create_run(run).result(TIMEOUT)
        assert seqs(writer.submit(log_line(run.id)).result(TIMEOUT)) == [1]
        assert seqs(writer.submit(log_line(run.id)).result(TIMEOUT)) == [2]


def test_close_writes_everything_submitted_before_it(db: Path) -> None:
    run = run_record()
    writer = started_writer(db, max_delay=1.0)
    writer.create_run(run).result(TIMEOUT)
    futures = [writer.submit(log_line(run.id, str(i))) for i in range(300)]
    writer.close(TIMEOUT)
    assert all(future.done() for future in futures)
    with StoreReader(db) as reader:
        assert reader.last_seq(run.id) == 300
    with pytest.raises(WriteError, match="not running"):
        writer.submit(log_line(run.id))


def test_submissions_from_many_threads_get_distinct_contiguous_seqs(db: Path) -> None:
    run = run_record()
    with started_writer(db) as writer:
        writer.create_run(run).result(TIMEOUT)
        results: list[int] = []
        lock = threading.Lock()

        def work() -> None:
            for _ in range(100):
                (event,) = writer.submit(log_line(run.id)).result(TIMEOUT)
                with lock:
                    results.append(event.seq)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(results) == list(range(1, 801))


def test_checkpoint_truncates_the_wal(db: Path) -> None:
    run = run_record()
    with started_writer(db) as writer:
        writer.create_run(run).result(TIMEOUT)
        for future in [writer.submit(log_line(run.id)) for _ in range(100)]:
            future.result(TIMEOUT)
        result = writer.checkpoint().result(TIMEOUT)
        assert isinstance(result, tuple)
        assert result[0] == 0  # not blocked by a reader
        wal = db.with_name(db.name + "-wal")
        assert not wal.exists() or wal.stat().st_size == 0


def test_100k_events_round_trip_in_order(db: Path) -> None:
    """Roadmap C02: 100k events written and read back in order."""
    run = run_record()
    count = 100_000
    with started_writer(db) as writer:
        writer.create_run(run).result(TIMEOUT)
        drafts = [log_line(run.id, f"event {i}") for i in range(count)]
        start = time.perf_counter()
        futures = [writer.submit(draft) for draft in drafts]
        last = futures[-1].result(120)
        written = time.perf_counter() - start
    assert last[0].seq == count
    start = time.perf_counter()
    with StoreReader(db) as reader:
        read = list(reader.iter_events(run.id))
    elapsed = time.perf_counter() - start
    assert [event.seq for event in read] == list(range(1, count + 1))
    assert [event.id for event in read] == [draft["id"] for draft in drafts]
    assert read[-1].envelope()["payload"]["message"] == f"event {count - 1}"
    print(f"\n100k events: written in {written:.1f} s, read in {elapsed:.1f} s")  # noqa: T201
