"""Running git: refs, merge bases, and a target repository's own programs never run (C05)."""

import subprocess
import sys
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import Git, GitError, add_worktree, diff, remove_worktree, snapshot


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "target")


def test_refs_resolve_to_full_commit_shas(repo: Repo) -> None:
    first = repo.commit({"a.py": "a = 1\n"})
    second = repo.commit({"a.py": "a = 2\n"})
    repo.git("tag", "-a", "v1", "-m", "release", first)  # an annotated tag peels to its commit
    git = Git(repo.path)
    assert git.resolve("main") == second
    assert git.resolve("v1") == first
    assert git.resolve(first[:10]) == first
    assert git.resolve("main~1") == first


def test_a_detached_head_resolves(repo: Repo) -> None:
    first = repo.commit({"a.py": "a = 1\n"})
    repo.commit({"a.py": "a = 2\n"})
    repo.git("checkout", "-q", "--detach", first)
    assert Git(repo.path).resolve("HEAD") == first


@pytest.mark.parametrize("ref", ["nope", "--output=pwned", "main:a.py", ""])
def test_anything_that_is_not_a_commit_is_refused(repo: Repo, ref: str, tmp_path: Path) -> None:
    repo.commit({"a.py": "a = 1\n"})
    with pytest.raises(GitError, match="does not name a commit"):
        Git(repo.path).resolve(ref)
    assert not (repo.path / "pwned").exists()
    assert not (tmp_path / "pwned").exists()


def test_merge_base_and_unrelated_histories(repo: Repo) -> None:
    root = repo.commit({"a.py": "a = 1\n"})
    left = repo.commit({"b.py": "b = 1\n"})
    repo.parent = root
    right = repo.commit({"c.py": "c = 1\n"})
    git = Git(repo.path)
    assert git.merge_base(left, right) == root
    lonely = repo.commit({"d.py": "d"}, fresh=True)
    assert git.merge_base(left, lonely) is None


def test_a_missing_repository_is_an_error(tmp_path: Path) -> None:
    git = Git(tmp_path / "nothing")
    assert not git.is_repository()
    with pytest.raises(GitError):
        git.resolve("HEAD")


def test_every_command_runs_with_long_paths_and_no_hooks(repo: Repo) -> None:
    command = Git(repo.path).command("status")
    joined = " ".join(command)
    assert "core.longpaths=true" in joined
    assert "core.fsmonitor=false" in joined
    assert "core.hooksPath=" in joined


HOOK = '#!/bin/sh\necho ran > "$(git rev-parse --git-common-dir)/../ran-{name}"\n'


def plant_programs(repo: Repo) -> None:
    """Hooks in .git/hooks and in a committed hooks directory, and an fsmonitor command."""
    hooks = repo.path / ".git" / "hooks"
    tracked = repo.path / ".husky-like"
    tracked.mkdir()
    for directory in (hooks, tracked):
        for name in ("post-checkout", "pre-commit", "reference-transaction"):
            script = directory / name
            script.write_text(HOOK.format(name=f"{directory.name}-{name}"), encoding="utf-8")
            script.chmod(0o755)
    repo.git("config", "core.hooksPath", str(tracked))
    monitor = repo.path / "monitor.sh"
    monitor.write_text("#!/bin/sh\necho ran > ran-fsmonitor\n", encoding="utf-8")
    monitor.chmod(0o755)
    repo.git("config", "core.fsmonitor", str(monitor))


def markers(repo: Repo) -> list[str]:
    return sorted(path.name for path in repo.path.glob("ran-*"))


def test_the_repositorys_hooks_and_monitor_never_run(repo: Repo, tmp_path: Path) -> None:
    base = repo.commit({"a.py": "a = 1\n"})
    head = repo.commit({"a.py": "a = 2\n"})
    repo.git("checkout", "-q", "--detach", head)
    plant_programs(repo)
    # Control: plain git does run them, so the trap is real on this machine.
    plain = subprocess.run(
        ["git", "worktree", "add", "--detach", str(tmp_path / "control"), base],
        cwd=repo.path, env=repo.env, capture_output=True, check=False,
    )  # fmt: skip
    if plain.returncode != 0 or not markers(repo):
        pytest.skip(f"this git does not run the planted hooks ({sys.platform})")
    for marker in repo.path.glob("ran-*"):
        marker.unlink()
    git = Git(repo.path)
    git.resolve("HEAD")
    diff(git, base, head)
    snapshot(git, head, tmp_path / "snap")
    tree = add_worktree(git, base, tmp_path / "hardened")
    remove_worktree(git, tree)
    git.run("status", "--porcelain")
    assert markers(repo) == []
