"""The E2B sandbox: each side in a Firecracker microVM of a self-hosted E2B (K09, ADR-0018 B).

E2B's runtime gives "one Firecracker microVM per sandbox, in its own cgroup and network
namespace, with a per-sandbox nftables egress firewall" [e2b-dev/runtime README, read on
2026-10-22]. Its Embed package runs the whole stack on one Linux host with KVM. Repro talks to
it through E2B's Python SDK (``e2b``, MIT), which reads ``E2B_API_KEY`` and ``E2B_DOMAIN`` or
``E2B_API_URL`` from the environment: Repro never holds E2B's key itself.

A side's microVM:

1. starts from a template of Repro's sandbox image (``image/Dockerfile``'s recipe, step by
   step), named by the recipe's digest and its size, so it is built once per E2B and reused;
2. may reach the package index alone, through E2B's egress allow-list, while its dependencies
   are installed from wheels: no code of the target's runs then;
3. is **sealed** before any of the target's code runs. Every outbound address is denied
   (``update_network``), and a probe from inside, as the unprivileged user, must then fail to
   reach the index and an address outside it. If either connects, the side has no sandbox:
   the card never states a network it did not check. ``run`` refuses to run anything on a VM
   that is not sealed.

The snapshot and Repro's hook go in as archives, unpacked as root, the snapshot handed to the
unprivileged user and the hook left read-only. Commands run as that user, with its process
limit (``ulimit -u``: the VM's kernel counts only its own processes, as in K10), from a shell
that ``exec``s the command. The VM's memory is the template's (``e2b_memory_mb``).

The level is L5: a microVM per side, its own kernel. The network is ``enforced`` by the
host's firewall outside the VM, which a process inside cannot change, root or not.
"""

import contextlib
import hashlib
import importlib
import io
import json
import posixpath
import shlex
import tarfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from repro.gitops import Git, TarredTree, tar_tree
from repro.sandbox.detect import AUDIT_LOG_ENV, AUDIT_ROOTS_ENV, Detections, read_detections
from repro.sandbox.docker import DEFAULT_IMAGE, hook_archive
from repro.sandbox.limits import Limits
from repro.sandbox.process import HASH_SEED, POLL_S, Execution, Outcome, SandboxError
from repro.sandbox.remote import HOOK_MOUNT, TMP, WORK, RemoteSandbox

#: The hosts dependencies are installed from (``provision.env.PYPI`` and its files).
PACKAGE_INDEX: Final = ("pypi.org", "files.pythonhosted.org")
#: Every outbound address: what a sealed VM is denied.
ALL_TRAFFIC: Final = "0.0.0.0/0"
#: The user commands run as: E2B's own unprivileged user in every template.
RUN_AS: Final = "user"
ROOT: Final = "root"
#: How long a VM may live from now: the most E2B allows ("Timeout cannot be greater than 1
#: hours", K09). Each command renews it, and so does a long one every ``RENEW_S``.
LIFETIME_S: Final = 3600
RENEW_S: Final = 600.0
#: What the seal's probe tries: the index, and an address outside it. Each must fail.
_PROBE: Final = """
import socket, sys
reached = []
for host, port in (("pypi.org", 443), ("1.1.1.1", 53)):
    try:
        socket.create_connection((host, port), timeout=5).close()
        reached.append(f"{host}:{port}")
    except OSError:
        pass
print(",".join(reached))
sys.exit(1 if reached else 0)
"""


def sdk() -> Any:
    """E2B's SDK, or a ``SandboxError`` naming how to install it."""
    try:
        return importlib.import_module("e2b")
    except ImportError:
        raise SandboxError(
            "the E2B sandbox needs E2B's SDK: install repro-engine[e2b] (pip) or run "
            "`uv sync --extra e2b`"
        ) from None


#: The template's recipe: ``image/Dockerfile``'s, step by step, since E2B's builder takes no
#: ``COPY --from`` (K09 found it refusing the Dockerfile's ``/uv``). The same base image by
#: digest, the same Debian packages, and uv 0.13.0, the version Repro pins, from PyPI with its
#: wheels' SHA-256 (pypi.org/pypi/uv/0.13.0/json, read on 2026-10-23).
TEMPLATE_BASE: Final = DEFAULT_IMAGE
UV_REQUIREMENT: Final = (
    "uv==0.13.0"
    " --hash=sha256:52c7da0fd9056d9551124777ec77de53f0df7017daf8f98a19e947b7837416ed"
    " --hash=sha256:f840e640fe16591f6d71a94e8863707b7ba43c5786d1fe662868a9fb44c53e50"
)
TEMPLATE_PACKAGES: Final = ("less", "git", "procps", "tzdata")
_UV_INSTALL: Final = (
    f"printf '%s\\n' {shlex.quote(UV_REQUIREMENT)} > /tmp/uv.txt"
    " && python3 -m pip install --no-cache-dir --require-hashes -r /tmp/uv.txt"
    " && rm /tmp/uv.txt && uv --version"
)


