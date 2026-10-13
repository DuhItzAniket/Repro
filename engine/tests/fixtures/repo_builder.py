"""Scripted fixture repositories (docs/TEST_STRATEGY.md §3).

Fixture repositories are generated at test time, never committed as nested ``.git`` directories.
A spec describes a tiny Python project on ``main`` plus one or more head branches. Commits use
fixed identities and dates, files are written with LF line endings, and the user's global and
system git configuration is ignored. The same spec therefore produces the same commit SHAs on
every machine and operating system.
"""

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

FIXED_DATE = "2026-01-01T00:00:00+00:00"
IDENTITY = {"name": "Repro Fixtures", "email": "fixtures@repro.invalid"}


@dataclass(frozen=True)
class RepoSpec:
    name: str
    description: str
    base: Mapping[str, str]  # path -> content on main
    heads: Mapping[str, Mapping[str, str | None]]  # branch -> {path: content, or None to delete}
    pr_description: Mapping[str, str] = field(default_factory=dict)  # branch -> PR text


@dataclass(frozen=True)
class BuiltRepo:
    path: Path
    base_sha: str
    head_shas: dict[str, str]


def _git(repo: Path, *args: str, env: Mapping[str, str]) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _write_tree(root: Path, files: Mapping[str, str | None]) -> None:
    for rel, content in files.items():
        target = root / Path(rel)
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def build_repo(spec: RepoSpec, dest: Path) -> BuiltRepo:
    """Create the repository described by ``spec`` at ``dest`` (which must not exist)."""
    dest.mkdir(parents=True)
    empty_config = dest.parent / f".{spec.name}.gitconfig"
    empty_config.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(empty_config),
        "GIT_AUTHOR_NAME": IDENTITY["name"],
        "GIT_AUTHOR_EMAIL": IDENTITY["email"],
        "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_NAME": IDENTITY["name"],
        "GIT_COMMITTER_EMAIL": IDENTITY["email"],
        "GIT_COMMITTER_DATE": FIXED_DATE,
    }
    _git(dest, "init", "-q", "-b", "main", env=env)
    _write_tree(dest, spec.base)
    _git(dest, "add", "-A", env=env)
    _git(dest, "commit", "-q", "-m", f"{spec.name}: base", env=env)
    base_sha = _git(dest, "rev-parse", "HEAD", env=env)
    head_shas = {}
    for branch, changes in spec.heads.items():
        _git(dest, "checkout", "-q", "-b", branch, "main", env=env)
        _write_tree(dest, changes)
        _git(dest, "add", "-A", env=env)
        message = spec.pr_description.get(branch, f"{spec.name}: {branch}")
        _git(dest, "commit", "-q", "-m", message, env=env)
        head_shas[branch] = _git(dest, "rev-parse", "HEAD", env=env)
        _git(dest, "checkout", "-q", "main", env=env)
    return BuiltRepo(path=dest, base_sha=base_sha, head_shas=head_shas)
