"""Reading the change's files from git objects, by checked paths only (G03)."""

import sys
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.agents.sources import MAX_FILE_BYTES, RepoSources, SourceError, checked_path
from repro.gitops import Git


@pytest.fixture
def sources(tmp_path: Path) -> RepoSources:
    repo = Repo(tmp_path / "repo")
    base = repo.commit(
        {
            "pkg/a.py": "x = 1\n",
            "pkg/crlf.py": b"a = 1\r\nb = 2\r\n",
            "pkg/link.py": ("../../outside.txt", "120000"),
            "vendor/sub": ("0" * 39 + "1", "160000"),
            "big.txt": "y" * (MAX_FILE_BYTES + 1),
            "odd [name].py": "z = 3\n",
        }
    )
    head = repo.commit({"pkg/a.py": "x = 2\n", "pkg/new.py": "n = 0\n"})
    return RepoSources(Git(repo.path), base, head)


@pytest.mark.parametrize(
    "path",
    ["pkg/a.py", "a", "tests/test_x.py", "odd [name].py", "unicode/é.py", "a b/c-d_e.f"],
)
def test_a_plain_repository_path_is_accepted(path: str) -> None:
    assert checked_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../secret",
        "pkg/../../x",
        "./pkg/a.py",
        "pkg//a.py",
        "pkg/a.py/",
        "C:/Windows/win.ini",
        "C:x",
        "pkg\\a.py",
        "\\\\server\\share",
        ":(glob)**",
        "pkg/a\x00.py",
        "pkg/a\n.py",
        'pkg/"a".py',
        "pkg/<a>.py",
        "x" * 401,
        None,
        7,
        ["pkg/a.py"],
    ],
)
def test_anything_else_is_refused_before_git_sees_it(path: object) -> None:
    with pytest.raises(SourceError):
        checked_path(path)


def test_a_file_is_read_from_its_commit(sources: RepoSources) -> None:
    assert sources.read("base", "pkg/a.py") == "x = 1\n"
    assert sources.read("head", "pkg/a.py") == "x = 2\n"
    assert sources.read("base", "pkg/new.py") is None
    assert sources.read("head", "pkg/crlf.py") == "a = 1\nb = 2\n"
    assert sources.read("base", "odd [name].py") == "z = 3\n"  # a name, not a pattern


@pytest.mark.parametrize("path", ["pkg/link.py", "vendor/sub", "pkg"])
def test_only_regular_files_are_read(sources: RepoSources, path: str) -> None:
    with pytest.raises(SourceError, match="not a regular file"):
        sources.read("base", path)


def test_a_large_file_is_refused(sources: RepoSources) -> None:
    with pytest.raises(SourceError, match="bytes; at most"):
        sources.read("base", "big.txt")


@pytest.mark.parametrize("side", ["Base", "both", "", None, "../head"])
def test_a_side_is_base_or_head(sources: RepoSources, side: object) -> None:
    with pytest.raises(SourceError, match="side is"):
        sources.read(side, "pkg/a.py")


def test_a_diff_is_git_s_own_and_runs_nothing(tmp_path: Path) -> None:
    """A textconv or external diff driver configured for the file never runs."""
    repo = Repo(tmp_path / "repo")
    marker = tmp_path / "ran.txt"
    driver = f"\"{Path(sys.executable).as_posix()}\" -c \"open(r'{marker}', 'w')\""
    base = repo.commit({"a.py": "x = 1\n"})
    head = repo.commit({"a.py": "x = 2\n"})
    # The repository's own attributes file, read for every diff, with or without a worktree.
    (repo.path / ".git" / "info").mkdir(exist_ok=True)
    (repo.path / ".git" / "info" / "attributes").write_text("*.py diff=evil\n", encoding="utf-8")
    repo.git("config", "diff.evil.textconv", driver)
    repo.git("config", "diff.evil.command", driver)
    repo.git("diff", base, head, "--", "a.py")  # control: a plain diff does run the driver
    assert marker.exists()
    marker.unlink()
    diff = RepoSources(Git(repo.path), base, head).diff("a.py")
    assert "-x = 1\n+x = 2" in diff
    assert not marker.exists()
    assert RepoSources(Git(repo.path), head, head).diff("a.py") == ""