def template_name(memory_mb: int, cpus: int) -> str:
    """The template at this size: the recipe's digest and the size in the name, so a changed
    recipe or size is a new template and an unchanged one is built once per E2B."""
    recipe = json.dumps([TEMPLATE_BASE, UV_REQUIREMENT, TEMPLATE_PACKAGES]).encode()
    return f"repro-sandbox-{hashlib.sha256(recipe).hexdigest()[:12]}-{cpus}c{memory_mb}m"


_BUILDING = threading.Lock()


def ensure_template(*, memory_mb: int, cpus: int, log: Callable[[str], None] | None = None) -> str:
    """The template's name, built first if this E2B does not have it (once, when both sides
    ask at the same time)."""
    e2b = sdk()
    name = template_name(memory_mb, cpus)
    with _BUILDING:
        try:
            if e2b.Template.exists(name):
                return name
            if log is not None:
                log(f"building the E2B template {name} (once per E2B)")
            template = (
                e2b.Template()
                .from_image(TEMPLATE_BASE)
                .run_cmd(_UV_INSTALL, user=ROOT)
                .apt_install(list(TEMPLATE_PACKAGES), no_install_recommends=True)
            )
            e2b.Template.build(template, name, cpu_count=cpus, memory_mb=memory_mb)
        except (e2b.SandboxException, e2b.BuildException) as exc:  # BuildException is apart
            raise SandboxError(f"the E2B template {name} could not be built: {exc}") from None
    return name


