"""The E2B sandbox on real Firecracker microVMs (K09): the rules ``test_sandbox_e2b.py`` checks
against a fake, here against a self-hosted E2B.

They run where one answers: its SDK's variables set (``E2B_API_KEY``, and ``E2B_API_URL`` or
``E2B_DOMAIN``) and ``REPRO_E2B_LIVE=1``, as in CI's ``e2b`` job. The microVM's size comes from
``REPRO_E2B_MEMORY_MB`` (512 by default: a host with little memory, as WSL2 on a laptop).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import Git
from repro.sandbox import Limits, SandboxError
from repro.sandbox.e2b import E2BSandbox, ensure_template

pytestmark = pytest.mark.skipif(
    os.environ.get("REPRO_E2B_LIVE") != "1",
    reason="no self-hosted E2B to reach (REPRO_E2B_LIVE=1, E2B_API_KEY, E2B_API_URL)",
)

CODE = {
    "pkg/__init__.py": "def add(a, b):\n    return a + b\n",
    "tests/test_add.py": "from pkg import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n",
}


@pytest.fixture(scope="module")
def template() -> str:
    return ensure_template(memory_mb=int(os.environ.get("REPRO_E2B_MEMORY_MB", "512")), cpus=2)


@pytest.fixture
def box(tmp_path: Path, template: str) -> Iterator[E2BSandbox]:
    repo = Repo(tmp_path / "repo")
    sha = repo.commit(CODE)
    vm = E2BSandbox(
        tmp_path / "work", Git(repo.path), sha, template=template,
        limits=Limits(timeout_s=120, processes=64),
    )  # fmt: skip
    try:
        yield vm
    finally:
        vm.close()


def connect(host: str, port: int) -> list[str]:
    return [
        "python3",
        "-c",
        f"import socket; socket.create_connection(({host!r}, {port}), timeout=5); print('reached')",
    ]


def test_nothing_of_the_targets_runs_before_the_seal(box: E2BSandbox) -> None:
    with pytest.raises(SandboxError, match="not sealed"):
        box.run(["true"])
    # Before the seal the side may reach the package index, for its wheels.
    fetch = "import urllib.request as u; print(u.urlopen(u.Request(%r), timeout=15).status)"
    index = box.run_unsealed(
        ["python3", "-c", fetch % "https://pypi.org/simple/attrs/"], timeout_s=60
    )
    assert (index.returncode, index.stdout.strip()) == (0, b"200")


def test_the_seal_closes_every_address_name_or_number(box: E2BSandbox) -> None:
    box.seal()
    for host, port in (("pypi.org", 443), ("1.1.1.1", 443), ("8.8.8.8", 53), ("8.8.8.8", 443)):
        done = box.run(connect(host, port))
        assert done.returncode != 0, (host, port, done.stdout)
        assert b"reached" not in done.stdout
    # The attempt Python made is recorded as evidence, as in any other sandbox.
    attempts = box.run(connect("pypi.org", 443)).detections
    assert any(d.kind == "network" for d in attempts.items)


def test_the_target_runs_as_a_user_without_sudo_on_a_kernel_of_its_own(box: E2BSandbox) -> None:
    box.seal()
    who = box.run(["sh", "-c", "id -u; id -G; sudo -n true 2>/dev/null && echo sudo || echo none"])
    assert who.stdout.split() == [b"1001", b"1001", b"none"]
    rules = box.run(["sh", "-c", "nft flush ruleset 2>&1; echo $?"])
    assert rules.stdout.strip().splitlines()[-1] != b"0"  # it cannot open the network again
    still = box.run(connect("1.1.1.1", 443))
    assert still.returncode != 0
    ready = box.ready_payload("head")
    assert (ready["isolation_level"], ready["network"]) == ("L5", "enforced")


def test_the_snapshots_code_runs_and_its_files_come_back(box: E2BSandbox) -> None:
    box.seal()
    done = box.run(["python3", "-c", "import pkg; print(pkg.add(2, 3))"])
    assert (done.returncode, done.stdout.strip()) == (0, b"5")
    box.write_files(".repro", {"note.txt": b"written by repro"})
    assert box.read_file(".repro/note.txt") == b"written by repro"
    assert box.read_file(".repro/none.txt") is None


def test_a_fork_bomb_meets_the_process_limit_and_a_timeout_kills(box: E2BSandbox) -> None:
    box.seal()
    bomb = box.run(["sh", "-c", "for i in $(seq 200); do sleep 30 & done; wait"], timeout_s=8)
    assert b"Cannot fork" in bomb.stderr or bomb.outcome == "timeout"
    slow = box.run(["sleep", "60"], timeout_s=3)
    assert slow.outcome == "timeout"
    assert slow.duration_s < 30
    after = box.run(["sh", "-c", "ps -u repro -o pid= | wc -l"])
    assert int(after.stdout.strip() or 0) <= 3  # the killed commands left nothing running
