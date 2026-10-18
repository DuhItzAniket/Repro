"""Task images within a disk budget, pinned by the manifest (fix to J01 and J04).

Docker is a fake here, a dictionary of images and a registry: the tests check what is pulled and
what is removed, and above all what never is.
"""

import argparse
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from repro_bench import baselines, groundtruth, swe
from repro_bench.images import GB, ImageCache, ImageError, from_arguments
from repro_bench.truth import Environment

NAME = "swerebench/sweb.eval.x86_64.example_1776_pkg"
Done = subprocess.CompletedProcess[bytes]


def ref(n: int) -> str:
    return f"{NAME}-{n}@sha256:{n:064x}"


def answer(code: int, out: str = "", err: str = "") -> Done:
    return subprocess.CompletedProcess([], code, out.encode(), err.encode())


class FakeDocker:
    """``docker`` for the commands the bench uses: images by reference, a registry by tag."""

    def __init__(self) -> None:
        self.images: dict[str, int] = {}
        self.registry: dict[str, str] = {}  # reference -> digest
        self.in_use: set[str] = set()
        self.refuse_pulls = ""  # the daemon's error, when pulls fail
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: Any) -> Done:
        args = argv[1:]
        self.calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return self.inspect(args)
        if args[0] == "pull":
            return self.pull(args[-1])
        if args[:2] == ["image", "rm"]:
            return self.remove(args[-1])
        if args[:3] == ["buildx", "imagetools", "inspect"]:
            return self.lookup(args[-1])
        raise AssertionError(f"unexpected docker call: {args}")

    def inspect(self, args: list[str]) -> Done:
        image = args[-1]
        if image not in self.images:
            return answer(1, err=f"Error: No such image: {image}")
        return answer(0, str(self.images[image]) if "{{.Size}}" in args else "sha256:id")

    def pull(self, image: str) -> Done:
        if self.refuse_pulls:
            return answer(1, err=self.refuse_pulls)
        self.images[image] = int(4.5 * GB)
        return answer(0, image)

    def remove(self, image: str) -> Done:
        if image in self.in_use:
            return answer(1, err="Error: image is being used by a running container")
        del self.images[image]
        return answer(0)

    def lookup(self, image: str) -> Done:
        if image not in self.registry:
            return answer(1, err="ERROR: pull access denied, repository does not exist")
        return answer(0, json.dumps({"digest": self.registry[image], "size": 1360}))

    def pulled(self) -> list[str]:
        return [call[-1] for call in self.calls if call[0] == "pull"]

    def removed(self) -> list[str]:
        return [call[-1] for call in self.calls if call[:2] == ["image", "rm"]]


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def cache(tmp_path: Path, budget_gb: float) -> ImageCache:
    ticks = itertools.count(1)
    return ImageCache(int(budget_gb * GB), tmp_path / "ledger.json", clock=lambda: next(ticks))


def ledger(tmp_path: Path) -> dict[str, Any]:
    found: dict[str, dict[str, Any]] = json.loads(
        (tmp_path / "ledger.json").read_text(encoding="utf-8")
    )["images"]
    return found


def test_an_image_is_pulled_by_digest_when_its_task_comes(
    docker: FakeDocker, tmp_path: Path
) -> None:
    images = cache(tmp_path, 20)
    assert images.ready(ref(1)) == ref(1)
    assert images.ready(ref(1)) == ref(1)  # present now: not pulled again
    assert docker.pulled() == [ref(1)]
    assert ledger(tmp_path)[ref(1)]["owned"] is True


def test_past_the_budget_the_least_recently_used_image_goes(
    docker: FakeDocker, tmp_path: Path
) -> None:
    images = cache(tmp_path, 10)  # two 4.5 GB images fit, three do not
    images.ready(ref(1))
    images.ready(ref(2))
    images.ready(ref(3))
    assert docker.removed() == [ref(1)]
    images.ready(ref(2))  # used again: now the most recent
    images.ready(ref(4))
    assert docker.removed() == [ref(1), ref(3)]
    assert sorted(docker.images) == [ref(2), ref(4)]


def test_an_image_that_was_here_before_is_never_removed(docker: FakeDocker, tmp_path: Path) -> None:
    docker.images[ref(9)] = int(4.5 * GB)  # the user's, pulled before
    images = cache(tmp_path, 5)
    images.ready(ref(9))
    images.ready(ref(1))
    images.ready(ref(2))
    assert ref(9) in docker.images
    assert docker.removed() == [ref(1)]
    assert ledger(tmp_path)[ref(9)]["owned"] is False


def test_an_image_a_container_uses_is_skipped(docker: FakeDocker, tmp_path: Path) -> None:
    images = cache(tmp_path, 5)
    images.ready(ref(1))
    docker.in_use.add(ref(1))
    images.ready(ref(2))  # over the budget, and the only candidate is in use: both stay
    assert sorted(docker.images) == [ref(1), ref(2)]
    docker.in_use.clear()
    images.ready(ref(3))
    assert ref(1) not in docker.images  # its record was kept, so it goes once it is free


def test_the_image_made_ready_stays_even_alone_above_the_budget(
    docker: FakeDocker, tmp_path: Path
) -> None:
    cache(tmp_path, 1).ready(ref(1))
    assert list(docker.images) == [ref(1)]
    assert docker.removed() == []


def test_an_image_removed_by_hand_leaves_the_ledger(docker: FakeDocker, tmp_path: Path) -> None:
    images = cache(tmp_path, 20)
    images.ready(ref(1))
    del docker.images[ref(1)]
    images.ready(ref(2))
    assert list(ledger(tmp_path)) == [ref(2)]


