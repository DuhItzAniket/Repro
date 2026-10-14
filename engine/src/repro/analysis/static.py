"""The static analysis of a change, from two commits of a target repository (C06, C07)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from repro.analysis.blast import BlastRadius, blast_radius
from repro.analysis.changes import ChangedSymbols, changed_symbols
from repro.analysis.imports import DEFAULT_TIMEOUT, ImportGraph, import_graph
from repro.analysis.modules import module_names
from repro.gitops import Git, diff, read_blobs, regular_files


@dataclass(frozen=True, slots=True)
class StaticAnalysis:
    changes: ChangedSymbols
    base: ImportGraph
    head: ImportGraph
    blast: BlastRadius


def analyse(
    git: Git, base: str, head: str, workdir: Path, *, timeout: float = DEFAULT_TIMEOUT
) -> StaticAnalysis:
    """Changed symbols, both sides' import graphs and the blast radius of ``base..head``.

    Every Python file of both sides is read through one ``git cat-file --batch``; ``workdir``
    holds grimp's trees while it runs (C05 snapshots are for running the target, not this).
    """
    base_files, head_files = regular_files(git, base), regular_files(git, head)
    base_names, head_names = module_names(base_files.keys(), head_files.keys())
    wanted = [base_files[p] for p in base_names] + [head_files[p] for p in head_names]
    blobs = read_blobs(git, wanted)

    def read(shas: Sequence[str]) -> dict[str, bytes]:
        missing = [sha for sha in shas if sha not in blobs]
        return {**blobs, **read_blobs(git, missing)} if missing else blobs

    changes = changed_symbols(
        diff(git, base, head), read, base_files=base_files, head_files=head_files
    )
    graphs = [
        import_graph(
            {path: blobs[files[path]] for path in names},
            names,
            workdir / side,
            timeout=timeout,
        )
        for side, files, names in (
            ("base", base_files, base_names),
            ("head", head_files, head_names),
        )
    ]
    return StaticAnalysis(changes, graphs[0], graphs[1], blast_radius(changes.changes, *graphs))
