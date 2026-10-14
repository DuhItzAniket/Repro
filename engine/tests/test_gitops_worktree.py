"""Worktrees: added detached, and always removed, even past Windows file locks (C05)."""

import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import CleanupError, Git, add_worktree, remove_worktree
from repro.gitops import worktree as worktree_module

WINDOWS = sys.platform == "win32"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    repo = Repo(tmp_path / "target")
    repo.commit({"pkg/a.py": "a = 1\n", "pkg/b.py": "b = 1\n"})
    return repo


def listed(repo: Repo) -> str:
    return repo.git("worktree", "list", "--porcelain")


def test_a_worktree_is_detached_at_the_commit_and_then_gone(repo: Repo, tmp_path: Path) -> None:
    git = Git(repo.path)
    sha = git.resolve("main")
    tree = add_worktree(git, "main", tmp_path / "work tree")  # a space in its path
    assert (tree / "pkg" / "a.py").read_text(encoding="utf-8") == "a = 1\n"
    assert Git(tree).resolve("HEAD") == sha
    assert "detached" in listed(repo)
    remove_worktree(git, tree)
    assert not tree.exists()
    assert str(tree.name) not in listed(repo)


def test_read_only_files_do_not_stop_cleanup(repo: Repo, tmp_path: Path) -> None:
    git = Git(repo.path)
    tree = add_worktree(git, "main", tmp_path / "wt")
    (tree / "pkg" / "a.py").chmod(stat.S_IREAD)
    (tree / "untracked.txt").write_text("left by a tool", encoding="utf-8")
    (tree / "untracked.txt").chmod(stat.S_IREAD)
    remove_worktree(git, tree)
    assert not tree.exists()


@pytest.mark.skipif(not WINDOWS, reason="open files block deletion only on Windows")
def test_a_file_held_open_for_a_while_is_waited_for(repo: Repo, tmp_path: Path) -> None:
    """Roadmap C05: locked-file cleanup on Windows."""
    git = Git(repo.path)
    tree = add_worktree(git, "main", tmp_path / "wt")
    handle = (tree / "pkg" / "a.py").open("rb")  # like an editor or an indexer

    def let_go() -> None:
        time.sleep(0.6)
        handle.close()

    releaser = threading.Thread(target=let_go)
    releaser.start()
    start = time.monotonic()
    remove_worktree(git, tree)
    releaser.join()
    assert not tree.exists()
    assert time.monotonic() - start >= 0.5  # it really waited for the lock
    assert str(tree) not in listed(repo)


@pytest.mark.skipif(not WINDOWS, reason="open files block deletion only on Windows")
def test_a_file_never_released_is_reported_and_git_forgets_the_worktree(
    repo: Repo, tmp_path: Path
) -> None:
    git = Git(repo.path)
    tree = add_worktree(git, "main", tmp_path / "wt")
    handle = (tree / "pkg" / "b.py").open("rb")
    try:
        with pytest.raises(CleanupError) as failed:
            remove_worktree(git, tree, budget_s=0.3)
        assert any("b.py" in item for item in failed.value.left)
    finally:
        handle.close()
    assert "wt" not in listed(repo).replace(str(repo.path), "")  # pruned all the same
    remove_worktree(git, tree)  # once released, cleanup completes
    assert not tree.exists()


def test_cleanup_waits_with_growing_pauses_and_gives_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = tmp_path / "stuck"
    stuck.mkdir()
    (stuck / "held.txt").write_text("x", encoding="utf-8")
    pauses: list[float] = []
    # A lock that never lets go: every pass fails and leaves the file.
    monkeypatch.setattr(worktree_module, "_delete_once", lambda path: [str(path / "held.txt")])
    with pytest.raises(CleanupError) as failed:
        worktree_module._delete(stuck, 2.0, pauses.append)
    assert pauses[:4] == [0.1, 0.2, 0.4, 0.8]
    assert sum(pauses) >= 2.0
    assert failed.value.left == [str(stuck / "held.txt")]
