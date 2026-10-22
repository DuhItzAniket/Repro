"""The E2B sandbox's rules, against a fake of E2B's SDK (K09).

What is checked here is Repro's side of the bargain:
- a VM starts allowed the package index alone, and nothing of the target's runs before it is
  sealed;
- the seal is checked from inside, and a seal the probe sees through gives no sandbox;
- commands run as the unprivileged user under its process limit, with Repro's hook first on
  the import path;
- a command past its time is killed;
- paths stay inside the snapshot.

Real microVMs are ``test_sandbox_e2b_live.py``'s, in CI's ``e2b`` job.
"""

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from gitrepo import Repo
from repro.gitops import Git
from repro.pipeline import run_backend
from repro.provision.env import ENV_MOUNT, E2BProvisioner
from repro.provision.project import inspect_project
from repro.sandbox import Limits, SandboxError
from repro.sandbox import e2b as module
from repro.sandbox.e2b import ALL_TRAFFIC, PACKAGE_INDEX, E2BSandbox, template_name


class FakeSandboxError(Exception):  # the SDK's SandboxException
    pass


class FakeCommandExitError(FakeSandboxError):  # CommandExitException
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 1) -> None:
        super().__init__(stderr)
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code


class FakeNotFoundError(FakeSandboxError):  # NotFoundException
    pass


class Result(SimpleNamespace):
    stdout: str
    stderr: str
    exit_code: int


class Handle:
    def __init__(self, result: Result, *, hang: bool = False) -> None:
        self.result, self.released, self.killed = result, threading.Event(), False
        if not hang:
            self.released.set()

    def wait(self) -> Result:
        self.released.wait(30)
        return self.result

    def kill(self) -> None:
        self.killed = True
        self.released.set()


class Commands:
    def __init__(self, vm: "FakeVM") -> None:
        self.vm = vm

    def run(self, cmd: str, **options: Any) -> Any:
        self.vm.ran.append((cmd, options))
        if "socket.create_connection" in cmd:  # the seal's probe
            reached = "" if self.vm.closed else "pypi.org:443"
            if reached:
                raise FakeCommandExitError(stdout=reached, exit_code=1)
            return Result(stdout="", stderr="", exit_code=0)
        if options.get("background"):
            if options.get("on_stdout"):
                options["on_stdout"]("out\n")
            handle = Handle(Result(stdout="out\n", stderr="", exit_code=self.vm.code),
                            hang=self.vm.hang)  # fmt: skip
            self.vm.handles.append(handle)
            return handle
        return Result(stdout="", stderr="", exit_code=0)


class Files:
    def __init__(self, vm: "FakeVM") -> None:
        self.vm = vm

    def write(self, path: str, data: bytes, **options: Any) -> None:
        self.vm.written[path] = (data, options.get("user"))

    def read(self, path: str, **_: Any) -> bytes:
        if path not in self.vm.readable:
            raise FakeNotFoundError(path)
        return self.vm.readable[path]


class FakeVM:
    def __init__(self, template: str, **options: Any) -> None:
        self.template, self.options = template, options
        self.ran: list[tuple[str, dict[str, Any]]] = []
        self.written: dict[str, tuple[bytes, str | None]] = {}
        self.readable: dict[str, bytes] = {}
        self.network: list[dict[str, Any]] = []
        self.handles: list[Handle] = []
        self.closed = False  # whether the network is closed
        self.hang = False
        self.code = 0
        self.killed = False
        self.commands = Commands(self)
        self.files = Files(self)

    def update_network(self, network: dict[str, Any]) -> None:
        self.network.append(network)
        self.closed = network == {"deny_out": [ALL_TRAFFIC]}

    def kill(self) -> None:
        self.killed = True


class Templates:
    built: ClassVar[list[tuple[str, int, int]]] = []
    have: ClassVar[set[str]] = set()

    steps: ClassVar[list[str]] = []

    def from_image(self, image: str) -> "Templates":
        Templates.steps.append(f"from {image}")
        return self

    def run_cmd(self, command: str, *, user: str) -> "Templates":
        Templates.steps.append(f"run as {user}: {command}")
        return self

    def apt_install(self, packages: list[str], *, no_install_recommends: bool) -> "Templates":
        Templates.steps.append(f"apt {' '.join(packages)} {no_install_recommends}")
        return self

    @classmethod
    def exists(cls, name: str) -> bool:
        return name in cls.have

    @classmethod
    def build(cls, _template: Any, name: str, *, cpu_count: int, memory_mb: int) -> None:
        cls.built.append((name, cpu_count, memory_mb))
        cls.have.add(name)


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    made: list[FakeVM] = []

    def create(template: str, **options: Any) -> FakeVM:
        vm = FakeVM(template, **options)
        made.append(vm)
        return vm

    fake = SimpleNamespace(
        Sandbox=SimpleNamespace(create=create),
        Template=Templates,
        SandboxException=FakeSandboxError,
        CommandExitException=FakeCommandExitError,
        NotFoundException=FakeNotFoundError,
        FileNotFoundException=FakeNotFoundError,
        made=made,
    )
    Templates.built, Templates.have, Templates.steps = [], set(), []
    monkeypatch.setattr(module, "sdk", lambda: fake)
    return fake


