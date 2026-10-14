"""What changed between two commits: files, and the changed lines on each side.

Files come from ``git diff --raw -z``: NUL-separated, so a path is exact whatever it contains
(spaces, quotes, newlines, non-ASCII). Line ranges come from the ``@@ -a,b +c,d @@`` headers of
``git diff -U0``, matched to the files by order: both listings use the same rename detection and
the same filter, and git emits them in the same order. If the counts ever disagree, each file is
diffed on its own instead, by its exact paths.

No diff driver or text conversion runs (``--no-ext-diff --no-textconv``).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from repro.gitops.git import Git

ChangeStatus = Literal["A", "M", "D", "R", "T"]
#: Kinds whose patch is a single section with hunks (typechanges are two sections).
_PATCHED: Final = "ADMR"
_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NULL_SHA = re.compile(r"^0+$")
_DIFF_OPTIONS: Final = ("--no-color", "--no-ext-diff", "--no-textconv", "-M")


@dataclass(frozen=True, slots=True)
class Hunk:
    """One ``-U0`` hunk: ``count`` lines from ``start`` on each side (0 lines: an insertion
    point, after line ``start``)."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True, slots=True)
class FileChange:
    status: ChangeStatus
    old_path: str | None
    new_path: str | None
    old_mode: str
    new_mode: str
    old_blob: str | None
    new_blob: str | None
    similarity: int | None = None
    binary: bool = False
    hunks: tuple[Hunk, ...] = field(default_factory=tuple)

    @property
    def path(self) -> str:
        """The path on head, or on base for a deletion."""
        return self.new_path if self.new_path is not None else str(self.old_path)

    def changed_lines(self, side: Literal["old", "new"]) -> list[range]:
        """The 1-based line ranges changed on one side (removed on old, added on new)."""
        ranges = []
        for hunk in self.hunks:
            start, count = (
                (hunk.old_start, hunk.old_count)
                if side == "old"
                else (hunk.new_start, hunk.new_count)
            )
            if count:
                ranges.append(range(start, start + count))
        return ranges


def _blob(sha: str) -> str | None:
    return None if _NULL_SHA.match(sha) else sha


def parse_raw(output: bytes) -> list[FileChange]:
    """Parses ``git diff --raw -z --no-abbrev`` output."""
    fields = output.split(b"\0")
    changes: list[FileChange] = []
    i = 0
    while i < len(fields) and fields[i]:
        meta = fields[i].decode("ascii")
        if not meta.startswith(":"):
            raise ValueError(f"unexpected raw diff record: {meta[:40]!r}")
        old_mode, new_mode, old_sha, new_sha, status = meta[1:].split(" ")
        kind = status[0]
        score = int(status[1:]) if status[1:] else None
        first = fields[i + 1].decode("utf-8", "surrogateescape")
        i += 2
        if kind in "RC":
            second = fields[i].decode("utf-8", "surrogateescape")
            i += 1
            old_path, new_path = first, second
        elif kind == "A":
            old_path, new_path = None, first
        elif kind == "D":
            old_path, new_path = first, None
        else:
            old_path = new_path = first
        if kind not in "AMDRT":
            raise ValueError(f"unsupported change status {status!r} for {first!r}")
        changes.append(
            FileChange(
                status=kind,  # type: ignore[arg-type]
                old_path=old_path,
                new_path=new_path,
                old_mode=old_mode,
                new_mode=new_mode,
                old_blob=_blob(old_sha),
                new_blob=_blob(new_sha),
                similarity=score if kind == "R" else None,
            )
        )
    return changes


def parse_patch_sections(output: bytes) -> list[tuple[bool, tuple[Hunk, ...]]]:
    """For each ``diff --git`` section of a ``-U0`` patch: whether it is binary, and its hunks."""
    sections: list[tuple[bool, list[Hunk]]] = []
    for line in output.split(b"\n"):
        if line.startswith(b"diff --git "):
            sections.append((False, []))
        elif not sections:
            continue
        elif line.startswith(b"Binary files ") and line.endswith(b" differ"):
            sections[-1] = (True, sections[-1][1])
        elif line.startswith(b"@@ "):
            match = _HUNK.match(line)
            if match is None:
                raise ValueError(f"unparsable hunk header: {line[:60]!r}")
            a, b, c, d = match.groups()
            sections[-1][1].append(
                Hunk(int(a), 1 if b is None else int(b), int(c), 1 if d is None else int(d))
            )
    return [(binary, tuple(hunks)) for binary, hunks in sections]


def _with_patch(change: FileChange, binary: bool, hunks: tuple[Hunk, ...]) -> FileChange:
    return FileChange(
        status=change.status,
        old_path=change.old_path,
        new_path=change.new_path,
        old_mode=change.old_mode,
        new_mode=change.new_mode,
        old_blob=change.old_blob,
        new_blob=change.new_blob,
        similarity=change.similarity,
        binary=binary,
        hunks=hunks,
    )


def diff(git: Git, base: str, head: str) -> list[FileChange]:
    """Every file that differs between commits ``base`` and ``head``, with its changed lines."""
    raw = parse_raw(git.run("diff", "--raw", "-z", "--no-abbrev", *_DIFF_OPTIONS, base, head, "--"))
    patched = [change for change in raw if change.status in _PATCHED]
    sections = parse_patch_sections(
        git.run("diff", "-U0", f"--diff-filter={_PATCHED}", *_DIFF_OPTIONS, base, head, "--")
    )
    if len(sections) != len(patched):
        sections = [_one_file(git, base, head, change) for change in patched]
    by_change = dict(zip((id(c) for c in patched), sections, strict=True))
    result = []
    for change in raw:
        if id(change) in by_change:
            binary, hunks = by_change[id(change)]
            result.append(_with_patch(change, binary, hunks))
        else:
            result.append(change)  # a typechange: no line ranges
    return result


def _one_file(git: Git, base: str, head: str, change: FileChange) -> tuple[bool, tuple[Hunk, ...]]:
    paths: Sequence[str] = [p for p in (change.old_path, change.new_path) if p is not None]
    sections = parse_patch_sections(
        git.run(
            "diff",
            "-U0",
            *_DIFF_OPTIONS,
            base,
            head,
            "--",
            *(f":(literal){path}" for path in dict.fromkeys(paths)),
        )
    )
    if len(sections) != 1:
        raise ValueError(f"expected one patch section for {change.path!r}, got {len(sections)}")
    return sections[0]
