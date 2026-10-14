"""Running git against a target repository, safely.

A target repository is untrusted, and so is its configuration: a ``core.hooksPath`` committed by
a tool such as a hook manager, or a ``core.fsmonitor`` command, would make git run the
repository's programs when Repro reads it. Every command therefore runs with:

- ``-c core.longpaths=true`` (CLAUDE.md: per command; the user's configuration is never changed);
- ``-c core.hooksPath=<an empty directory>`` and ``-c core.fsmonitor=false``: no hook or monitor
  runs. Settings given with ``-c`` take precedence over the repository's own ``.git/config``;
- ``-c core.quotepath=false``, and no prompts (``GIT_TERMINAL_PROMPT=0``) or optional locks
  (``GIT_OPTIONAL_LOCKS=0``).

Diffs add ``--no-ext-diff --no-textconv`` (``repro.gitops.changes``), so no diff driver runs either.
"""

import atexit
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

DEFAULT_TIMEOUT_S: Final = 300.0
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class GitError(RuntimeError):
    """A git command failed; the message names the command and git's own complaint."""


def _empty_hooks_dir() -> Path:
    """One empty directory per process for ``core.hooksPath``: nothing in it can run."""
    path = Path(tempfile.mkdtemp(prefix="repro-no-hooks-"))
    atexit.register(shutil.rmtree, path, True)
    return path


_NO_HOOKS: Path | None = None


def no_hooks_dir() -> Path:
    global _NO_HOOKS  # noqa: PLW0603 - created once, on first use
    if _NO_HOOKS is None or not _NO_HOOKS.is_dir():
        _NO_HOOKS = _empty_hooks_dir()
    return _NO_HOOKS


class Git:
    """A target repository, read through hardened git commands."""

    def __init__(self, repo: Path, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        program = shutil.which("git")
        if program is None:
            raise GitError("git is not installed (repro doctor checks it)")
        self.program = program
        self.repo = repo
        self.timeout_s = timeout_s

    def command(self, *args: str) -> list[str]:
        """The full argument vector for ``git <args>`` in this repository."""
        return [
            self.program,
            "-c", "core.longpaths=true",
            "-c", f"core.hooksPath={no_hooks_dir()}",
            "-c", "core.fsmonitor=false",
            "-c", "core.quotepath=false",
            "-C", str(self.repo),
            *args,
        ]  # fmt: skip

    def environment(self) -> dict[str, str]:
        return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}

    def run(self, *args: str, stdin: bytes | None = None, check: bool = True) -> bytes:
        """Runs ``git <args>``; its stdout as bytes. Raises ``GitError`` on failure."""
        try:
            done = subprocess.run(  # noqa: S603 - a fixed program and our own arguments
                self.command(*args),
                input=stdin,
                capture_output=True,
                env=self.environment(),
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} timed out after {self.timeout_s:g} s") from None
        if check and done.returncode != 0:
            problem = done.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = problem[-1] if problem else f"exit status {done.returncode}"
            raise GitError(f"git {' '.join(args[:3])}: {reason}")
        return done.stdout

    def text(self, *args: str) -> str:
        return self.run(*args).decode("utf-8", "surrogateescape").strip()

    def is_repository(self) -> bool:
        try:
            self.run("rev-parse", "--git-dir")
        except GitError:
            return False
        return True

    def resolve(self, ref: str) -> str:
        """The full commit SHA ``ref`` names: a branch, tag, SHA or ``HEAD``, peeled to a commit."""
        try:
            sha = self.text(
                "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"
            )
        except GitError:
            raise GitError(f"{ref!r} does not name a commit in {self.repo}") from None
        if not _SHA.match(sha):
            raise GitError(f"{ref!r} resolved to something that is not a commit SHA: {sha!r}")
        return sha

    def merge_base(self, base: str, head: str) -> str | None:
        """Their best common ancestor, or ``None`` if the histories are unrelated."""
        done = self.run("merge-base", "--end-of-options", base, head, check=False)
        sha = done.decode("ascii", "replace").strip()
        return sha if _SHA.match(sha) else None
