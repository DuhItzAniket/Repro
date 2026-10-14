"""Provisioning environments (D03), against the real package index.

Roadmap D03: "five fixture project types provision on both OSes. A broken install gives
UNVERIFIABLE with a reason, never a crash." Each environment is checked the only way that
matters: the fixture project's own tests pass in it, in the sandbox.

Resolution is cut off at a fixed date (``--exclude-newer``), so the same packages are chosen on
every run. The Docker cases need Docker with Linux containers (required on CI's Ubuntu job).
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import Git
from repro.provision import (
    DockerProvisioner,
    HostProvisioner,
    ProvisionError,
    environment_missing,
    inspect_project,
    spec_for,
)
from repro.sandbox import DockerSandbox, Limits, ProcessSandbox, docker_available
from repro.sandbox.image import sandbox_image
from repro_events.models import EnvProvisionedPayload, MissingRecordedPayload

PROJECTS = Path(__file__).parent / "data" / "projects"
KINDS = ("uv", "poetry", "pdm", "requirements", "setuptools")
CUT_OFF = "2025-01-01T00:00:00Z"
PYTEST = ["-m", "pytest", "-q", "-p", "no:cacheprovider"]


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> HostProvisioner:
    return HostProvisioner(tmp_path_factory.mktemp("envs"), exclude_newer=CUT_OFF)


def snapshot_of(kind: str, root: Path) -> Path:
    snapshot = root / "snapshot"
    shutil.copytree(PROJECTS / kind, snapshot)
    return snapshot


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_provisions_on_the_host(host: HostProvisioner, tmp_path: Path, kind: str) -> None:
    snapshot = snapshot_of(kind, tmp_path)
    box = ProcessSandbox(tmp_path / "work", Limits(timeout_s=300))
    env = host.provision("base", inspect_project(snapshot), box)
    EnvProvisionedPayload.model_validate(env.payload())
    assert env.payload()["project_kind"] == kind
    assert env.python_version.startswith("3.13.")
    run = box.run([env.python, *PYTEST], cwd=snapshot)
    assert run.returncode == 0, run.stdout.decode() + run.stderr.decode()
    assert b"2 passed" in run.stdout


def test_both_sides_share_the_dependencies(host: HostProvisioner, tmp_path: Path) -> None:
    snapshot = snapshot_of("requirements", tmp_path)
    project = inspect_project(snapshot)
    first = host.provision("base", project, ProcessSandbox(tmp_path / "base"))
    second = host.provision("head", project, ProcessSandbox(tmp_path / "head"))
    assert second.cache_hit
    assert second.installed_packages == first.installed_packages


@pytest.mark.parametrize(
    ("requirements", "reason"),
    [
        ("repro-no-such-package==1.0\n", "installing the dependencies failed"),
        # Only a source distribution: building it would run its code with network access.
        ("pyperclip==1.9.0\n", "installing the dependencies failed"),
    ],
)
def test_a_broken_install_is_a_reason_not_a_crash(
    host: HostProvisioner, tmp_path: Path, requirements: str, reason: str
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "requirements.txt").write_text(requirements, encoding="utf-8")
    with pytest.raises(ProvisionError, match=reason) as failure:
        host.provision("head", inspect_project(snapshot), ProcessSandbox(tmp_path / "work"))
    assert str(failure.value).split(": ", 1)[1]  # uv's own explanation follows
    missing = environment_missing("head", str(failure.value))
    MissingRecordedPayload.model_validate(missing)
    assert missing["missing"]["reason"] == "environment_failed"


def test_a_project_whose_own_install_fails_says_so(host: HostProvisioner, tmp_path: Path) -> None:
    snapshot = snapshot_of("setuptools", tmp_path)
    (snapshot / "setup.py").write_text(
        "raise SystemExit('this project cannot be built')\n", encoding="utf-8"
    )
    with pytest.raises(ProvisionError, match="the project's own install failed"):
        host.provision("head", inspect_project(snapshot), ProcessSandbox(tmp_path / "work"))


docker = pytest.mark.skipif(
    not docker_available() and os.environ.get("REPRO_REQUIRE_DOCKER") != "1",
    reason="Docker with Linux containers is not available",
)


@pytest.fixture(scope="module")
def image() -> str:
    return sandbox_image()


@pytest.fixture
def commit(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Git, str]:
    kind: str = request.param
    repo = Repo(tmp_path / "repo")
    files = {
        path.relative_to(PROJECTS / kind).as_posix(): path.read_text(encoding="utf-8")
        for path in (PROJECTS / kind).rglob("*")
        if path.is_file()
    }
    return Git(repo.path), repo.commit(files)


@docker
@pytest.mark.parametrize("commit", KINDS, indirect=True)
def test_each_kind_provisions_in_a_container(
    image: str, tmp_path: Path, commit: tuple[Git, str], request: pytest.FixtureRequest
) -> None:
    git, sha = commit
    kind = request.node.callspec.params["commit"]
    provisioner = DockerProvisioner(image, exclude_newer=CUT_OFF)
    with DockerSandbox(
        tmp_path / "work", git, sha, image=image, limits=Limits(timeout_s=300)
    ) as box:
        env = provisioner.provision("head", inspect_project(PROJECTS / kind), box)
        run = box.run([env.python, *PYTEST])
    EnvProvisionedPayload.model_validate(env.payload())
    assert run.returncode == 0, run.stdout.decode() + run.stderr.decode()
    assert b"2 passed" in run.stdout


def build_twice_at_once(build: Callable[[], tuple[object, bool]]) -> list[tuple[object, bool]]:
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(lambda _: build(), range(2)))


def test_two_sides_building_one_environment_at_once(tmp_path: Path) -> None:
    """Both sides of a run need the same dependencies at the same moment: one builds them, the
    other waits and uses that build (two container builds once collided on Linux CI)."""
    provisioner = HostProvisioner(tmp_path / "envs", exclude_newer=CUT_OFF)
    project = inspect_project(snapshot_of("requirements", tmp_path))
    spec = spec_for(project, platform="test", exclude_newer=CUT_OFF)
    results = build_twice_at_once(lambda: provisioner.dependencies(spec))
    assert results[0][0] == results[1][0]
    assert sorted(hit for _, hit in results) == [False, True]


@docker
def test_two_container_builds_of_one_environment_at_once(image: str, tmp_path: Path) -> None:
    provisioner = DockerProvisioner(image, exclude_newer="2025-01-02T00:00:00Z")
    project = inspect_project(snapshot_of("requirements", tmp_path))
    spec = spec_for(project, platform=f"linux, {image}", exclude_newer="2025-01-02T00:00:00Z")
    results = build_twice_at_once(lambda: provisioner.dependencies(spec))
    try:
        assert results[0][0] == results[1][0]
        assert sorted(hit for _, hit in results) == [False, True]
    finally:  # not left as a cache: the next run of this test must build again
        subprocess.run(["docker", "volume", "rm", "-f", str(results[0][0])], check=False)