@pytest.fixture
def commit(tmp_path: Path) -> tuple[Git, str]:
    repo = Repo(tmp_path / "repo")
    sha = repo.commit({"pkg/__init__.py": "", "tests/test_a.py": "def test_a():\n    pass\n"})
    return Git(repo.path), sha


def vm_of(sdk: SimpleNamespace) -> FakeVM:
    found: FakeVM = sdk.made[-1]
    return found


def make(tmp_path: Path, commit: tuple[Git, str], **options: Any) -> E2BSandbox:
    git, sha = commit
    return E2BSandbox(tmp_path / "work", git, sha, template="repro-sandbox-x", **options)


def test_a_vm_may_reach_the_package_index_alone(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit)
    vm = vm_of(sdk)
    assert vm.options["network"] == {"allow_out": list(PACKAGE_INDEX), "deny_out": [ALL_TRAFFIC]}
    assert PACKAGE_INDEX == ("pypi.org", "files.pythonhosted.org")
    # The hook and the snapshot went in as archives, unpacked as root: the hook read-only,
    # the snapshot the unprivileged user's.
    unpacked = [cmd for cmd, options in vm.ran if options.get("user") == "root"]
    assert any("/opt/repro/hook" in c and "chmod -R a-w,a+rX" in c for c in unpacked)
    assert any("tar -x -C /work " in c and "chown -R user:user /work" in c for c in unpacked)
    assert all(user == "root" for _, user in vm.written.values())
    assert not box.sealed


def test_nothing_runs_before_the_seal(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit)
    with pytest.raises(SandboxError, match="not sealed"):
        box.run(["python", "-c", "pass"])
    assert box.run_unsealed(["uv", "pip", "install"], timeout_s=60).returncode == 0


def test_the_seal_denies_every_address_and_is_checked_from_inside(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit)
    box.seal()
    vm = vm_of(sdk)
    assert vm.network == [{"deny_out": [ALL_TRAFFIC]}]
    probe, options = next((c, o) for c, o in vm.ran if "socket.create_connection" in c)
    assert options["user"] == "user"
    assert "pypi.org" in probe
    assert "1.1.1.1" in probe
    assert box.sealed
    ready = box.ready_payload("base")
    assert (ready["backend"], ready["isolation_level"], ready["network"]) == (
        "e2b",
        "L5",
        "enforced",
    )


