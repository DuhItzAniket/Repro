"""Snapshots: the commit byte for byte, nothing outside the directory, on every OS (C05)."""

import hashlib
import io
import os
import stat
import sys
import tarfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import Git, SnapshotError, path_problem, regular_files, snapshot, tar_tree
from repro.gitops.snapshot import ZIP_EPOCH, extended, remove_snapshot

POSIX = sys.platform != "win32"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "target repo")  # a space in the path, on purpose


def files_under(root: Path) -> dict[str, bytes]:
    found = {}
    for dirpath, _, names in os.walk(extended(root)):
        for name in names:
            full = Path(dirpath) / name
            rel = full.relative_to(Path(extended(root))).as_posix()
            found[rel] = full.read_bytes() if not full.is_symlink() else b"<link>"
    return found


def test_a_snapshot_is_the_commit_byte_for_byte(repo: Repo, tmp_path: Path) -> None:
    contents: dict[str, bytes | str] = {
        "pkg/dates.py": "def parse(text):\n    return text\n",
        "pkg/windows.txt": b"line one\r\nline two\r\n",  # CRLF stays CRLF
        "data/blob.bin": bytes(range(256)) * 10,
        "docs/naïve café.md": "unicode and spaces\n",
        "empty.txt": b"",
    }
    sha = repo.commit(contents)
    result = snapshot(Git(repo.path), sha, tmp_path / "snap")
    found = files_under(result.root)
    expected = {k: v.encode() if isinstance(v, str) else v for k, v in contents.items()}
    assert found == expected
    assert (result.commit, result.files, result.skipped) == (sha, 5, ())
    assert result.bytes == sum(len(v) for v in expected.values())
    assert not (result.root / ".git").exists()


def test_gitattributes_are_not_applied(repo: Repo, tmp_path: Path) -> None:
    """git archive would drop export-ignore paths and rewrite export-subst ones."""
    sha = repo.commit({
        ".gitattributes": "tests export-ignore\nversion.txt export-subst\n* text eol=crlf\n",
        "tests/test_core.py": "def test_x():\n    assert True\n",
        "version.txt": "$Format:%H$\n",
    })  # fmt: skip
    found = files_under(snapshot(Git(repo.path), sha, tmp_path / "snap").root)
    assert found["tests/test_core.py"] == b"def test_x():\n    assert True\n"  # not dropped
    assert found["version.txt"] == b"$Format:%H$\n"  # not expanded, still LF


@pytest.mark.skipif(not POSIX, reason="executable bits are POSIX")
def test_executable_bits_follow_the_commit(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"run.sh": ("#!/bin/sh\necho hi\n", "100755"), "plain.txt": "x"})
    root = snapshot(Git(repo.path), sha, tmp_path / "snap").root
    assert (root / "run.sh").stat().st_mode & stat.S_IXUSR
    assert not (root / "plain.txt").stat().st_mode & stat.S_IXUSR


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../escape.txt", "'..'"),
        ("a/../../escape.txt", "'..'"),
        (".GIT/config", ".git"),
        ("sub/.git/hooks/post-checkout", ".git"),
        ("GIT~1/HEAD", ".git"),
        ("con.txt", "device"),
        ("dir/NUL", "device"),
        ("C:/windows.txt", "colon"),
        ("a:stream", "colon"),
        ("back\\slash.txt", "backslash"),
        ("trailing.", "ending in"),
        ("space /x", "ending in"),
        ("new\nline.txt", "control"),
        ("a" * 256 + ".txt", "longer than 255"),
    ],
)
def test_unsafe_tree_entries_are_skipped_never_written_elsewhere(
    repo: Repo, tmp_path: Path, path: str, reason: str
) -> None:
    assert path_problem(path) is not None
    sha = repo.commit({"ok.txt": "fine", path: "hostile"})
    dest = tmp_path / "deep" / "snap"
    result = snapshot(Git(repo.path), sha, dest)
    assert [s.path for s in result.skipped] == [path]
    assert reason in result.skipped[0].reason
    assert files_under(result.root) == {"ok.txt": b"fine"}
    assert sorted(p.name for p in (tmp_path / "deep").iterdir()) == ["snap"]  # nothing beside it


def test_a_submodule_is_skipped(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"lib": ("0123456789abcdef0123456789abcdef01234567", "160000"), "a.txt": "a"})
    result = snapshot(Git(repo.path), sha, tmp_path / "snap")
    assert [(s.path, s.mode) for s in result.skipped] == [("lib", "160000")]
    assert "submodule" in result.skipped[0].reason


def test_symbolic_links(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({
        "real.txt": "target",
        "inside": ("real.txt", "120000"),
        "outside": ("../../etc/passwd", "120000"),
        "absolute": ("/etc/passwd", "120000"),
    })  # fmt: skip
    result = snapshot(Git(repo.path), sha, tmp_path / "snap")
    skipped = {s.path: s.reason for s in result.skipped}
    if POSIX:
        assert set(skipped) == {"outside", "absolute"}
        assert (result.root / "inside").is_symlink()
        assert (result.root / "inside").read_text(encoding="utf-8") == "target"
    else:
        assert set(skipped) == {"inside", "outside", "absolute"}
        assert all("symbolic link" in reason for reason in skipped.values())


def test_case_collisions_only_where_the_filesystem_folds_case(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"README": "upper", "readme": "lower", "Docs/a.txt": "a", "docs": "a file"})
    result = snapshot(Git(repo.path), sha, tmp_path / "snap")
    probe = tmp_path / "Case-Probe"
    probe.touch()
    folds = (tmp_path / "case-probe").exists()
    if folds:
        assert {s.path for s in result.skipped} == {"readme", "docs"}
        assert all("collides" in s.reason for s in result.skipped)
    else:
        assert result.skipped == ()
        assert result.files == 4


