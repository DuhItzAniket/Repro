"""A run's evidence as agents see it: listed, related to targets, rendered (G03).

Agents may cite only evidence the engine produced (ground rule 1), so what they read of it is
built here from the run's own log: ``evidence.created`` payloads, and ``symbol.changed`` for
which file each changed symbol is in.

**Rendering is the text quotes are checked against** (G05: every quote must be an exact
substring of it), so it is a pure function of the evidence and the same on every machine and in
every run of the same change:

- items are ordered by their content (type, targets, summary), not by ID: IDs follow creation
  time, which varies with how a run's jobs happened to interleave;
- only fields that describe the finding are shown, per type; what varies between runs of the
  same change (timings, process IDs, digests, artifacts) is left out, and a performance ratio
  is shown to one decimal;
- the engine's bookkeeping (``environment``, ``policy``) is not shown;
- strings are made portable (``repro.agents.untrusted.portable``) and cut at ``MAX_FIELD``.

Everything that can carry the target's own text (summaries, messages, values, details) is
inside an ``untrusted_content`` block; the evidence ID, type, stability, origin and targets,
which are the engine's, are outside it.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from repro.agents.untrusted import block, portable

#: Evidence agents are never shown: the engine's own bookkeeping.
HIDDEN: Final = frozenset({"environment", "policy"})
#: The fields shown per type, in this order; nested fields as ``a.b``.
FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "test_outcome": (
        "class",
        "base_outcome",
        "head_outcome",
        "base_again_outcome",
        "likely_flaky",
        "base_message",
        "head_message",
    ),
    "test_change": ("change", "detail"),
    "behaviour_diff": (
        "change",
        "calls",
        "test_modified",
        "reproducer.call",
        "reproducer.base",
        "reproducer.head",
        "reproducer.reproduced",
    ),
    "probe_diff": (
        "provenance",
        "change",
        "inputs_differing",
        "inputs_tried",
        "reproducer.call",
        "reproducer.base",
        "reproducer.head",
    ),
    "api_diff": ("breakage", "old", "new"),
    "dep_diff": ("package", "change", "base", "head", "source"),
    "lock_drift": ("side", "package", "locked", "installed"),
    "perf_diff": ("verdict", "ratio"),
    "invariant": ("invariant", "result", "cites"),
    "policy_change": ("change", "weakened"),
    "network_attempt": ("side", "event", "detail", "count"),
    "subprocess_attempt": ("side", "event", "detail", "count"),
    "file_attempt": ("side", "event", "detail", "count"),
    "selection": (),
    "static_change": (),
}
#: Evidence types in the order a listing shows them.
TYPE_ORDER: Final = tuple(FIELDS)
MAX_FIELD: Final = 600
MAX_SUMMARY: Final = 400
_LIST_SUMMARY: Final = 160


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 15]} ...[{len(text)} chars]"


def _field(data: Mapping[str, Any], dotted: str) -> Any:
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _show(value: Any) -> str:
    if isinstance(value, str):
        return _cut(portable(value), MAX_FIELD)
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, float):
        return f"{value:.1f}"
    return _cut(portable(json.dumps(value, sort_keys=True, ensure_ascii=False)), MAX_FIELD)


def target_text(target: Mapping[str, str]) -> str:
    return ", ".join(f"{key} {target[key]}" for key in ("file", "symbol", "test") if key in target)


@dataclass(frozen=True, slots=True)
class Item:
    """One evidence record an agent may see and cite."""

    id: str
    type: str
    targets: tuple[Mapping[str, str], ...]
    summary: str
    data: Mapping[str, Any]
    stability: str
    origin: str

    @property
    def order(self) -> tuple[int, str, str, str]:
        rank = TYPE_ORDER.index(self.type) if self.type in TYPE_ORDER else len(TYPE_ORDER)
        targets = json.dumps(list(self.targets), sort_keys=True)
        return (rank, targets, self.shown_summary, self.id)

    @property
    def shown_summary(self) -> str:
        if self.type == "perf_diff":  # the summary's numbers vary run to run
            test = next((t["test"] for t in self.targets if "test" in t), "the test")
            return f"{self.data.get('verdict', 'unknown')}: {test}"
        return _cut(portable(self.summary), MAX_SUMMARY)

    def line(self) -> str:
        """One line for a listing: ID, type, stability, origin, summary."""
        return (
            f"{self.id}  {self.type}  {self.stability}  {self.origin}  "
            f"{_cut(self.shown_summary, _LIST_SUMMARY)}"
        )

    def render(self) -> str:
        """The full view ``get_evidence`` returns, and quotes are checked against."""
        targets = "; ".join(target_text(t) for t in self.targets)
        header = (
            f"evidence {self.id}\ntype: {self.type}\nstability: {self.stability}\n"
            f"origin: {self.origin}\ntargets: {targets}"
        )
        lines = [f"summary: {self.shown_summary}"]
        for name in FIELDS.get(self.type, tuple(sorted(self.data))):
            value = _field(self.data, name)
            if value is not None:
                lines.append(f"{name}: {_show(value)}")
        return f"{header}\n{block('evidence', chr(10).join(lines), id=self.id)}"


class EvidenceView:
    """A run's citable evidence and the files its changed symbols are in."""

    def __init__(self, items: Iterable[Item], symbol_files: Mapping[str, str]) -> None:
        self.items = sorted(items, key=lambda item: item.order)
        self.by_id = {item.id: item for item in self.items}
        self.symbol_files = dict(symbol_files)

    @classmethod
    def from_events(cls, events: Iterable[Mapping[str, Any]]) -> "EvidenceView":
        items, files = [], {}
        for event in events:
            payload = event["payload"]
            if event["kind"] == "symbol.changed":
                files[payload["symbol_id"]] = payload["file"]
            elif event["kind"] == "evidence.created":
                record = payload["evidence"]
                if record["type"] in HIDDEN:
                    continue
                items.append(
                    Item(
                        id=record["id"],
                        type=record["type"],
                        targets=tuple(dict(t) for t in record["targets"]),
                        summary=record["summary"],
                        data=record["data"],
                        stability=record["stability"],
                        origin=record["origin"],
                    )
                )
        return cls(items, files)

    def _files_of(self, target: Mapping[str, str]) -> set[str]:
        files = {target["file"]} if "file" in target else set()
        if "symbol" in target and target["symbol"] in self.symbol_files:
            files.add(self.symbol_files[target["symbol"]])
        if "test" in target:
            files.add(target["test"].split("::", 1)[0])
        return files

    def related(self, item: Item, target: Mapping[str, str]) -> bool:
        """Whether ``item`` is about ``target``: the same test or symbol, or the same file
        (a symbol's file being where it changed, a test's the file it is in)."""
        wanted = self._files_of(target)
        for own in item.targets:
            if any(own.get(key) and own.get(key) == target.get(key) for key in ("symbol", "test")):
                return True
            if wanted & self._files_of(own):
                return True
        return False

    def relevant(self, targets: Sequence[Mapping[str, str]]) -> list[Item]:
        """The items about any of ``targets``, in rendering order; all of them if none given."""
        if not targets:
            return list(self.items)
        return [item for item in self.items if any(self.related(item, t) for t in targets)]
