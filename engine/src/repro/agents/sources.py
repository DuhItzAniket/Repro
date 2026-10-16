"""The change's files, as agents may read them: from git objects, by checked paths (G03).

Agents read source code and diffs of the two commits a run compares. They are read from the
repository's git objects, not the snapshots: the target's own tests ran in the snapshots and
could have rewritten them, but no target code can change a commit. Reading goes through
``repro.gitops.Git`` (no hooks, no fsmonitor, ``--no-ext-diff`` and ``--no-textconv`` so the
repository's attributes run nothing).

A path is the repository-relative, ``/``-separated path git lists. Anything else is refused
before git sees it: an absolute or drive path, a ``.`` or ``..`` segment, a backslash, a
colon (which git would read as pathspec magic), control characters, quotes or angle brackets.
Only regular files are read (not symlinks or submodules), up to ``MAX_FILE_BYTES``.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from repro.gitops import Git, GitError

Side = Literal["base", "head"]
SIDES: Final[tuple[Side, ...]] = ("base", "head")
MAX_PATH: Final = 400
MAX_FILE_BYTES: Final = 1_000_000
_SEGMENT: Final = re.compile(r"[^\\:\x00-\x1f\x7f\"<>|?*]+")
#: ``git ls-tree`` output for one entry: mode, type, object id, then a tab and the path.
_TREE_ENTRY: Final = re.compile(rb"^(\d{6}) (\w+) ([0-9a-f]{40}|[0-9a-f]{64})\t")


class SourceError(ValueError):
    """A path or range an agent may not read, said plainly enough to correct."""


def checked_path(path: object) -> str:
    """``path`` if it is a plain repository-relative file path; else ``SourceError``."""
    if not isinstance(path, str) or not path or len(path) > MAX_PATH:
        raise SourceError(f"a path is a repository-relative string of 1 to {MAX_PATH} characters")
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", "..") or not _SEGMENT.fullmatch(segment):
            raise SourceError(
                f"{path!r} is not a plain repository path: relative, '/'-separated, "
                "no '.' or '..' segments, no '\\', ':', quotes, '<', '>' or control characters"
            )
    return path


@dataclass(frozen=True, slots=True)
class RepoSources:
    """The two commits of a run, read through git."""

    git: Git
    base: str
    head: str

    def commit(self, side: object) -> str:
        if side == "base":
            return self.base
        if side == "head":
            return self.head
        raise SourceError(f"side is 'base' or 'head', not {side!r}")

    def read(self, side: object, path: object) -> str | None:
        """The file's text on that side (lines end in LF); None if the side has no such file."""
        sha, checked = self.commit(side), checked_path(path)
        try:
            listing = self.git.run("ls-tree", "-z", "--end-of-options", sha, "--", checked)
        except GitError as exc:
            raise SourceError(f"cannot list {checked} on {side}: {exc}") from None
        if not listing:
            return None
        entry = _TREE_ENTRY.match(listing)
        if entry is None:
            raise SourceError(f"cannot read {checked} on {side}")
        mode, kind, blob = entry.group(1).decode(), entry.group(2), entry.group(3).decode()
        if kind != b"blob" or mode not in ("100644", "100755"):
            raise SourceError(f"{checked} on {side} is not a regular file")
        size = int(self.git.text("cat-file", "-s", blob))
        if size > MAX_FILE_BYTES:
            raise SourceError(f"{checked} on {side} is {size} bytes; at most {MAX_FILE_BYTES}")
        data = self.git.run("cat-file", "blob", blob)
        return data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")

    def diff(self, path: object, *, context: int = 3) -> str:
        """The file's unified diff from base to head; empty if it did not change."""
        checked = checked_path(path)
        try:
            data = self.git.run(
                "diff",
                f"-U{context}",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--end-of-options",
                self.base,
                self.head,
                "--",
                f":(literal){checked}",
            )
        except GitError as exc:
            raise SourceError(f"cannot diff {checked}: {exc}") from None
        return data.decode("utf-8", "replace").replace("\r\n", "\n")
