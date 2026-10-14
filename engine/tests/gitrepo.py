"""Test repositories built with git plumbing, so a tree can hold any name a hostile one might.

Trees are written with ``git mktree`` and committed with ``commit-tree``. Neither a working tree
nor the index is involved, and git's index refuses names such as ``..``, ``.git``, ``con`` or
``a:b`` ("Ignoring path"), but ``mktree`` writes them: a hostile repository can contain them,
so the tests must be able to as well. The user's global and system configuration is ignored,
identities and dates are fixed.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

IDENTITY = {
    "GIT_AUTHOR_NAME": "Repro Tests",
    "GIT_AUTHOR_EMAIL": "tests@repro.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "Repro Tests",
    "GIT_COMMITTER_EMAIL": "tests@repro.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}

#: A tree entry: content (bytes, or str written as UTF-8), and optionally its mode.
Entry = bytes | str | tuple[bytes | str, str]


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        config = path.parent / f".{path.name}.gitconfig"
        config.write_text("", encoding="utf-8")
        self.env = {
            **os.environ,
            **IDENTITY,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(config),
        }
        self.git("init", "-q", "-b", "main")
        self.parent: str | None = None
        self.files: dict[str, tuple[str, str]] = {}

    def git(self, *args: str, stdin: bytes | None = None) -> str:
        done = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", *args],
            cwd=self.path,
            env=self.env,
            input=stdin,
            capture_output=True,
            check=True,
        )
        return done.stdout.decode("utf-8", "surrogateescape").strip()

    def blob(self, content: bytes | str) -> str:
        data = content.encode("utf-8") if isinstance(content, str) else content
        return self.git("hash-object", "-w", "--stdin", stdin=data)

    def _tree(self, entries: Mapping[str, tuple[str, str]]) -> str:
        """Writes the tree for ``entries`` (path -> (mode, sha)), subtrees first."""
        here: dict[str, tuple[str, str, str]] = {}
        below: dict[str, dict[str, tuple[str, str]]] = {}
        for path, (mode, sha) in entries.items():
            name, slash, rest = path.partition("/")
            if slash:
                below.setdefault(name, {})[rest] = (mode, sha)
            else:
                kind = {"160000": "commit"}.get(mode, "blob")
                here[name] = (mode, kind, sha)
        for name, children in below.items():
            here[name] = ("040000", "tree", self._tree(children))
        payload = "".join(
            f"{mode} {kind} {sha}\t{name}\0" for name, (mode, kind, sha) in here.items()
        ).encode("utf-8", "surrogateescape")
        return self.git("mktree", "-z", stdin=payload)

    def commit(
        self, files: Mapping[str, Entry | None], message: str = "commit", *, fresh: bool = False
    ) -> str:
        """Applies ``files`` (``None`` removes a path) to the previous commit's files."""
        if fresh:
            self.files = {}
        for path, entry in files.items():
            if entry is None:
                self.files.pop(path, None)
                continue
            content, mode = entry if isinstance(entry, tuple) else (entry, "100644")
            sha = str(content) if mode == "160000" else self.blob(content)
            self.files[path] = (mode, sha)
        tree = self._tree(self.files)
        parents = [] if self.parent is None or fresh else ["-p", self.parent]
        sha = self.git("commit-tree", tree, *parents, "-m", message)
        self.parent = sha
        self.git("update-ref", "refs/heads/main", sha)
        return sha
