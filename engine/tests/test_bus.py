"""The event bus: envelopes, validation, secret scrubbing and fan-out after commit (C03)."""

import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from repro.bus import PAYLOAD_VERSIONS, EventBus, EventError, producer_tag
from repro.scrub import REDACTED, scrub, scrub_text
from repro.store import StoredEvent, StoreReader, StoreWriter
from repro_events.models import EVENT_KINDS
from store_support import evidence_record, run_record, started_writer

TIMEOUT = 30
LOG = {"level": "info", "verb": "read", "message": "reading the diff"}
# PEM markers built at run time: a literal private-key block in the source would (rightly)
# trip the repository secret scan.
PEM_BEGIN = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
PEM_END = "-----END " + "OPENSSH PRIVATE KEY-----"


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


@pytest.fixture
def bus(writer: StoreWriter) -> EventBus:
    return EventBus(writer)


@pytest.fixture
def run_id(writer: StoreWriter) -> str:
    run = run_record()
    writer.create_run(run).result(TIMEOUT)
    return run.id


def test_every_kind_has_its_payload_version() -> None:
    assert set(PAYLOAD_VERSIONS) == set(EVENT_KINDS)
    assert all(version >= 1 for version in PAYLOAD_VERSIONS.values())


def test_the_bus_builds_the_envelope(bus: EventBus, run_id: str) -> None:
    (event,) = bus.emit(run_id, "log.line", stage="read", status="progress", payload=LOG).result(
        TIMEOUT
    )
    envelope = event.envelope()
    assert re.fullmatch(r"evt_[0-9A-HJKMNP-TV-Z]{26}", envelope["id"])
    assert envelope["seq"] == 1
    assert (envelope["v"], envelope["pv"]) == (1, PAYLOAD_VERSIONS["log.line"])
    assert envelope["producer"] == producer_tag()
    assert re.fullmatch(r"repro/[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*", producer_tag())
    assert envelope["ts"].endswith("Z")
    assert (envelope["agent"], envelope["target"]) == (None, None)
    assert "parent" not in envelope


def test_a_parent_is_kept(bus: EventBus, run_id: str) -> None:
    (first,) = bus.emit(run_id, "log.line", stage="read", status="progress", payload=LOG).result(
        TIMEOUT
    )
    (second,) = bus.emit(
        run_id, "log.line", stage="read", status="ok", payload=LOG, parent=first.id
    ).result(TIMEOUT)
    assert second.envelope()["parent"] == first.id


def test_evidence_is_emitted_without_a_seq_and_gets_its_events(
    bus: EventBus, writer: StoreWriter, run_id: str
) -> None:
    record = evidence_record(run_id)  # no seq: only the writer knows it (found in D01)
    (event,) = bus.emit(
        run_id, "evidence.created", stage="run", status="ok", payload={"evidence": record}
    ).result(TIMEOUT)
    assert event.envelope()["payload"]["evidence"]["seq"] == event.seq
    broken = {**record, "id": "ev_not-an-id"}
    with pytest.raises(EventError, match=r"invalid evidence\.created"):
        bus.emit(run_id, "evidence.created", stage="run", status="ok", payload={"evidence": broken})


@pytest.mark.parametrize(
    ("kind", "fields", "message"),
    [
        ("log.lines", {"stage": "read", "status": "ok", "payload": LOG}, "unknown event kind"),
        ("log.line", {"stage": "read", "status": "ok", "payload": {"level": "info"}}, "invalid"),
        ("log.line", {"stage": "lunch", "status": "ok", "payload": LOG}, "invalid"),
        ("log.line", {"stage": "read", "status": "done", "payload": LOG}, "invalid"),
        ("run.started", {"stage": "build", "status": "start", "payload": {}}, "invalid"),
    ],
)
def test_invalid_events_are_refused_before_they_reach_the_store(
    bus: EventBus, run_id: str, kind: str, fields: dict[str, object], message: str
) -> None:
    with pytest.raises(EventError, match=message):
        bus.emit(run_id, kind, **fields)


def test_credentials_are_scrubbed_before_storage(
    bus: EventBus, run_id: str, tmp_path: Path
) -> None:
    token = "ghp_" + "a1B2" * 9
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    payload = {"level": "info", "verb": "read", "message": f"token {token} and key {key}"}
    target = {"file": f"notes/{key}.txt"}
    bus.emit(run_id, "log.line", stage="read", status="ok", payload=payload, target=target).result(
        TIMEOUT
    )
    with StoreReader(tmp_path / "repro.db") as reader:
        (event,) = reader.events(run_id)
    assert token not in event.body
    assert key not in event.body
    envelope = event.envelope()
    assert envelope["payload"]["message"] == f"token {REDACTED} and key {REDACTED}"
    assert envelope["target"] == {"file": f"notes/{REDACTED}.txt"}


