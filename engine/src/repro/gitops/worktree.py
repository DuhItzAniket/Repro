"""Worktrees for host-side static reads (THREAT_MODEL T3: target code never runs from one).

A worktree is a checkout linked to the target repository, so it must always be removed, and on
Windows removal often meets files another process still holds open: an editor, an indexer or an
antivirus scan. Cleanup therefore goes:

1. ``git worktree remove --force``;
2. if anything is left, delete it, clearing read-only bits, and retry a locked file with growing
   pauses for up to ``budget_s`` seconds;
3. ``git worktree prune``, so the repository forgets the worktree even if a file is still stuck.

What could not be deleted is reported, not ignored.
"""

import contextlib
import os
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from repro.gitops.git import Git, GitError
from repro.gitops.snapshot import extended

CLEANUP_BUDGET_S: Final = 10.0


class CleanupError(RuntimeError):
    """A worktree directory could not be fully deleted; ``left`` is what remains."""

    def __init__(self, path: Path, left: list[str]) -> None:
        super().__init__(f"{path}: {len(left)} item(s) could not be deleted")
        self.left = left


def add_worktree(git: Git, commit: str, dest: Path) -> Path:
    """Checks ``commit`` out, detached, at ``dest`` (which must not exist)."""
    sha = git.resolve(commit)
    git.run("worktree", "add", "--detach", "--", str(dest), sha)
    return dest


def remove_worktree(
    git: Git,
    dest: Path,
    *,
    budget_s: float = CLEANUP_BUDGET_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Removes a worktree completely; raises ``CleanupError`` listing what could not go."""
    with contextlib.suppress(GitError):  # whatever git leaves is deleted below
        git.run("worktree", "remove", "--force", "--force", "--", str(dest))
    try:
        _delete(dest, budget_s, sleep)
    finally:
        git.run("worktree", "prune", check=False)


def _delete_once(path: Path) -> list[str]:
    """One pass of deleting ``path``; what could not be deleted."""
    failures: list[str] = []

    def note(function: Callable[..., Any], target: str, error: BaseException) -> None:
        if isinstance(error, FileNotFoundError):
            return
        if isinstance(error, PermissionError):
            # A read-only file cannot be deleted on Windows: clear the bit and try once more.
            try:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)  # noqa: PTH101
                function(target)
                return
            except OSError:
                pass
        failures.append(target)

    if os.path.lexists(extended(path)):
        shutil.rmtree(extended(path), onexc=note)
    return failures


def _delete(path: Path, budget_s: float, sleep: Callable[[float], None]) -> None:
    waited = 0.0
    delay = 0.1
    while True:
        failures = _delete_once(path)
        if not os.path.lexists(extended(path)):
            return
        if waited >= budget_s:
            raise CleanupError(path, failures or [str(path)])
        sleep(delay)  # a locked file: its owner may let go
        waited += delay
        delay = min(delay * 2, 1.0)
