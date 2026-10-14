"""Run artifacts: content-addressed files under ``<data dir>/runs/<run_id>/`` (ARCHITECTURE §11).

An artifact is written to a temporary file in its final directory, hashed (SHA-256) while it is
written, flushed to disk and renamed into place, so a reader never sees a partial file. Its row
in the ``artifacts`` table, written through the store's writer, is the record; the reference it
returns (``ArtifactRef``) is what evidence cites. An artifact never changes: writing the same
content to the same path again is a no-op, and other content at a taken path is an error.

Paths come from the engine, but they often derive from a target repository's own names, which
are untrusted. A path must be relative, use ``/``, and stay inside the run's directory: absolute
paths, drive letters, ``..``, empty or dot segments, backslashes, control characters, Windows
device names and segments ending in a dot or a space (which Windows silently strips) are refused.
"""

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final

from repro.clock import now_timestamp
from repro.store.writer import StoreWriter
from repro_events.models import ArtifactRef

MAX_PATH: Final = 1024  # the schema's ArtifactRef.path maxLength
MAX_SEGMENT: Final = 255
CHUNK: Final = 1 << 20
_RUN_ID = re.compile(r"^run_[0-9A-HJKMNP-TV-Z]{26}$")
_CONTROL = re.compile("[\x00-\x1f\x7f]")
_WINDOWS_DEVICES: Final = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


class ArtifactError(ValueError):
    """An artifact that cannot be stored or found as asked."""


def safe_relative_path(path: str) -> PurePosixPath:
    """``path`` as a normalised relative POSIX path, or ``ArtifactError`` if it is unsafe."""
    if not path or len(path) > MAX_PATH:
        raise ArtifactError(f"artifact path must be 1 to {MAX_PATH} characters")
    if "\\" in path or ":" in path:
        raise ArtifactError(f"artifact path must use '/' and no drive: {path!r}")
    if _CONTROL.search(path):
        raise ArtifactError(f"artifact path has a control character: {path!r}")
    if path.startswith("/"):
        raise ArtifactError(f"artifact path must be relative: {path!r}")
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ArtifactError(f"artifact path has an empty, '.' or '..' segment: {path!r}")
        if len(segment) > MAX_SEGMENT:
            raise ArtifactError(f"artifact path segment longer than {MAX_SEGMENT}: {path!r}")
        if segment.endswith((".", " ")):
            raise ArtifactError(f"artifact path segment ends in '.' or ' ': {path!r}")
        if segment.split(".")[0].lower() in _WINDOWS_DEVICES:
            raise ArtifactError(f"artifact path uses a Windows device name: {path!r}")
    return PurePosixPath(*segments)


class ArtifactStore:
    """Writes and opens a store's artifact files; their rows go through ``writer``."""

    def __init__(self, runs_dir: Path, writer: StoreWriter) -> None:
        self.runs_dir = runs_dir
        self.writer = writer

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.match(run_id):
            raise ArtifactError(f"not a run ID: {run_id!r}")
        return self.runs_dir / run_id

    def file_of(self, run_id: str, path: str) -> Path:
        """Where an artifact's file is, checked to be inside the run's directory."""
        relative = safe_relative_path(path)
        root = self.run_dir(run_id)
        target = root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(root.resolve()):
            raise ArtifactError(f"artifact path leaves the run directory: {path!r}")
        return target

    def put_bytes(self, run_id: str, path: str, data: bytes, media_type: str) -> ArtifactRef:
        return self.put_chunks(run_id, path, [data], media_type)

    def put_file(self, run_id: str, path: str, source: Path, media_type: str) -> ArtifactRef:
        with source.open("rb") as handle:
            return self.put_chunks(run_id, path, iter(lambda: handle.read(CHUNK), b""), media_type)

    def put_chunks(
        self, run_id: str, path: str, chunks: Iterable[bytes], media_type: str
    ) -> ArtifactRef:
        """Writes an artifact atomically and records it; returns its reference."""
        if not media_type or len(media_type) > 255:  # noqa: PLR2004 - the schema's maxLength
            raise ArtifactError("media type must be 1 to 255 characters")
        target = self.file_of(run_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - renamed into place below
            dir=target.parent, prefix=".tmp-", delete=False
        )
        temporary = Path(handle.name)
        try:
            with handle:
                for chunk in chunks:
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            sha256 = digest.hexdigest()
            if target.exists():
                if _sha256_of(target) != sha256:
                    raise ArtifactError(f"{path} already holds other content in {run_id}")
                temporary.unlink()
            else:
                temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        ref = ArtifactRef(path=path, sha256=sha256, media_type=media_type, size_bytes=size)
        self.writer.record_artifact(run_id, ref, now_timestamp()).result()
        return ref

    def open(self, run_id: str, ref: ArtifactRef) -> BinaryIO:
        """The artifact's file for reading, after checking that its content still matches."""
        target = self.file_of(run_id, ref.path)
        if not target.is_file():
            raise ArtifactError(f"{ref.path} is missing from {run_id}")
        if _sha256_of(target) != ref.sha256:
            raise ArtifactError(f"{ref.path} in {run_id} no longer matches its digest")
        return target.open("rb")


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
