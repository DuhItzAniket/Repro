"""Detected attempts as evidence (ADR-0004, L1): network, subprocess and file-write attempts.

Each distinct attempt (kind, detail, test) is one evidence record, with how many times it was
seen. The target is the test that made it when pytest was running one, otherwise what the
caller names (the command's working file, say). The records are ``evidence.created`` payloads'
``evidence``; the writer gives them their ``seq``.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Final

from repro import __version__
from repro.ids import new_evidence_id
from repro.sandbox.detect import Detection

EVIDENCE_TYPES: Final = {
    "network": "network_attempt",
    "subprocess": "subprocess_attempt",
    "file": "file_attempt",
}
_VERBS: Final = {
    "network": "network attempt",
    "subprocess": "started a process",
    "file": "wrote outside its directories",
}
#: Process IDs listed per record, at most.
MAX_PIDS: Final = 10


def detection_evidence(
    detections: Sequence[Detection],
    *,
    run_id: str,
    side: str,
    fallback_target: Mapping[str, str],
) -> list[dict[str, Any]]:
    """One evidence record per distinct attempt, in the order first seen."""
    groups: dict[tuple[str, str, str, str | None], list[Detection]] = defaultdict(list)
    for detection in detections:
        key = (detection.kind, detection.event, detection.detail, detection.test)
        groups[key].append(detection)
    records = []
    for (kind, event, detail, test), seen in groups.items():
        pids = sorted({d.pid for d in seen})
        where = f" in {test}" if test else ""
        records.append(
            {
                "id": new_evidence_id(),
                "run_id": run_id,
                "type": EVIDENCE_TYPES[kind],
                "targets": [{"test": test}] if test else [dict(fallback_target)],
                "summary": f"{side}: {_VERBS[kind]}{where}: {detail}"[:280],
                "data": {
                    "side": side,
                    "event": event,
                    "detail": detail,
                    "count": len(seen),
                    "pids": pids[:MAX_PIDS],
                    "enforced": False,  # detected at L1; only L3 enforces the network
                },
                "artifacts": [],
                "stability": "n/a",
                "origin": "n/a",
                "produced_by": {"component": "repro.sandbox", "version": __version__},
            }
        )
    return records
