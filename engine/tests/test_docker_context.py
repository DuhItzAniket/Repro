"""The Docker sandbox on an engine named by a context (K05's local prototype).

A team's engine on another machine is a Docker context (``ssh://user@host``). Since H06 the
sandbox sends everything to the engine (snapshots, Repro's hook, environments, through its own
volumes and standard input) and mounts nothing from the host. So the same sandbox runs on any
engine the context names. Here the context points at this machine's engine by its endpoint.
It is created in a throwaway Docker configuration, so the user's own is never touched.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from cli_support import clean_env
from gitrepo import Repo
from repro.config import SettingsError, load_settings
from repro.gitops import Git
from repro.sandbox import DockerSandbox, Limits, docker_available
from repro.sandbox.image import sandbox_image

docker = pytest.mark.skipif(
    not docker_available() and os.environ.get("REPRO_REQUIRE_DOCKER") != "1",
    reason="Docker with Linux containers is not available",
)


def test_the_context_is_a_setting_with_a_plain_name(tmp_path: Path) -> None:
    assert (
        load_settings(env=clean_env(tmp_path, REPRO_DOCKER_CONTEXT="team-builder")).docker_context
        == "team-builder"
    )
    with pytest.raises(SettingsError, match="REPRO_DOCKER_CONTEXT"):
        load_settings(env=clean_env(tmp_path, REPRO_DOCKER_CONTEXT="--host=evil"))


@docker
def test_the_sandbox_runs_on_the_engine_a_context_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    image = sandbox_image()  # built or found through the user's own context, before the switch
    name = f"repro-k05-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "docker-config"))
    subprocess.run(
        ["docker", "context", "create", name, "--docker", f"host={endpoint}"],
        capture_output=True,
        check=True,
    )
    monkeypatch.setenv("DOCKER_CONTEXT", name)
    shown = subprocess.run(
        ["docker", "context", "show"], capture_output=True, check=True, text=True
    )
    assert shown.stdout.strip() == name
    repo = Repo(tmp_path / "repo")
    sha = repo.commit({"hello.txt": "from the snapshot\n"})
    with DockerSandbox(
        tmp_path / "work", Git(repo.path), sha, image=image, limits=Limits(timeout_s=120)
    ) as box:
        run = box.run(["cat", "hello.txt"])
    assert run.returncode == 0, run.stderr
    assert run.stdout == b"from the snapshot\n"