def test_long_paths_are_written(repo: Repo, tmp_path: Path) -> None:
    deep = "/".join(f"directory_{i:02d}_" + "x" * 20 for i in range(12)) + "/leaf.py"
    assert len(deep) > 300
    sha = repo.commit({deep: "print('deep')\n"})
    result = snapshot(Git(repo.path), sha, tmp_path / "snap")
    assert result.skipped == ()
    assert len(str(result.root / deep)) > 260
    assert files_under(result.root) == {deep: b"print('deep')\n"}


def test_limits_are_checked_before_anything_is_written(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"a.bin": b"x" * 1000, "b.bin": b"y" * 1000})
    with pytest.raises(SnapshotError, match="over the limits"):
        snapshot(Git(repo.path), sha, tmp_path / "snap", max_bytes=1500)
    with pytest.raises(SnapshotError, match="over the limits"):
        snapshot(Git(repo.path), sha, tmp_path / "snap", max_files=1)
    assert not (tmp_path / "snap").exists()


def test_a_non_empty_destination_is_refused(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"a.txt": "a"})
    dest = tmp_path / "snap"
    dest.mkdir()
    (dest / "leftover").write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotError, match="not empty"):
        snapshot(Git(repo.path), sha, dest)


def test_a_ref_is_resolved_first(repo: Repo, tmp_path: Path) -> None:
    repo.commit({"a.txt": "a"})
    assert snapshot(Git(repo.path), "main", tmp_path / "snap").files == 1


def test_remove_snapshot_handles_read_only_files(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"pkg/locked.txt": "x"})
    root = snapshot(Git(repo.path), sha, tmp_path / "snap").root
    (root / "pkg" / "locked.txt").chmod(stat.S_IREAD)
    remove_snapshot(root)
    assert not root.exists()


def test_regular_files_lists_blobs_by_their_exact_path(repo: Repo) -> None:
    sha = repo.commit(
        {
            "pkg/naïve café.py": "x = 1",  # git would quote this without -z
            "run.py": ("x = 2", "100755"),
            "link.py": ("run.py", "120000"),
            "vendor": ("0123456789abcdef0123456789abcdef01234567", "160000"),
        }
    )
    files = regular_files(Git(repo.path), sha)
    assert set(files) == {"pkg/naïve café.py", "run.py"}
    assert files["run.py"] == repo.git("rev-parse", f"{sha}:run.py")


def test_the_tree_digest_names_exactly_what_was_written(repo: Repo, tmp_path: Path) -> None:
    sha = repo.commit({"b.txt": "b", "a/x.py": ("x = 1", "100755")})
    first = snapshot(Git(repo.path), sha, tmp_path / "s1")
    blob = {path: repo.git("rev-parse", f"{sha}:{path}") for path in ("a/x.py", "b.txt")}
    text = f"100755 {blob['a/x.py']}\ta/x.py\n100644 {blob['b.txt']}\tb.txt\n"  # path order
    assert first.tree_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert snapshot(Git(repo.path), sha, tmp_path / "s2").tree_sha256 == first.tree_sha256
    with_skipped = repo.commit({"con": "a Windows device name: skipped on every OS"})
    assert snapshot(Git(repo.path), with_skipped, tmp_path / "s3").tree_sha256 == first.tree_sha256


def test_tar_tree_is_the_commit_exactly_and_the_same_every_time(repo: Repo) -> None:
    sha = repo.commit(
        {
            "a/run.py": ("print('x')", "100755"),
            "b.txt": "b",
            "link": ("b.txt", "120000"),  # kept on any host: the tar is for a Linux container
            "con": "a Windows device name",  # unsafe: skipped and listed
            "vendor": ("0123456789abcdef0123456789abcdef01234567", "160000"),  # a submodule
        }
    )
    first, second = io.BytesIO(), io.BytesIO()
    tarred = tar_tree(Git(repo.path), sha, first)
    tar_tree(Git(repo.path), sha, second)
    assert first.getvalue() == second.getvalue()  # deterministic: the commit's time, no owners
    with tarfile.open(fileobj=io.BytesIO(first.getvalue())) as tar:
        members = {member.name: member for member in tar.getmembers()}
        assert set(members) == {"a/run.py", "b.txt", "link"}
        assert (members["a/run.py"].mode, members["b.txt"].mode) == (0o755, 0o644)
        assert members["link"].issym()
        assert members["link"].linkname == "b.txt"
        committed = datetime(2026, 1, 1, tzinfo=UTC).timestamp()  # gitrepo's committer date
        assert all(member.mtime == committed for member in members.values())
        handle = tar.extractfile(members["a/run.py"])
        assert handle is not None
        assert handle.read() == b"print('x')"
    assert (tarred.commit, tarred.files, tarred.bytes) == (sha, 3, len("print('x')") + 1)
    assert {item.path for item in tarred.skipped} == {"con", "vendor"}


def test_a_commit_dated_before_zip_can_hold_it_is_tarred_from_1980(repo: Repo) -> None:
    """H02: the project's own install builds a wheel, and a zip holds no time before 1980."""
    repo.env["GIT_COMMITTER_DATE"] = "@86400 +0000"  # 1970-01-02
    sha = repo.commit({"setup.py": "from setuptools import setup\nsetup()\n"})
    out = io.BytesIO()
    tar_tree(Git(repo.path), sha, out)
    with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as tar:
        (member,) = tar.getmembers()
    assert member.mtime == ZIP_EPOCH
    assert zipfile.ZipInfo("setup.py", time.gmtime(member.mtime)[:6]).date_time[0] == 1980
