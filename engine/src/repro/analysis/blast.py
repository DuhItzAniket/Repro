"""Blast radius: the changed symbols and the modules that import them (ARCHITECTURE §9).

A change's modules are the modules of its symbols, before and after (a moved symbol leaves one
and enters another). Their importers are affected at distance 1, the importers of those at 2,
and so on, over the import edges of both sides together: an importer that a change removed
was still affected by it. Static imports are module-level, so an affected module appears as
its ``<module>`` symbol; symbol-level dependents come from the dynamic map (Stage E).

The cockpit's graph is both sides too: every module, every import, and a node per changed
function, method or class.
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from repro.analysis.changes import SymbolChange
from repro.analysis.imports import ImportGraph
from repro.analysis.symbols import MODULE_QUALNAME


def module_of(symbol_id: str) -> str:
    return symbol_id.partition(":")[0]


def module_symbol(module: str) -> str:
    return f"{module}:{MODULE_QUALNAME}#0"


@dataclass(frozen=True, slots=True)
class BlastRadius:
    changed: tuple[str, ...]
    affected: tuple[tuple[str, int], ...]  # (symbol_id, distance), nearest first
    module_level_changes: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        """The ``blast.computed`` payload."""
        return {
            "changed": list(self.changed),
            "affected": [{"symbol_id": s, "distance": d} for s, d in self.affected],
            "module_level_changes": list(self.module_level_changes),
        }


def downstream(sources: Iterable[str], base: ImportGraph, head: ImportGraph) -> dict[str, int]:
    """``sources`` at distance 0, their importers at 1, and so on, over both sides' imports."""
    importers: dict[str, set[str]] = {}
    for importer, imported in base.imports | head.imports:
        importers.setdefault(imported, set()).add(importer)
    start = sorted(set(sources))
    distance = dict.fromkeys(start, 0)
    queue = deque(start)
    while queue:
        module = queue.popleft()
        for importer in sorted(importers.get(module, ())):
            if importer not in distance:
                distance[importer] = distance[module] + 1
                queue.append(importer)
    return distance


def blast_radius(
    changes: Sequence[SymbolChange], base: ImportGraph, head: ImportGraph
) -> BlastRadius:
    changed = tuple(dict.fromkeys(change.symbol_id for change in changes))
    ids = [i for c in changes for i in (c.symbol_id, c.previous_symbol_id) if i is not None]
    module_level = sorted({module_of(i) for i in ids if f":{MODULE_QUALNAME}#" in i})
    distance = downstream((module_of(i) for i in ids), base, head)
    excluded = set(changed)
    affected = sorted(
        (
            (module_symbol(module), d)
            for module, d in distance.items()
            if d > 0 and module_symbol(module) not in excluded
        ),
        key=lambda item: (item[1], item[0]),
    )
    return BlastRadius(changed, tuple(affected), tuple(module_level))


def graph_payloads(
    base: ImportGraph, head: ImportGraph, changes: Sequence[SymbolChange]
) -> list[tuple[str, dict[str, Any]]]:
    """``graph.node`` and ``graph.edge`` payloads for both sides: modules, then changed
    functions, methods and classes, then imports (head's file wins for a module on both)."""
    modules = {**base.modules, **head.modules}
    events: list[tuple[str, dict[str, Any]]] = [
        ("graph.node", {"node": _node(name, "module", name, file, None)})
        for name, file in sorted(modules.items())
    ]
    for change in changes:
        if change.kind == "module":
            continue  # the module's own node stands for it
        lines = change.head_lines or change.base_lines
        qualname = change.symbol_id.partition(":")[2].rpartition("#")[0]
        line = lines[0] if lines else None
        node = _node(change.symbol_id, change.kind, qualname, change.file, line)
        events.append(("graph.node", {"node": node}))
    events.extend(
        ("graph.edge", {"source": importer, "target": imported, "type": "imports"})
        for importer, imported in sorted(base.imports | head.imports)
    )
    return events


def _node(
    node_id: str, kind: str, name: str, file: str, line: int | None
) -> dict[str, str | int | None]:
    return {"id": node_id, "type": kind, "name": name, "file": file, "line": line}