class E2BSandbox(RemoteSandbox):
    """Runs commands at L5 on commit ``commit`` of ``git``'s repository, in a microVM."""

    backend = "e2b"

    def __init__(
        self,
        work: Path,
        git: Git,
        commit: str,
        *,
        template: str,
        limits: Limits | None = None,
        index: Sequence[str] = PACKAGE_INDEX,
        vm: Any = None,
    ) -> None:
        self.work = work
        self.limits = limits or Limits()
        self.template = template
        self.python_path = ()
        self.variables: dict[str, str] = {}
        self.sealed = False
        self._runs = 0
        self._lock = threading.Lock()
        self.work.mkdir(parents=True, exist_ok=True)
        self._e2b = sdk()
        try:
            self.vm = vm or self._e2b.Sandbox.create(
                template,
                timeout=LIFETIME_S,
                network={"allow_out": list(index), "deny_out": [ALL_TRAFFIC]},
            )
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B could not start a sandbox: {exc}") from None
        try:
            self._unpack(HOOK_MOUNT, hook_archive(), owner=None)
            self.tree = self._load(git, commit)
        except BaseException:
            self.close()
            raise

    # -- the level -----------------------------------------------------------------------------

    @property
    def isolation_level(self) -> str:
        return "L5"

    def ready_payload(self, side: str) -> dict[str, str]:
        """The ``sandbox.ready`` payload: L5, the network enforced once sealed (before any of
        the target's code runs; a VM that cannot be sealed has no sandbox)."""
        return {
            "side": side,
            "backend": self.backend,
            "isolation_level": self.isolation_level,
            "network": "enforced",
            "platform": f"E2B Firecracker microVM, template {self.template}"[:200],
        }

    def seal(self) -> None:
        """Denies the VM every outbound address, and checks it from inside: the index and an
        address outside it must both be unreachable to the user commands run as."""
        try:
            self.vm.update_network({"deny_out": [ALL_TRAFFIC]})
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B could not close the sandbox's network: {exc}") from None
        done = self._raw(["python3", "-I", "-S", "-c", _PROBE], user=RUN_AS, timeout_s=60)
        if done.exit_code != 0:
            reached = done.stdout.strip() or "?"
            raise SandboxError(f"the sandbox's network is still open after sealing: {reached}")
        self.sealed = True

    # -- files ---------------------------------------------------------------------------------

    def _raw(self, argv: Sequence[str], *, user: str, timeout_s: float, cwd: str = "/") -> Any:
        """``argv`` in the VM, waited for; its result whatever its exit status."""
        try:
            return self.vm.commands.run(shlex.join(argv), user=user, cwd=cwd, timeout=timeout_s)
        except self._e2b.CommandExitException as exc:
            return exc  # it carries stdout, stderr and exit_code too
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B: {exc}") from None

    def _unpack(self, target: str, archive: bytes, *, owner: str | None) -> None:
        """``archive`` unpacked at ``target`` as root; handed to ``owner``, else read-only."""
        staged = f"{TMP}/repro-{time.monotonic_ns()}.tar"
        try:
            self.vm.files.write(staged, archive, user=ROOT)
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B: writing into the sandbox failed: {exc}") from None
        hand = f"chown -R {owner}:{owner} {target}" if owner else f"chmod -R a-w,a+rX {target}"
        script = (
            f"set -e; mkdir -p {target}; tar -x -C {target} --no-same-owner -f {staged}; "
            f"rm -f {staged}; {hand}"
        )
        done = self._raw(["sh", "-c", script], user=ROOT, timeout_s=300)
        if done.exit_code != 0:
            raise SandboxError(f"unpacking into the sandbox failed: {done.stderr.strip()[-300:]}")

    def own_directory(self, path: str) -> None:
        """Makes ``path`` (outside the snapshot: an environment's) the unprivileged user's."""
        script = f"mkdir -p {shlex.quote(path)} && chown {RUN_AS}:{RUN_AS} {shlex.quote(path)}"
        done = self._raw(["sh", "-c", script], user=ROOT, timeout_s=60)
        if done.exit_code != 0:
            raise SandboxError(f"preparing {path} failed: {done.stderr.strip()[-300:]}")

    def _load(self, git: Git, commit: str) -> TarredTree:
        archive = io.BytesIO()
        tree = tar_tree(git, commit, archive)
        self._unpack(WORK, archive.getvalue(), owner=RUN_AS)
        self._unpack(f"{WORK}/.repro", _tar({}), owner=RUN_AS)
        return tree

    def write_files(self, directory: str, files: Mapping[str, bytes]) -> None:
        target = self.container_path(directory)
        for path in files:  # each must stay inside the snapshot
            self.container_path(f"{directory}/{path}")
        self._unpack(target, _tar(files), owner=RUN_AS)

    def overlay(self, name: str, files: Mapping[str, bytes]) -> str:
        if not name.isidentifier():
            raise SandboxError(f"{name!r} is not a plain name")
        relative = f".repro/{name}"
        target = self.container_path(relative)
        copy = (
            f"set -e; mkdir -p {target}; cd {WORK}; "
            f"tar --exclude=./.repro -cf - . | tar -x -C {target}"
        )
        done = self._raw(["sh", "-c", copy], user=RUN_AS, timeout_s=300)
        if done.exit_code != 0:
            raise SandboxError(f"copying the snapshot failed: {done.stderr.strip()[-300:]}")
        for path in files:
            self.container_path(f"{relative}/{path}")
        self._unpack(target, _tar(files), owner=RUN_AS)
        return relative

    def read_file(self, relative: str, *, limit: int = 64 * 1024 * 1024) -> bytes | None:
        return self._read(self.container_path(relative), limit)

    def _read(self, path: str, limit: int) -> bytes | None:
        try:
            data = self.vm.files.read(path, format="bytes", user=ROOT)
        except (self._e2b.NotFoundException, self._e2b.FileNotFoundException):
            return None
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B: reading {path} failed: {exc}") from None
        return bytes(data[:limit])

    def close(self) -> None:
        vm = getattr(self, "vm", None)
        if vm is not None:
            with contextlib.suppress(Exception):  # it may already be gone
                vm.kill()

    # -- running -------------------------------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        """Runs ``argv`` as the unprivileged user, from ``cwd``, in the sealed VM."""
        if not argv:
            raise SandboxError("no command")
        if not self.sealed:
            raise SandboxError(
                "the sandbox is not sealed: nothing of the target's runs on a network"
            )
        return self._run(argv, cwd=cwd, env=env, timeout_s=timeout_s, stop=stop)

    def run_unsealed(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None,
                     timeout_s: float) -> Execution:  # fmt: skip
        """For the provisioner alone: a command before the seal, reaching the index only. It
        must run none of the target's code (dependencies from wheels, ``--no-build``)."""
        return self._run(argv, cwd=".", env=env, timeout_s=timeout_s, stop=None)

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None,
        timeout_s: float | None,
        stop: Callable[[], bool] | None,
    ) -> Execution:
        with self._lock:
            self._runs += 1
            number = self._runs
        run_dir = self.work / f"run-{number}"
        run_dir.mkdir(parents=True, exist_ok=False)
        audit = f"{WORK}/.repro/audit-{number}.jsonl"
        limit = self.limits.processes
        command = f"ulimit -u {limit}; exec {shlex.join(argv)}"
        timeout = timeout_s if timeout_s is not None else self.limits.timeout_s
        self._renew()
        started = renewed = time.monotonic()
        outcome: Outcome = "exited"
        out: list[str] = []
        err: list[str] = []
        try:
            handle = self.vm.commands.run(
                command,
                background=True,
                user=RUN_AS,
                cwd=self.container_path(cwd),
                envs=self._environment(audit, env),
                timeout=0,  # Repro keeps the time
                on_stdout=out.append,
                on_stderr=err.append,
            )
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B could not start the command: {exc}") from None
        result: list[Any] = []
        waiter = threading.Thread(target=lambda: result.append(_wait(handle, self._e2b)))
        waiter.start()
        while waiter.is_alive():
            if time.monotonic() - started > timeout:
                outcome = "timeout"
                break
            if stop is not None and stop():
                outcome = "stopped"
                break
            if time.monotonic() - renewed > RENEW_S:
                self._renew()
                renewed = time.monotonic()
            waiter.join(POLL_S)
        if waiter.is_alive():
            _kill(handle)
            self._raw(["pkill", "-KILL", "-u", RUN_AS], user=ROOT, timeout_s=60)
            waiter.join(30)
        duration = time.monotonic() - started
        code = getattr(result[0], "exit_code", None) if result else None
        stdout, cut_out = _head("".join(out), self.limits.output_bytes)
        stderr, cut_err = _head("".join(err), self.limits.output_bytes)
        log = self._read(audit, 64 * 1024 * 1024)
        log_path = run_dir / "audit.jsonl"
        if log is not None:
            log_path.write_bytes(log)
        return Execution(
            argv=tuple(argv),
            outcome=outcome,
            returncode=int(code) if outcome == "exited" and code is not None else None,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
            output_truncated=cut_out or cut_err,
            left_running=False,  # the user's processes are killed at a timeout or a stop
            detections=read_detections(log_path) if log else Detections((), 0, truncated=False),
            oom_killed=code == 137,  # noqa: PLR2004 - SIGKILL, as the kernel's OOM killer sends
        )

    def _renew(self) -> None:
        """The VM's lifetime, from now, ``LIFETIME_S`` again."""
        try:
            self.vm.set_timeout(LIFETIME_S)
        except self._e2b.SandboxException as exc:
            raise SandboxError(f"E2B could not keep the sandbox alive: {exc}") from None

    def _environment(self, audit: str, extra: Mapping[str, str] | None) -> dict[str, str]:
        """As the Docker sandbox's: a home in ``/tmp``, the hook first on the import path."""
        extra = dict(extra or {})
        python_path = [HOOK_MOUNT, *self.python_path]
        if extra.get("PYTHONPATH"):
            python_path.append(extra["PYTHONPATH"])
        env = {
            "HOME": TMP,
            "TMPDIR": TMP,
            "PYTHONHASHSEED": str(HASH_SEED),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            **self.variables,
            **extra,
        }
        env["PYTHONPATH"] = ":".join(python_path)
        env[AUDIT_LOG_ENV] = audit
        env[AUDIT_ROOTS_ENV] = f"{WORK}:{TMP}"
        return env


def _wait(handle: Any, e2b: Any) -> Any:
    try:
        return handle.wait()
    except e2b.CommandExitException as exc:
        return exc


def _kill(handle: Any) -> None:
    with contextlib.suppress(Exception):  # it may have ended meanwhile
        handle.kill()


def _head(text: str, limit: int) -> tuple[bytes, bool]:
    data = text.encode("utf-8", "replace")
    return data[:limit], len(data) > limit


def _tar(files: Mapping[str, bytes]) -> bytes:
    """``files`` (POSIX paths) as a tar archive, readable by everyone."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for path, data in sorted(files.items()):
            name = posixpath.normpath(path)
            if name.startswith(("/", "..")):
                raise SandboxError(f"{path!r} is outside the snapshot")
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return archive.getvalue()
