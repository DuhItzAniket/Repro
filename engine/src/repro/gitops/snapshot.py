"""``.git``-less snapshots: a commit's files, byte for byte, in a directory of their own.

Target code runs only from snapshots (CLAUDE.md rule 5; THREAT_MODEL T3). A snapshot is built
from the commit's tree object: ``git ls-tree`` lists it and one ``git cat-file --batch`` process
streams the blobs, so the files are the committed bytes exactly. No ``.gitattributes``,
filter, ``export-ignore`` or line-ending conversion applies (``git archive`` would apply the
archived tree's attributes: https://git-scm.com/docs/git-archive).

Tree entries come from an untrusted repository. An entry that cannot be written safely and
faithfully on this machine is skipped and listed, never written somewhere else:
- a path with an empty, ``.`` or ``..`` segment, a ``.git`` segment in any case (or its Windows
  short name ``GIT~1``), a drive letter, ``:``, ``\\``, a control character, a Windows device
  name, a segment ending in ``.`` or a space (Windows strips them, which would alias another
  file), or a segment over 255 characters;
- a second path that differs from another only by case, on a case-insensitive filesystem;
- a symbolic link on Windows (creating one needs a privilege), or one whose target leaves the
  snapshot;
- a submodule (its commit is not in this repository).

Size and file-count limits guard the disk (THREAT_MODEL T4); they are checked before anything is
written. On Windows, files are written through extended-length paths, so deep trees work even
when long paths are disabled.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Final

from repro.gitops.git import Git, GitError

DEFAULT_MAX_BYTES: Final = 4 * 1024**3
DEFAULT_MAX_FILES: Final = 500_000
_MAX_SEGMENT: Final = 255
_MAX_PATH: Final = 4096
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SHORT_GIT = re.compile(r"^git~\d+$", re.IGNORECASE)
_DEVICES: Final = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{n}" for n in "123456789"}
    | {f"lpt{n}" for n in "123456789"}
)
_CHUNK: Final = 1 << 20


class SnapshotError(RuntimeError):
    """The commit cannot be snapshotted (limits, or git failed)."""


@dataclass(frozen=True, slots=True)
class Skipped:
    path: str
    mode: str
    reason: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    root: Path
    commit: str
    files: int
    bytes: int
    skipped: tuple[Skipped, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    mode: str
    kind: str
    sha: str
    size: int
    path: str


def _segment_problem(segment: str) -> str | None:
    if segment in ("", ".", ".."):
        return "an empty, '.' or '..' segment"
    if len(segment) > _MAX_SEGMENT:
        return f"a segment longer than {_MAX_SEGMENT} characters"
    if segment.rstrip(". ").lower() == ".git" or _SHORT_GIT.match(segment):
        return "a '.git' segment"
    if segment.endswith((".", " ")):
        return "a segment ending in '.' or a space (Windows strips them)"
    if segment.split(".", maxsplit=1)[0].rstrip(" ").lower() in _DEVICES:
        return "a Windows device name"
    return None


def path_problem(path: str) -> str | None:
    """Why a tree path cannot be written safely, or ``None``."""
    if not path or len(path) > _MAX_PATH:
        return "an empty or overlong path"
    if _CONTROL.search(path):
        return "a control character in the path"
    if "\\" in path or ":" in path:
        return "a backslash or colon in the path (a separator or drive on Windows)"
    problems = (_segment_problem(segment) for segment in path.split("/"))
    return next((problem for problem in problems if problem is not None), None)


def extended(path: Path) -> str:
    """``path`` as the OS should be given it: an extended-length path on Windows."""
    text = str(path.absolute())
    if sys.platform != "win32" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def _list_tree(git: Git, commit: str) -> list[_Entry]:
    output = git.run("ls-tree", "-r", "-z", "-l", "--full-tree", commit)
    entries = []
    for record in output.split(b"\0"):
        if not record:
            continue
        meta, _, raw_path = record.partition(b"\t")
        mode, kind, sha, size = meta.decode("ascii").split()
        path = raw_path.decode("utf-8", "surrogateescape")
        entries.append(_Entry(mode, kind, sha, 0 if size == "-" else int(size), path))
    return entries


def _case_insensitive(directory: Path) -> bool:
    probe = directory / ".repro-case-Probe"
    probe.touch()
    try:
        return (directory / ".repro-case-probe").exists()
    finally:
        probe.unlink()


def _blobs(git: Git, shas: list[str]) -> Generator[tuple[str, IO[bytes], int]]:
    """Streams each blob from one ``git cat-file --batch``: (sha, stream, size)."""
    process = subprocess.Popen(  # noqa: S603 - our own argv
        git.command("cat-file", "--batch"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=git.environment(),
    )
    stdin, stdout = process.stdin, process.stdout
    if stdin is None or stdout is None:  # pragma: no cover - both are pipes
        raise SnapshotError("git cat-file has no pipes")

    def feed() -> None:
        try:
            for sha in shas:
                stdin.write(sha.encode("ascii") + b"\n")
        finally:
            stdin.close()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    try:
        for sha in shas:
            header = stdout.readline().decode("ascii", "replace").split()
            if len(header) != 3 or header[1] != "blob":  # noqa: PLR2004
                raise SnapshotError(f"git cat-file could not read blob {sha}: {header}")
            size = int(header[2])
            yield sha, stdout, size
            if stdout.read(1) != b"\n":
                raise SnapshotError(f"git cat-file output out of step after {sha}")
    finally:
        process.kill()
        process.wait()
        feeder.join(5)


def _copy(stream: IO[bytes], size: int, target: str, *, executable: bool) -> None:
    with open(target, "xb") as out:  # noqa: PTH123 - an extended-length path string
        remaining = size
        while remaining:
            chunk = stream.read(min(_CHUNK, remaining))
            if not chunk:
                raise SnapshotError("git cat-file ended early")
            out.write(chunk)
            remaining -= len(chunk)
    if executable and sys.platform != "win32":
        os.chmod(target, 0o755)  # noqa: PTH101, S103 - the committed mode, 100755


def _plan(entries: list[_Entry], *, insensitive: bool) -> tuple[list[_Entry], list[Skipped]]:
    """Which entries to write; the rest, with why they are skipped."""
    to_write: list[_Entry] = []
    skipped: list[Skipped] = []
    files: dict[str, str] = {}  # (lower-cased if insensitive) path -> path
    dirs: set[str] = set()
    for entry in entries:
        key = entry.path.lower() if insensitive else entry.path
        parents = ["/".join(key.split("/")[:n]) for n in range(1, key.count("/") + 1)]
        problem = path_problem(entry.path)
        if problem is None and (key in files or key in dirs or any(p in files for p in parents)):
            clash = files.get(key) or next((files[p] for p in parents if p in files), key)
            problem = f"collides with {clash!r} on this case-insensitive filesystem"
        if problem is None and entry.kind == "commit":
            problem = "a submodule (its commit is not in this repository)"
        if problem is None and entry.mode == "120000" and sys.platform == "win32":
            problem = "a symbolic link (not created on Windows)"
        if problem is not None:
            skipped.append(Skipped(entry.path, entry.mode, problem))
            continue
        files[key] = entry.path
        dirs.update(parents)
        to_write.append(entry)
    return to_write, skipped


def snapshot(
    git: Git,
    commit: str,
    dest: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> Snapshot:
    """Writes commit ``commit`` into ``dest`` (which must not exist or be empty)."""
    sha = git.resolve(commit)
    if dest.exists() and any(dest.iterdir()):
        raise SnapshotError(f"{dest} is not empty")
    try:
        entries = _list_tree(git, sha)
    except GitError as exc:
        raise SnapshotError(f"cannot list {sha}: {exc}") from None
    blobs = [e for e in entries if e.kind == "blob"]
    total = sum(e.size for e in blobs)
    if total > max_bytes or len(blobs) > max_files:
        raise SnapshotError(
            f"{sha[:12]} has {len(blobs)} files and {total} bytes, over the limits "
            f"({max_files} files, {max_bytes} bytes)"
        )
    os.makedirs(extended(dest), exist_ok=True)  # noqa: PTH103
    to_write, skipped = _plan(entries, insensitive=_case_insensitive(dest))
    root = dest.absolute()
    files = size = 0
    links: list[tuple[_Entry, str]] = []
    stream_blobs = _blobs(git, [entry.sha for entry in to_write])
    try:
        for entry, (blob_sha, stream, length) in zip(to_write, stream_blobs, strict=True):
            if entry.sha != blob_sha:
                raise SnapshotError("git cat-file answered out of order")
            target = root.joinpath(*PurePosixPath(entry.path).parts)
            os.makedirs(extended(target.parent), exist_ok=True)  # noqa: PTH103
            if entry.mode == "120000":
                links.append((entry, stream.read(length).decode("utf-8", "surrogateescape")))
                continue
            _copy(stream, length, extended(target), executable=entry.mode == "100755")
            files += 1
            size += length
    finally:
        stream_blobs.close()
    for entry, link_target in links:  # after every file, so a link's target exists
        target = root.joinpath(*PurePosixPath(entry.path).parts)
        inside = (target.parent / link_target).resolve().is_relative_to(root.resolve())
        if Path(link_target).is_absolute() or not inside:
            skipped.append(
                Skipped(entry.path, entry.mode, "a symbolic link that leaves the snapshot")
            )
            continue
        target.symlink_to(link_target)
        files += 1
    return Snapshot(root, sha, files, size, tuple(skipped))


def remove_snapshot(root: Path) -> None:
    """Deletes a snapshot, clearing read-only bits as needed."""

    def writable(function: object, path: str, _: BaseException) -> None:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)  # noqa: PTH101
        if callable(function):
            function(path)

    shutil.rmtree(extended(root), onexc=writable)
