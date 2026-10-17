"""An image's own environment, used as it is (J04): a benchmark task's image, a team's CI image.

The provisioner installs nothing. It finds the image's interpreter (its named conda
environment's, as SWE-bench-style task images have, else ``python3``), puts the snapshot first
on the import path, and checks before any test runs that the snapshot's packages import from
the snapshot: never a run of the copy the image holds installed elsewhere.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro.config import SettingsError, load_settings
from repro.gitops import Git
from repro.provision import ImageProvisioner, ProvisionError, inspect_project
from repro.provision.env import snapshot_packages
from repro.sandbox import DockerSandbox, Limits, docker_available
from repro.sandbox.detect import Detections
from repro.sandbox.image import sandbox_image
from repro.sandbox.process import Execution
from repro_events.models import EnvProvisionedPayload

docker = pytest.mark.skipif(
    not docker_available() and os.environ.get("REPRO_REQUIRE_DOCKER") != "1",
    reason="Docker with Linux containers is not available",
)


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(text.encode())
    return root


@pytest.mark.parametrize(
    ("files", "paths", "names"),
    [
        ({"pkg/__init__.py": "", "tests/__init__.py": "", "setup.py": ""}, (".",), ("pkg",)),
        ({"src/a/__init__.py": "", "src/b/__init__.py": "", "docs/conf.py": ""},
         ("src", "."), ("a", "b")),
        ({"module.py": "", "tests/test_x.py": ""}, (".",), ()),
    ],
)  # fmt: skip
def test_the_snapshots_code_is_found_in_either_layout(
    tmp_path: Path, files: dict[str, str], paths: tuple[str, ...], names: tuple[str, ...]
) -> None:
    assert snapshot_packages(tree(tmp_path, files)) == (paths, names)


class FakeBox:
    """A sandbox that answers the provisioner's two commands as an image would."""

    def __init__(self, found: str, probe: dict[str, Any]) -> None:
        self.found, self.probe = found, probe
        self.python_path: tuple[str, ...] = ()
        self.variables: dict[str, str] = {}
        self.argv: list[list[str]] = []

    @staticmethod
    def container_path(relative: str) -> str:
        return "/work" if relative == "." else f"/work/{relative}"

    def run(self, argv: list[str], **_: Any) -> Execution:
        self.argv.append(argv)
        out = self.found if argv[0] == "sh" else json.dumps(self.probe)
        return Execution(tuple(argv), "exited", 0 if out else 1, 0.1, out.encode(), b"",
                         False, False, Detections((), 0, truncated=False))  # fmt: skip


CONDA = "/opt/conda/envs/testbed/bin/python\n/opt/conda/bin:/usr/bin:/bin\n"


def probe(**changes: Any) -> dict[str, Any]:
    found = {"python": "/opt/conda/envs/testbed/bin/python", "version": "3.13.13",
             "tracer": True, "packages": 36,
             "found": {"pkg": {"from": "/work/pkg/__init__.py", "error": None}}}  # fmt: skip
    return found | changes


def project(tmp_path: Path) -> Any:
    return inspect_project(tree(tmp_path, {"pkg/__init__.py": ""}))


def test_the_images_conda_environment_is_used_as_activating_it_would(tmp_path: Path) -> None:
    box = FakeBox(CONDA, probe())
    env = ImageProvisioner("img").provision("head", project(tmp_path), box)  # type: ignore[arg-type]
    assert env.python == "/opt/conda/envs/testbed/bin/python"
    assert box.argv[1][0] == env.python
    assert box.python_path == ("/work",)
    assert box.variables == {"PATH": "/opt/conda/envs/testbed/bin:/opt/conda/bin:/usr/bin:/bin"}
    assert (env.python_version, env.installed_packages, env.cache_hit) == ("3.13.13", 36, True)
    EnvProvisionedPayload.model_validate(env.payload())


@pytest.mark.parametrize(
    ("found", "answer", "message"),
    [
        ("", probe(), "no Python interpreter"),
        (CONDA, probe(version="3.11.9", tracer=False), "3.11.9; Repro's tracer needs 3.12"),
        (CONDA, probe(found={"pkg": {"from": "/testbed/pkg/__init__.py", "error": None}}),
         "pkg would be imported from the image (/testbed/pkg/__init__.py), not from the snapshot"),
        (CONDA, probe(found={"pkg": {"from": None, "error": "ImportError: _speedups"}}),
         "the snapshot's pkg does not import in the image: ImportError: _speedups"),
    ],
)  # fmt: skip
def test_an_image_that_would_run_the_wrong_code_gives_no_environment(
    tmp_path: Path, found: str, answer: dict[str, Any], message: str
) -> None:
    with pytest.raises(ProvisionError, match=message.replace("(", r"\(").replace(")", r"\)")):
        ImageProvisioner("img").provision("head", project(tmp_path), FakeBox(found, answer))  # type: ignore[arg-type]


def test_the_image_is_pinned_by_digest(tmp_path: Path) -> None:
    pinned = "swerebench/sweb.eval.x86_64.o_1776_r-1@sha256:" + "0" * 64
    env = {"REPRO_DATA_DIR": str(tmp_path / "data"), "REPRO_SANDBOX_IMAGE": pinned}
    assert load_settings(env=env).sandbox_image == pinned
    with pytest.raises(SettingsError, match=r"REPRO_SANDBOX_IMAGE.*sha256"):
        load_settings(env=env | {"REPRO_SANDBOX_IMAGE": "swerebench/sweb.eval:latest"})


@docker
@pytest.mark.parametrize(
    ("files", "python_path"),
    [
        ({"pkg/__init__.py": "VALUE = 1\n"}, ("/work",)),
        ({"src/pkg/__init__.py": "VALUE = 1\n", "pyproject.toml": ""}, ("/work/src", "/work")),
    ],
)
def test_a_real_image_runs_the_snapshots_code(
    tmp_path: Path, files: dict[str, str], python_path: tuple[str, ...]
) -> None:
    repo = Repo(tmp_path / "repo")
    sha = repo.commit(files | {"tests/test_pkg.py": "import pkg\n"})
    image = sandbox_image()
    root = tree(tmp_path / "snapshot", files)
    with DockerSandbox(tmp_path / "work", Git(repo.path), sha, image=image,
                       limits=Limits(timeout_s=120)) as box:  # fmt: skip
        env = ImageProvisioner(image).provision("head", inspect_project(root), box)
        run = box.run([env.python, "-c", "import pkg; print(pkg.__file__, pkg.VALUE)"])
    assert box.python_path == python_path
    assert run.stdout.decode().split() == [f"{python_path[0]}/pkg/__init__.py", "1"]


@docker
def test_a_real_image_where_the_snapshot_does_not_import(tmp_path: Path) -> None:
    files = {"pkg/__init__.py": "from pkg._speedups import fast\n"}  # a module built elsewhere
    repo = Repo(tmp_path / "repo")
    sha = repo.commit(files)
    image = sandbox_image()
    snapshot = inspect_project(tree(tmp_path / "s", files))
    with (
        DockerSandbox(tmp_path / "work", Git(repo.path), sha, image=image,
                      limits=Limits(timeout_s=120)) as box,
        pytest.raises(ProvisionError, match="pkg does not import in the image"),
    ):  # fmt: skip
        ImageProvisioner(image).provision("head", snapshot, box)