def test_a_name_with_an_undecodable_byte_is_stored_escaped(
    bus: EventBus, run_id: str, tmp_path: Path
) -> None:
    """H02 (found on click): a file name Python decoded with surrogate escapes holds a lone
    surrogate, which UTF-8 JSON cannot carry. It is stored as its escape, never refused."""
    name = "out/" + chr(0xDCFF) + ".txt"
    payload = {"level": "info", "verb": "run", "message": f"wrote {name}"}
    target = {"file": name}
    bus.emit(run_id, "log.line", stage="run", status="ok", payload=payload, target=target).result(
        TIMEOUT
    )
    with StoreReader(tmp_path / "repro.db") as reader:
        (event,) = reader.events(run_id)
    envelope = event.envelope()
    assert envelope["payload"]["message"] == "wrote out/\\udcff.txt"
    assert envelope["target"] == {"file": "out/\ufffd.txt"}  # paths allow no backslash


def test_the_home_directory_is_stored_as_a_tilde(
    bus: EventBus, run_id: str, tmp_path: Path
) -> None:
    """H03: an absolute path in an event (a write the sandbox saw, say) does not name the user."""
    home = str(Path.home())
    for written in (f"{home}{os.sep}notes.txt", home.replace("\\", "/") + "/notes.txt"):
        payload = {"level": "info", "verb": "run", "message": f"wrote {written}"}
        bus.emit(run_id, "log.line", stage="run", status="ok", payload=payload).result(TIMEOUT)
    with StoreReader(tmp_path / "repro.db") as reader:
        stored = [event.envelope()["payload"]["message"] for event in reader.events(run_id)]
    assert stored == [f"wrote ~{os.sep}notes.txt", "wrote ~/notes.txt"]
    assert all(home not in event for event in stored)


def test_subscribers_see_committed_events_in_order(bus: EventBus, run_id: str) -> None:
    seen: list[int] = []
    unsubscribe = bus.subscribe(lambda events: seen.extend(e.seq for e in events))
    futures = [
        bus.emit(run_id, "log.line", stage="read", status="progress", payload=LOG)
        for _ in range(30)
    ]
    for future in futures:
        future.result(TIMEOUT)
    assert seen == list(range(1, 31))
    unsubscribe()
    bus.emit(run_id, "log.line", stage="read", status="ok", payload=LOG).result(TIMEOUT)
    assert len(seen) == 30


def test_a_failing_subscriber_is_dropped_and_the_others_carry_on(
    bus: EventBus, run_id: str
) -> None:
    calls = {"bad": 0}
    good: list[int] = []

    def bad(_: Sequence[StoredEvent]) -> None:
        calls["bad"] += 1
        raise RuntimeError("client broke")

    bus.subscribe(bad)
    bus.subscribe(lambda events: good.extend(e.seq for e in events))
    for _ in range(3):
        bus.emit(run_id, "log.line", stage="read", status="ok", payload=LOG).result(TIMEOUT)
    assert calls["bad"] == 1
    assert good == [1, 2, 3]


@pytest.mark.parametrize(
    ("text", "sensitive"),
    [
        ("ghp_" + "x" * 36, "x" * 36),
        ("github_pat_" + "Ab1_" * 10, "Ab1_" * 10),
        ("gho_" + "Y" * 36, "Y" * 36),
        ("ghu_" + "z9" * 18, "z9" * 18),
        ("ghs_" + "Q" * 36, "Q" * 36),
        ("ghr_" + "w" * 36, "w" * 36),
        ("AKIA" + "Z" * 16, "Z" * 16),
        ("ASIA" + "1" * 16, "1" * 16),
        (f"{PEM_BEGIN}\nb3BlbnNzaC1rZXk=\n{PEM_END}", "b3BlbnNzaC1rZXk="),
        (f"{PEM_BEGIN}\nMIIEvQIBADANBg", "MIIEvQIBADANBg"),  # cut off: no end line
        ("Authorization: Bearer abcdefghijklmnop.qrstuvwxyz", "abcdefghijklmnop.qrstuvwxyz"),
    ],
)
def test_recognised_credentials_are_redacted(text: str, sensitive: str) -> None:
    scrubbed = scrub_text(f"before {text} after")
    assert REDACTED in scrubbed
    assert sensitive not in scrubbed
    assert scrubbed.startswith("before ")


@pytest.mark.parametrize(
    "text",
    [
        "def parse(ghp): return ghp_value",
        "AKIA is a prefix",
        "bearer of bad news",
        "-----BEGIN CERTIFICATE-----",
        "sha256 0123456789abcdef0123456789abcdef",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert scrub_text(text) == text


def test_scrub_walks_structures() -> None:
    token = "ghs_" + "k" * 36
    assert scrub({"a": [token, {"b": token}], "n": 3}) == {
        "a": [REDACTED, {"b": REDACTED}],
        "n": 3,
    }
