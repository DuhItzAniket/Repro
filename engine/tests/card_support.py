"""Golden cards (F05): a card with what differs between two runs of one fixture made fixed.

Run and evidence IDs become their order of appearance; the time, the machine (interpreter,
platform), Repro's version and the log's digest and size become placeholders; and the
measured numbers of timing (ratios, percentages) are replaced, since two runs never time alike.
Everything else, the status and its reasons, the gap, the invariants and the missing items, is
compared as it is.
"""

import json
import re
from typing import Any

_EVIDENCE = re.compile(r"ev_[0-9A-HJKMNP-TV-Z]{26}")
_RUN = re.compile(r"run_[0-9A-HJKMNP-TV-Z]{26}")
#: Measured timing: "x17.26", "1625%", "x1.04" (perf summaries and perf_budget's message).
_MEASURED = re.compile(r"x\d+\.\d+|\d+(?:\.\d+)?%")


def _timing(text: str) -> str:
    return _MEASURED.sub("<measured>", text)


def normalised(card: dict[str, Any]) -> str:
    """The card as indented JSON with run-to-run differences replaced."""
    text = json.dumps(card, sort_keys=True, ensure_ascii=False)
    ids: dict[str, str] = {}
    for found in _EVIDENCE.findall(text):
        ids.setdefault(found, f"ev_{len(ids) + 1:026d}")
    text = _EVIDENCE.sub(lambda m: ids[m.group(0)], text)
    text = _RUN.sub("run_" + "0" * 26, text)
    data = json.loads(text)
    conditions = data["conditions"]
    for key in ("python_version", "platform", "repro_version"):
        if conditions.get(key) is not None:
            conditions[key] = f"<{key}>"
    data["generated_at"] = "<generated_at>"
    data["replay"] = {"event_log_sha256": "<sha256>", "event_count": "<count>"}
    for item in data["gap"]:
        if item["check"] == "diff.perf":
            item["summary"] = _timing(item["summary"])
    for invariant in data["invariants"]:
        if invariant["name"] == "perf_budget":
            invariant["message"] = _timing(invariant["message"])
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
