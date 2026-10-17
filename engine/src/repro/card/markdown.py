"""The card as Markdown (F05): for a PR comment, a job summary, or a person reading it.

Every value comes from the canonical card, in its order, so the text is as reproducible as the
card. Table cells have their pipes escaped and their line breaks folded.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

_HEADLINE = {
    "VERIFIED": "every claim is supported, no difference is unexplained, every invariant holds",
    "FLAGGED": "the run found a problem",
    "UNVERIFIABLE": "something could not be checked",
}


#: A URL safe to link as it is: https, and nothing Markdown would read as the link's end.
_LINKABLE: Final = re.compile(r"^https://[^\s()<>\[\]]+$")


def _link(text: str, url: Any) -> str:
    return f"[{text}]({url})" if isinstance(url, str) and _LINKABLE.match(url) else text


def _plain(value: Any) -> str:
    """Text someone else wrote (a pull request's title), shown as text, never as Markdown."""
    text = "-" if value is None or value == "" else str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#+!~|-])", r"\\\1", text)


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


def verified_why(card: Mapping[str, Any]) -> str:
    """Why a card with no reason is VERIFIED: what it did not check is listed, never hidden."""
    if card["missing"]:
        return "Nothing flags; what could not be checked, under Missing, leaves it verifiable."
    return "Nothing flags, and everything was checked."


def headline(card: Mapping[str, Any]) -> str:
    """``**STATUS**: what it means.``, the card's first line."""
    return f"**{card['status']}**: {_HEADLINE[card['status']]}."


def why(card: Mapping[str, Any]) -> list[str]:
    """The card's Why: the rules that decided its status, each with its detail."""
    return _why(card)


def _why(card: Mapping[str, Any]) -> list[str]:
    reasons = [r for r in card["status_reasons"] if r["decides"]]
    also = [r for r in card["status_reasons"] if not r["decides"]]
    lines = [f"- {r['detail']} (`{r['rule']}`)" for r in reasons]
    if not lines:
        lines = [f"- {verified_why(card)}"]
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


#: A missing item's targets shown in its row; the JSON card holds them all.
TARGETS_SHOWN: Final = 5


def _targets(item: Mapping[str, Any]) -> str | None:
    names = [str(next(iter(t.values()))) for t in item["targets"] if t]
    more = len(names) - TARGETS_SHOWN
    shown = ", ".join(names[:TARGETS_SHOWN]) + (f" and {more} more" if more > 0 else "")
    return shown or None


def _missing(card: Mapping[str, Any]) -> list[str]:
    rows = [
        [item["reason"], _targets(item), item["detail"], item.get("resolution")]
        for item in card["missing"]
    ]
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
        headline(card),
        "",
        f"- Repository: {_link(_cell(card['repo']['name']), card['repo']['url'])}",
        f"- Change: {_ref(c['base'])} to {_ref(c['head'])}",
    ]
    if card["pr"] is not None:
        pr = card["pr"]
        number = _link(f"#{pr['number']}", pr["url"]) + " " if pr["number"] is not None else ""
        lines.append(f"- Pull request: {number}{_plain(pr['title'])}")
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
