"""The card stage (F05): the last job of a run, assembling the card from the run's own log.

The job comes ``after`` every other job, however they ended: a run that could not check
everything still gets a card, saying so. It first logs a line and waits for it to be stored;
the store's single writer commits in order, so every earlier event is stored too. It then reads
the run's log back, assembles the card from it (``repro.card.assemble``), publishes it
(``card.published``, carrying the card) and records it in the ``cards`` table. ``run.finished``
takes its ``card_status`` from that event.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Protocol

from repro.card.assemble import assemble, canonical, published
from repro.orchestrator import Job, JobContext, OnFailure
from repro.store import StoreReader, StoreWriter

#: How long the job waits for its first event to be stored.
COMMIT_WAIT_S: Final = 60.0
#: ``card.published``'s status for each card status (ADR-0015's sense: a FLAGGED card fails).
EVENT_STATUS: Final = {"VERIFIED": "ok", "FLAGGED": "fail", "UNVERIFIABLE": "warn"}


class CardStore(Protocol):
    """Where the card job reads a run's log and records its card."""

    def events(self, run_id: str) -> list[dict[str, Any]]: ...

    def put(self, run_id: str, status: str, body: str, created_at: str) -> None: ...


class StoreCards:
    """A ``CardStore`` over the run store: its reader for the log, its writer for the card."""

    def __init__(self, database: Path, writer: StoreWriter) -> None:
        self.database = database
        self.writer = writer

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with StoreReader(self.database) as reader:
            return [json.loads(stored.body) for stored in reader.iter_events(run_id)]

    def put(self, run_id: str, status: str, body: str, created_at: str) -> None:
        self.writer.put_card(run_id, status, body, created_at).result(COMMIT_WAIT_S)


def card_job(store: CardStore, others: Sequence[str]) -> Job:
    """The ``card`` job, after every job in ``others``."""

    def run(ctx: JobContext) -> None:
        stored = ctx.emit(
            "log.line",
            status="progress",
            payload={"level": "info", "verb": "card", "message": "assembling the card"},
        )
        stored.result(COMMIT_WAIT_S)  # every event before it is stored too
        card = assemble(store.events(ctx.run_id))
        payload = published(card)
        ctx.emit("card.published", status=EVENT_STATUS[card["status"]], payload=payload)
        store.put(ctx.run_id, card["status"], canonical(card).decode("utf-8"), card["generated_at"])
        counts = payload["counts"]
        ctx.log(
            f"card: {card['status']} · {counts['gap_items']} gap items, {counts['unexplained']} "
            f"unexplained · {counts['missing']} missing · {counts['invariants_failed']} "
            "invariants failed"
        )

    return Job(
        "card",
        "card",
        run,
        OnFailure(reason="unsupported_project", detail="the card could not be assembled"),
        after=tuple(others),
    )
