"""The card as Markdown (F05): for a PR comment, a job summary, or a person reading it.

Every value comes from the canonical card, in its order, so the text is as reproducible as the
card. Table cells have their pipes escaped and their line breaks folded.
"""

from collections.abc import Mapping, Sequence
from typing import Any

_HEADLINE = {
    "VERIFIED": "every claim is supported, no difference is unexplained, every invariant holds",
    "FLAGGED": "the run found a problem",
    "UNVERIFIABLE": "something could not be checked",
}


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    if not rows:
        return ["None."]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines


def _ref(ref: Mapping[str, Any] | None) -> str:
    return f"`{ref['ref']}` ({ref['sha'][:12]})" if ref else "-"


def _why(card: Mapping[str, Any]) -> list[str]:
    reasons = [r for r in card["status_reasons"] if r["decides"]]
    also = [r for r in card["status_reasons"] if not r["decides"]]
    lines = [f"- {r['detail']} (`{r['rule']}`)" for r in reasons]
    if not lines:
        lines = ["- Nothing flags, and everything was checked."]
    if also:
        lines += ["", "Also not checked:", ""]
        lines += [f"- {r['detail']} (`{r['rule']}`)" for r in also]
    return lines


def _gap(card: Mapping[str, Any]) -> list[str]:
    columns = ["Evidence", "Check", "Kind", "Summary", "Origin", "Stability", "Result"]
    rows = [
        [
            g["evidence_id"],
            g["check"],
            g["kind"],
            g["summary"],
            g["origin"],
            g["stability"],
            g["resolution"]
            + (f" (explained by {', '.join(g['explained_by'])})" if g["explained_by"] else ""),
        ]
        for g in card["gap"]
    ]
    return _table(columns, rows)


def _missing(card: Mapping[str, Any]) -> list[str]:
    rows = []
    for item in card["missing"]:
        targets = ", ".join(str(next(iter(t.values()))) for t in item["targets"] if t)
        rows.append([item["reason"], targets or None, item["detail"], item.get("resolution")])
    return _table(["Reason", "Targets", "Detail", "What would resolve it"], rows)


def _conditions(card: Mapping[str, Any]) -> list[str]:
    c = card["conditions"]
    seeds = c["seeds"]
    locks = c["lock_sha256"]
    hashes = f"{seeds['hash_seed']}, {seeds['hash_seed_repeat']}" if seeds else None
    return _table(
        ["Condition", "Value"],
        [
            ["Python", c["python_version"]],
            ["Platform", c["platform"]],
            ["Isolation", c["isolation_level"]],
            ["Network", c["network"]],
            ["Lock, base", locks["base"]],
            ["Lock, head", locks["head"]],
            ["Selected tests", c["selected_tests"]],
            ["Hash seeds (A, A2)", hashes],
            ["Repro", c["repro_version"]],
            ["Models", ", ".join(c["models"]) or None],
        ],
    )


def render(card: Mapping[str, Any]) -> str:
    """The card in Markdown."""
    c = card["conditions"]
    lines = [
        f"# Reproduction Card: {card['status']}",
        "",
        f"**{card['status']}**: {_HEADLINE[card['status']]}.",
        "",
        f"- Repository: {_cell(card['repo']['name'])}",
        f"- Change: {_ref(c['base'])} to {_ref(c['head'])}",
    ]
    if card["pr"] is not None:
        lines.append(f"- Pull request: {_cell(card['pr']['title'])}")
    lines += ["", "## Why", "", *_why(card), "", "## Claims", ""]
    verdicts = {v["claim_id"]: v["verdict"] for v in card["verdicts"]}
    lines += _table(
        ["Claim", "Text", "Verdict"],
        [[k["id"], k["text"], verdicts.get(k["id"], "not judged")] for k in card["claims"]],
    )
    lines += ["", "## Gap", "", *_gap(card), "", "## Invariants", ""]
    lines += _table(
        ["Invariant", "Result", "Detail"],
        [[i["name"], i["result"], i["message"]] for i in card["invariants"]],
    )
    lines += ["", "## Missing", "", *_missing(card), "", "## Conditions", "", *_conditions(card)]
    replay = card["replay"]
    lines += [
        "",
        "## Replay",
        "",
        f"`repro replay {card['run_id']}` assembles this card again from its "
        f"{replay['event_count']} events (log SHA-256 `{replay['event_log_sha256']}`); it was "
        f"generated at {card['generated_at']}.",
        "",
    ]
    return "\n".join(lines)
