"""Diffs: every change kind with exact paths, and changed lines on each side (C05)."""

from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import FileChange, Git, Hunk, diff
from repro.gitops import changes as changes_module

BASE = "\n".join(f"line {n}" for n in range(1, 11)) + "\n"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo with spaces")


def by_path(changes: list[FileChange]) -> dict[str, FileChange]:
    return {change.path: change for change in changes}


def test_modified_lines_on_both_sides(repo: Repo) -> None:
    base = repo.commit({"a.py": BASE})
    lines = BASE.splitlines()
    lines[2] = "line three"  # changed
    lines.insert(6, "inserted")  # added after line 6
    del lines[8]  # removed: base line 9 (now index 8 after the insertion)
    head = repo.commit({"a.py": "\n".join(lines) + "\n"})
    (change,) = diff(Git(repo.path), base, head)
    assert (change.status, change.old_path, change.new_path) == ("M", "a.py", "a.py")
    assert change.hunks == (Hunk(3, 1, 3, 1), Hunk(6, 0, 7, 1), Hunk(8, 1, 8, 0))
    assert change.changed_lines("old") == [range(3, 4), range(8, 9)]
    assert change.changed_lines("new") == [range(3, 4), range(7, 8)]
    assert not change.binary


def test_added_deleted_and_renamed(repo: Repo) -> None:
    long_text = "".join(f"def function_{n}():\n    return {n}\n\n" for n in range(40))
    base = repo.commit({"old.py": long_text, "gone.py": "x = 1\n", "kept.py": "y = 2\n"})
    head = repo.commit({
        "old.py": None,
        "new name.py": long_text.replace("return 7\n", "return 70\n"),
        "gone.py": None,
        "added.py": "z = 3\n",
    })  # fmt: skip
    changes = by_path(diff(Git(repo.path), base, head))
    assert set(changes) == {"new name.py", "gone.py", "added.py"}
    renamed = changes["new name.py"]
    assert (renamed.status, renamed.old_path) == ("R", "old.py")
    assert renamed.similarity is not None
    assert 50 <= renamed.similarity < 100
    assert renamed.changed_lines("new") == [range(23, 24)]
    deleted, added = changes["gone.py"], changes["added.py"]
    assert (deleted.status, deleted.new_path, deleted.new_blob) == ("D", None, None)
    assert deleted.changed_lines("old") == [range(1, 2)]
    assert (added.status, added.old_path, added.old_blob) == ("A", None, None)
    assert added.changed_lines("new") == [range(1, 2)]


def test_a_pure_rename_has_no_hunks(repo: Repo) -> None:
    base = repo.commit({"a.py": BASE})
    head = repo.commit({"a.py": None, "b.py": BASE})
    (change,) = diff(Git(repo.path), base, head)
    assert (change.status, change.similarity, change.hunks) == ("R", 100, ())


def test_mode_and_type_changes(repo: Repo) -> None:
    base = repo.commit({"run.sh": "echo hi\n", "link": "target"})
    head = repo.commit({"run.sh": ("echo hi\n", "100755"), "link": ("target", "120000")})
    changes = by_path(diff(Git(repo.path), base, head))
    assert (changes["run.sh"].old_mode, changes["run.sh"].new_mode) == ("100644", "100755")
    assert changes["run.sh"].hunks == ()
    assert (changes["link"].status, changes["link"].hunks) == ("T", ())


def test_binary_files_are_marked(repo: Repo) -> None:
    base = repo.commit({"image.png": bytes(range(256))})
    head = repo.commit({"image.png": bytes(reversed(range(256)))})
    (change,) = diff(Git(repo.path), base, head)
    assert change.binary
    assert change.hunks == ()


def test_crlf_files_report_the_same_lines(repo: Repo) -> None:
    crlf = BASE.replace("\n", "\r\n")
    base = repo.commit({"win.txt": crlf.encode()})
    head = repo.commit({"win.txt": crlf.replace("line 5\r\n", "line five\r\n").encode()})
    (change,) = diff(Git(repo.path), base, head)
    assert change.hunks == (Hunk(5, 1, 5, 1),)


@pytest.mark.parametrize(
    "name",
    [
        "with space.py",
        'quote".py',
        "tab\there.py",
        "new\nline.py",
        "naïve/日本語.py",
        "back\\slash.py",
        "glob[1]*.py",
        "-dash.py",
    ],
)
def test_exact_paths_whatever_they_contain(repo: Repo, name: str) -> None:
    base = repo.commit({name: "a = 1\n"})
    head = repo.commit({name: "a = 2\n"})
    (change,) = diff(Git(repo.path), base, head)
    assert (change.old_path, change.new_path) == (name, name)
    assert change.hunks == (Hunk(1, 1, 1, 1),)


def test_each_file_is_diffed_alone_when_the_listings_disagree(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = repo.commit({"glob[1]*.py": "a = 1\n", "b.py": "b = 1\n"})
    head = repo.commit({"glob[1]*.py": "a = 2\n", "b.py": "b = 2\nb2 = 3\n"})
    real = changes_module.parse_patch_sections
    calls = {"n": 0}

    def lose_a_section(output: bytes) -> list[tuple[bool, tuple[Hunk, ...]]]:
        calls["n"] += 1
        sections = real(output)
        return sections[:-1] if calls["n"] == 1 else sections  # only the combined listing

    monkeypatch.setattr(changes_module, "parse_patch_sections", lose_a_section)
    changes = by_path(diff(Git(repo.path), base, head))
    assert changes["glob[1]*.py"].hunks == (Hunk(1, 1, 1, 1),)  # a literal pathspec
    assert changes["b.py"].hunks == (Hunk(1, 1, 1, 2),)


def test_no_change_is_an_empty_list(repo: Repo) -> None:
    sha = repo.commit({"a.py": BASE})
    assert diff(Git(repo.path), sha, sha) == []
