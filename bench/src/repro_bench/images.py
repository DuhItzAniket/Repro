"""Task images within a disk budget: pulled by digest when a stage needs one, the least recently
used removed past the budget (a fix to J01 and J04's image handling).

Each SWE-rebench task runs in its own environment image, pinned by digest in the manifest
(``repro_bench.swe``). The images are large: the two measured here are 4.53 GB
(``pypa__twine-1309``) and 4.85 GB (``delgan__loguru-1451``), as ``docker images`` reports them.
S2 has 351 candidate tasks (``bench/data/s2-candidates.jsonl``), far more than a workstation's
disk holds at once, and nothing used to remove an image once a stage had pulled it.

``ImageCache.ready`` makes a pinned image present, pulling it by digest if it is not, then
removes the least recently used images until those it pulled fit the budget:

- **Only its own.** The ledger records the images the cache pulled. An image that was on the
  machine before is used, never removed.
- **Never one in use.** Removal is ``docker image rm`` without ``--force``: Docker refuses to
  remove an image a container uses, and the image is skipped. Nor is the image just made ready.
- **Conservative sizes.** Each image counts its full size, though images share layers, so the
  disk used is at most what the ledger counts. At the peak, the budget plus one image is used.

The ledger is a JSON file every stage shares (ground truth, B0, Repro), so an image pulled for
one is reused by the next. Its writes are atomic. Two stages running at once can lose each
other's last-use times, which only changes which image goes first; an image whose record is lost
is never removed, the safe direction.

**Order matters.** A stage that runs every task before the next stage starts pulls each image
once per stage when the budget holds fewer images than there are tasks. Running every stage on
one task before the next pulls each image once.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from repro.paths import default_data_dir

GB: Final = 1000**3  # as docker images reports sizes
LEDGER_VERSION: Final = 1
PULL_TIMEOUT_S: Final = 3600
_PINNED: Final = re.compile(r"^[a-z0-9][a-z0-9._/:-]{0,250}@sha256:[0-9a-f]{64}$")


class ImageError(RuntimeError):
    """An image that could not be made ready."""


def default_ledger() -> Path:
    """The ledger every stage shares: ``~/.repro/bench-images.json``."""
    data = default_data_dir(os.environ, windows=sys.platform == "win32")
    return Path(data) / "bench-images.json"


@dataclass
class ImageCache:
    budget_bytes: int
    ledger: Path
    docker: str = "docker"
    clock: Callable[[], float] = field(default=time.time)

    def ready(self, image: str) -> str:
        """``image``, pinned by digest, present on this machine; the cache's other images then
        trimmed to the budget."""
        if not _PINNED.match(image):
            raise ImageError(f"{image!r} is not pinned by digest")
        images = self._load()
        if self._size(image) is None:
            done = self._docker(["pull", "--quiet", "--", image], timeout=PULL_TIMEOUT_S)
            if done.returncode != 0:
                said = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
                raise ImageError(f"pulling {image} failed: {said[0][:300] if said else ''}")
            images[image] = {"owned": True}
        images.setdefault(image, {"owned": False})["last_used"] = self.clock()
        self._trim(images, keep=image)
        self._save(images)
        return image

    def _trim(self, images: dict[str, dict[str, Any]], keep: str) -> None:
        sizes = {}
        for name, record in list(images.items()):
            if not record.get("owned"):
                continue
            size = self._size(name)
            if size is None:  # removed by someone else: nothing left to count
                del images[name]
            else:
                sizes[name] = size
        total = sum(sizes.values())
        oldest = sorted(
            (name for name in sizes if name != keep),
            key=lambda name: (images[name].get("last_used", 0.0), name),
        )
        for name in oldest:
            if total <= self.budget_bytes:
                break
            if self._docker(["image", "rm", "--", name], timeout=600).returncode == 0:
                total -= sizes[name]
                del images[name]
            # else: a container uses it (no --force); it stays, and so does its record

    def _size(self, image: str) -> int | None:
        done = self._docker(["image", "inspect", "--format", "{{.Size}}", "--", image], timeout=60)
        if done.returncode != 0:
            return None
        try:
            return int(done.stdout.decode().strip())
        except ValueError:
            return None

    def _docker(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - docker, with an image pinned by digest
            [self.docker, *args], capture_output=True, check=False, timeout=timeout
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.ledger.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise ImageError(f"the image ledger {self.ledger} cannot be read: {exc}") from None
        if data.get("version") != LEDGER_VERSION:
            raise ImageError(f"the image ledger {self.ledger} has another version")
        return {str(k): dict(v) for k, v in data.get("images", {}).items()}

    def _save(self, images: dict[str, dict[str, Any]]) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"version": LEDGER_VERSION, "images": images}, indent=1, sort_keys=True)
        handle, temporary = tempfile.mkstemp(dir=self.ledger.parent, prefix=".bench-images-")
        with os.fdopen(handle, "wb") as out:
            out.write(text.encode("utf-8") + b"\n")
        Path(temporary).replace(self.ledger)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options every stage that runs task images takes."""
    parser.add_argument(
        "--image-budget-gb",
        type=float,
        help="pull task images as needed and remove the least recently used ones this tool "
        "pulled once they pass this many GB (default: no budget, nothing removed)",
    )
    parser.add_argument(
        "--image-ledger",
        type=Path,
        help="the ledger of pulled images that stages share (default: ~/.repro/bench-images.json)",
    )


def from_arguments(args: argparse.Namespace) -> ImageCache | None:
    if args.image_budget_gb is None:
        return None
    if args.image_budget_gb <= 0:
        raise ImageError("--image-budget-gb must be positive")
    return ImageCache(int(args.image_budget_gb * GB), args.image_ledger or default_ledger())
