"""The Reproduction Card (F05; ARCHITECTURE §7), assembled from a run's event log alone.

A card is a function of the events before its own ``card.published``: assembling it again from
a stored or exported log gives the same bytes (``canonical``), which is how a replay checks it.

- **Status and reasons**: F04's ``decide`` over ``repro.policy.gap.inputs_from_events``.
- **Conditions**: the refs, the repository and the language from ``run.started``; head's
  interpreter (or, for JavaScript, Node.js) and lock (else base's) from ``env.provisioned``;
  the platform, the lower isolation level and the network from ``sandbox.ready`` (``enforced``
  only if every side's was); the seeds from the tests job's ``environment`` evidence (Python's
  hash seeds, or the seed of JavaScript's shuffled second base run); Repro's version from
  ``run.started``'s producer. What a run did not reach is null, never guessed. A log from
  before K08 has no language, and its card has none of K08's conditions.
- **Gap, invariants, missing**: the gap items with their evidence's type and summary and what
  the rules made of them; each ``invariant.result``; every ``missing.recorded`` item.
- **Replay**: the SHA-256 of the canonical log the card rests on, its event count, and its last
  event's time as ``generated_at``.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from repro.policy.gap import inputs_from_events
from repro.policy.status import GapItem, decide

CARD_VERSION: Final = 1
LEVELS: Final = ("L0", "L1", "L2", "L3", "L4", "L5")


def canonical(value: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def before_card(events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The events a card rests on: those before the run's ``card.published``, in ``seq`` order
    (the whole log when it has none)."""
    ordered = sorted(events, key=lambda e: int(e["seq"]))
    end = next((i for i, e in enumerate(ordered) if e["kind"] == "card.published"), len(ordered))
    return ordered[:end]


def log_digest(events: Sequence[Mapping[str, Any]]) -> str:
    """The SHA-256 of the events as canonical JSON lines."""
    sha = hashlib.sha256()
    for event in events:
        sha.update(canonical(event) + b"\n")
    return sha.hexdigest()


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [e["payload"] for e in events if e["kind"] == kind]