def test_what_cannot_be_made_ready_says_why(docker: FakeDocker, tmp_path: Path) -> None:
    images = cache(tmp_path, 20)
    with pytest.raises(ImageError, match="not pinned by digest"):
        images.ready(f"{NAME}-1:latest")
    docker.refuse_pulls = "Error response from daemon: toomanyrequests"
    with pytest.raises(ImageError, match="toomanyrequests"):
        images.ready(ref(1))
    (tmp_path / "ledger.json").write_text('{"version": 99}', encoding="utf-8")
    with pytest.raises(ImageError, match="another version"):
        images.ready(ref(1))


def test_the_options(tmp_path: Path) -> None:
    def parsed(**given: Any) -> argparse.Namespace:
        return argparse.Namespace(**({"image_budget_gb": None, "image_ledger": None} | given))

    assert from_arguments(parsed()) is None
    with pytest.raises(ImageError, match="positive"):
        from_arguments(parsed(image_budget_gb=0))
    made = from_arguments(parsed(image_budget_gb=40, image_ledger=tmp_path / "l.json"))
    assert made is not None
    assert (made.budget_bytes, made.ledger) == (40 * GB, tmp_path / "l.json")
    default = from_arguments(parsed(image_budget_gb=1.5))
    assert default is not None
    assert default.ledger.parts[-2:] == (".repro", "bench-images.json")


# -- pinning without pulling ---------------------------------------------------------------------


def test_an_image_is_pinned_by_its_registry_without_a_pull(docker: FakeDocker) -> None:
    digest = "sha256:" + "a" * 64
    docker.registry[f"{NAME}-1:latest"] = digest
    assert swe.pinned(f"{NAME}-1:latest", registry=True) == f"{NAME}-1@{digest}"
    assert docker.pulled() == []
    with pytest.raises(swe.ContractError, match="registry has no"):
        swe.pinned(f"{NAME}-2:latest", registry=True)
    docker.registry[f"{NAME}-1@sha256:" + "b" * 64] = digest
    with pytest.raises(swe.ContractError, match="another digest"):
        swe.registry_digest(f"{NAME}-1@sha256:" + "b" * 64)


def test_an_image_on_this_machine_is_pinned_as_docker_recorded_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "sha256:" + "c" * 64

    def local(argv: list[str], **_: Any) -> Done:
        assert argv[1:3] == ["image", "inspect"]  # never the registry, never a pull
        said = "sha256:id" if "{{.Id}}" in argv else json.dumps([f"{NAME}-1@{digest}"])
        return answer(0, said)

    monkeypatch.setattr(subprocess, "run", local)
    assert swe.pinned(f"{NAME}-1:latest", registry=True) == f"{NAME}-1@{digest}"


# -- each stage in the image the manifest pinned -------------------------------------------------


def manifest(path: Path, images: dict[str, str]) -> Path:
    rows = [
        {
            "instance_id": instance_id,
            "dataset": "nebius/SWE-rebench",
            "split": "s",
            "revision": "r",
            "repo": "example/pkg",
            "base_commit": "a" * 40,
            "image": image,
            "patch_sha256": "0" * 64,
            "model": "agent-x",
            "label": None,
        }
        for instance_id, image in images.items()
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_the_manifest_names_one_image_per_task(tmp_path: Path) -> None:
    pinned = manifest(tmp_path / "m.jsonl", {"t-1": ref(1), "t-2": ref(2)})
    assert swe.manifest_images(pinned) == {"t-1": ref(1), "t-2": ref(2)}
    rows = pinned.read_text(encoding="utf-8")
    second = json.loads(rows.splitlines()[0]) | {"patch_sha256": "1" * 64, "image": ref(3)}
    pinned.write_text(rows + json.dumps(second) + "\n", encoding="utf-8")
    with pytest.raises(swe.ContractError, match="two images"):
        swe.manifest_images(pinned)


def test_ground_truth_runs_in_the_manifest_image(docker: FakeDocker, tmp_path: Path) -> None:
    pinned = {"t-1": ref(1)}
    images = cache(tmp_path, 20)
    assert groundtruth.task_image("t-1", f"{NAME}-1:latest", pinned, images) == ref(1)
    assert docker.pulled() == [ref(1)]
    with pytest.raises(swe.ContractError, match="pins no image for t-2"):
        groundtruth.task_image("t-2", f"{NAME}-2:latest", pinned, images)
    docker.registry[f"{NAME}-5:latest"] = "sha256:" + "5" * 64
    found = groundtruth.task_image("t-5", f"{NAME}-5:latest", None, images)
    assert found == f"{NAME}-5@sha256:" + "5" * 64  # by its registry, then pulled
    assert docker.pulled()[-1] == found


def test_b0_runs_in_the_manifest_image(tmp_path: Path) -> None:
    given = {
        "t-1": (Environment(f"{NAME}-1:latest", "a" * 40), "pytest -rA"),
        "t-2": (Environment(f"{NAME}-2:latest", "b" * 40), "pytest -rA"),
    }
    pinned = manifest(tmp_path / "m.jsonl", {"t-1": ref(1), "t-2": ref(2)})
    found = baselines.pin_environments(given, pinned, None)
    assert {k: v[0].image for k, v in found.items()} == {"t-1": ref(1), "t-2": ref(2)}
    assert found["t-1"][0].base_commit == "a" * 40
    partial = manifest(tmp_path / "p.jsonl", {"t-1": ref(1)})
    with pytest.raises(swe.ContractError, match="pins no image for t-2"):
        baselines.pin_environments(given, partial, None)
    assert baselines.pin_environments(given, None, None) == given  # as before: the tags