def test_a_seal_the_probe_sees_through_gives_no_sandbox(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = make(tmp_path, commit)
    monkeypatch.setattr(FakeVM, "update_network", lambda self, network: None)  # ignored
    with pytest.raises(SandboxError, match=r"still open after sealing: pypi\.org:443"):
        box.seal()
    assert not box.sealed
    with pytest.raises(SandboxError, match="not sealed"):
        box.run(["python", "-c", "pass"])


def test_commands_run_as_the_user_under_its_process_limit_with_the_hook_first(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit, limits=Limits(processes=64))
    box.seal()
    done = box.run(["python", "-c", "print(1)"], cwd="pkg", env={"PYTHONPATH": "/extra"})
    command, options = next((c, o) for c, o in vm_of(sdk).ran if o.get("background"))
    assert command == "ulimit -u 64; exec python -c 'print(1)'"
    assert (options["user"], options["cwd"]) == ("user", "/work/pkg")
    assert options["envs"]["PYTHONPATH"] == "/opt/repro/hook:/extra"
    assert options["envs"]["REPRO_AUDIT_LOG"].startswith("/work/.repro/audit-")
    assert (done.outcome, done.returncode, done.stdout) == ("exited", 0, b"out\n")


def test_a_command_past_its_time_is_killed(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit)
    box.seal()
    vm_of(sdk).hang = True
    done = box.run(["sleep", "600"], timeout_s=0.3)
    assert (done.outcome, done.returncode) == ("timeout", None)
    assert vm_of(sdk).handles[-1].killed
    assert any(c.startswith("pkill -KILL -u user") for c, _ in vm_of(sdk).ran)


def test_paths_stay_inside_the_snapshot(
    tmp_path: Path, commit: tuple[Git, str], sdk: SimpleNamespace
) -> None:
    box = make(tmp_path, commit)
    with pytest.raises(SandboxError, match="outside the snapshot"):
        box.write_files(".repro", {"../../etc/x": b"x"})
    with pytest.raises(SandboxError, match="outside the snapshot"):
        box.read_file("../etc/passwd")
    assert box.read_file(".repro/missing.json") is None
    vm_of(sdk).readable["/work/.repro/out.json"] = b"0123456789"
    assert box.read_file(".repro/out.json", limit=4) == b"0123"
    box.close()
    assert vm_of(sdk).killed


def test_a_template_is_built_once_per_image_and_size(sdk: SimpleNamespace) -> None:
    name = module.ensure_template(memory_mb=1024, cpus=2)
    again = module.ensure_template(memory_mb=1024, cpus=2)
    bigger = module.ensure_template(memory_mb=2048, cpus=2)
    assert name == again == template_name(1024, 2)
    assert name.startswith("repro-sandbox-")
    assert name.endswith("-2c1024m")
    assert bigger != name
    assert [built[0] for built in Templates.built] == [name, bigger]
    # Repro's image, step by step: its base by digest, uv 0.13.0 by hash, its packages.
    assert Templates.steps[0] == f"from {module.TEMPLATE_BASE}"
    assert "@sha256:" in Templates.steps[0]
    assert "uv==0.13.0 --hash=sha256:" in Templates.steps[1]
    assert "--require-hashes" in Templates.steps[1]
    assert Templates.steps[1].startswith("run as root: ")
    assert Templates.steps[2] == "apt less git procps tzdata True"


def test_without_its_sdk_the_sandbox_says_how_to_get_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_: str) -> None:
        raise ImportError("no e2b")

    monkeypatch.setattr("importlib.import_module", missing)
    with pytest.raises(SandboxError, match=r"repro-engine\[e2b\]"):
        module.sdk()


class Recorder:
    """An E2B sandbox's side, as the provisioner sees it: what it was asked, in order."""

    template = "repro-sandbox-x"

    def __init__(self) -> None:
        self.steps: list[str] = []
        self.sealed = False

    def own_directory(self, path: str) -> None:
        self.steps.append(f"own {path}")

    def write_files(self, directory: str, files: dict[str, bytes]) -> None:
        self.steps.append(f"write {directory}/{','.join(files)}")

    @staticmethod
    def container_path(relative: str) -> str:
        return f"/work/{relative}"

    def run_unsealed(self, argv: list[str], **_: Any) -> Any:
        assert not self.sealed
        self.steps.append(f"unsealed {argv[-1]}")
        return SimpleNamespace(returncode=0, outcome="exited", stdout=b"", stderr=b"")

    def seal(self) -> None:
        self.steps.append("seal")
        self.sealed = True

    def run(self, argv: list[str], **_: Any) -> Any:
        assert self.sealed
        self.steps.append(f"sealed {' '.join(argv[:3])}")
        out = b"3.13.9\n" if "platform" in " ".join(argv) else b"7\n"
        return SimpleNamespace(returncode=0, outcome="exited", stdout=out, stderr=b"")


def test_dependencies_come_from_wheels_before_the_seal_and_the_project_after(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "1"\ndependencies = ["attrs"]\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    side = Recorder()
    env = E2BProvisioner().provision("base", inspect_project(root), side)  # type: ignore[arg-type]
    unsealed = [s for s in side.steps if s.startswith("unsealed")]
    assert len(unsealed) == 1
    assert "--no-build" in unsealed[0]
    assert unsealed[0].startswith(f"unsealed uv venv {ENV_MOUNT}/venv")
    seal = side.steps.index("seal")
    assert side.steps.index(unsealed[0]) < seal
    assert any(s.startswith("sealed uv pip install") for s in side.steps[seal:])  # the project
    assert (env.python, env.python_version, env.installed_packages) == (
        f"{ENV_MOUNT}/venv/bin/python",
        "3.13.9",
        7,
    )


def test_the_e2b_backend_is_the_runs_when_it_runs_code() -> None:
    assert run_backend("e2b", None, runs_code=True) == "e2b"
    assert run_backend("e2b", None, runs_code=False) == "process"