def _by_side(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {p["side"]: p for p in payloads if p.get("side") in ("base", "head")}


def conditions(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    started = next((e for e in events if e["kind"] == "run.started"), None)
    spec = started["payload"] if started is not None else {}
    envs = _by_side(_payloads(events, "env.provisioned"))
    ready = _by_side(_payloads(events, "sandbox.ready"))
    preferred = envs.get("head") or envs.get("base")
    sandbox = ready.get("head") or ready.get("base")
    levels = [p["isolation_level"] for p in ready.values()]
    networks = {p["network"] for p in ready.values()}
    environment = [
        e["data"]
        for e in (p["evidence"] for p in _payloads(events, "evidence.created"))
        if e["type"] == "environment"
    ]
    seeds = next(
        (
            {"hash_seed": data["hash_seed"], "hash_seed_repeat": data["hash_seed_repeat"]}
            for data in environment
            if "hash_seed" in data
        ),
        None,
    )
    producer = str(started.get("producer", "")) if started is not None else ""
    models = sorted(
        {p["verdict"]["model"] for p in _payloads(events, "verdict.issued")}
        | {str(p["model"]) for p in _payloads(events, "agent.spawned") if p.get("model")}
    )
    found = {
        "base": spec.get("base"),
        "head": spec.get("head"),
        "python_version": preferred["python_version"] if preferred else None,
        "platform": sandbox["platform"] if sandbox else None,
        "isolation_level": min(levels, key=LEVELS.index) if levels else None,
        "network": (
            None if not networks else "enforced" if networks == {"enforced"} else "detected-only"
        ),
        "lock_sha256": {
            side: (envs[side]["lock_sha256"] if side in envs else None) for side in ("base", "head")
        },
        "selected_tests": len(
            {e["target"]["test"] for e in events if e["kind"] == "test.selected"}
        ),
        "seeds": seeds,
        "repro_version": producer.removeprefix("repro/") or "unknown",
        "models": models,
    }
    # K08: only where run.started records a language, so an older log's card is the same.
    if "language" in spec:
        found["language"] = spec["language"]
    if spec.get("language") == "javascript":
        found["node_version"] = preferred.get("node_version") if preferred else None
        shuffle = next((d["shuffle_seed"] for d in environment if "shuffle_seed" in d), None)
        if shuffle is not None:
            found["shuffle_seed"] = shuffle
    return found


def _gap_item(item: GapItem, evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    record = evidence.get(item.evidence_id)
    if record is None:  # a valid log creates evidence before citing it (repro-events validate)
        raise ValueError(f"{item.check} cites {item.evidence_id}, which the log does not hold")
    return {
        "evidence_id": item.evidence_id,
        "type": record["type"],
        "check": item.check,
        "kind": item.kind,
        "summary": str(record["summary"])[:1000],
        "origin": item.origin,
        "stability": item.stability,
        "resolution": item.resolution,
        "explained_by": list(item.explained_by),
    }


def assemble(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The card of the run whose log ``events`` is (only what precedes its ``card.published``
    counts)."""
    log = before_card(events)
    started = next((e for e in log if e["kind"] == "run.started"), None)
    if started is None:
        raise ValueError("the log has no run.started: no card can be assembled from it")
    spec = started["payload"]
    inputs = inputs_from_events(log)
    decision = decide(inputs)
    evidence = {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in log
        if e["kind"] == "evidence.created"
    }
    reasons = [(r, True) for r in decision.reasons] + [(r, False) for r in decision.incomplete]
    return {
        "card_version": CARD_VERSION,
        "run_id": started["run_id"],
        "status": decision.status,
        "repo": spec["repo"],
        "pr": spec["pr"],
        "conditions": conditions(log),
        "claims": [p["claim"] for p in _payloads(log, "claim.extracted")],
        "verdicts": [p["verdict"] for p in _payloads(log, "verdict.issued")],
        "status_reasons": [
            {
                "rule": reason.rule,
                "detail": reason.detail[:1000],
                "evidence_ids": list(dict.fromkeys(reason.evidence_ids)),
                "targets": list(reason.targets),
                "decides": decides,
            }
            for reason, decides in reasons
        ],
        "gap": [_gap_item(item, evidence) for item in inputs.gap],
        "invariants": [
            {
                "name": p["invariant"],
                "result": p["result"],
                "evidence_ids": list(p["evidence_ids"]),
                "message": p["message"],
            }
            for p in _payloads(log, "invariant.result")
        ],
        "missing": [p["missing"] for p in _payloads(log, "missing.recorded")],
        "replay": {"event_log_sha256": log_digest(log), "event_count": len(log)},
        "generated_at": log[-1]["ts"],
    }


def counts(card: Mapping[str, Any]) -> dict[str, int]:
    """``card.published``'s counts."""
    verdicts = [v["verdict"] for v in card["verdicts"]]
    return {
        "claims": len(card["claims"]),
        "supported": verdicts.count("supported"),
        "contradicted": verdicts.count("contradicted"),
        "unverifiable": verdicts.count("unverifiable"),
        "gap_items": len(card["gap"]),
        "unexplained": sum(1 for g in card["gap"] if g["resolution"] == "flagged"),
        "missing": len(card["missing"]),
        "invariants_failed": sum(1 for i in card["invariants"] if i["result"] == "fail"),
    }


@dataclass(frozen=True, slots=True)
class Regenerated:
    """A card assembled again from a log, and the digest of the card the log published."""

    card: dict[str, Any]
    sha256: str
    published_sha256: str | None  # None: the log holds no card.published

    @property
    def identical(self) -> bool:
        return self.published_sha256 == self.sha256


def regenerate(events: Iterable[Mapping[str, Any]]) -> Regenerated:
    """The card a log rests on, assembled again, with the digest its ``card.published`` gave."""
    log = list(events)
    card = assemble(log)
    claimed = next((e for e in log if e["kind"] == "card.published"), None)
    return Regenerated(
        card,
        digest(canonical(card)),
        str(claimed["payload"]["card_sha256"]) if claimed is not None else None,
    )


def published(card: Mapping[str, Any]) -> dict[str, Any]:
    """The ``card.published`` payload: the status, the card's digest, its counts and the card."""
    return {
        "status": card["status"],
        "card_sha256": digest(canonical(card)),
        "counts": counts(card),
        "card": dict(card),
    }
