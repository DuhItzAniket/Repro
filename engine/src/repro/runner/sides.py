"""A side of a change, ready to run its tests: its sandbox and its environment (D06)."""

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from repro.provision.deps import LIST_INSTALLED, parse_installed
from repro.provision.env import Environment
from repro.runner.pytest import TestRun, run_tests
from repro.sandbox.process import ProcessSandbox, SandboxError
from repro.sandbox.remote import RemoteSandbox


@dataclass
class Side:
    name: str  # "base" or "head"
    sandbox: ProcessSandbox | RemoteSandbox
    env: Environment

    def run(self, tests: Sequence[str] = (), **options: Any) -> TestRun:
        """``run_tests`` on this side (see it for the options)."""
        return run_tests(self.sandbox, self.env, tests=tests, **options)

    def installed(self, timeout_s: float = 120.0) -> dict[str, str] | None:
        """The environment's distributions, ``{name: version}``, listed by its own interpreter
        in this side's sandbox (E05); None if that did not work."""
        if isinstance(self.sandbox, RemoteSandbox):  # <venv>/bin/python, inside the container
            root = str(PurePosixPath(self.env.python).parent.parent)
            argv = [self.env.python, "-I", "-S", "-c", LIST_INSTALLED, root]
            done = self.sandbox.run(argv, timeout_s=timeout_s)
        else:  # <venv>/Scripts/python.exe or <venv>/bin/python
            root = str(Path(self.env.python).parent.parent)
            argv = [self.env.python, "-I", "-S", "-c", LIST_INSTALLED, root]
            done = self.sandbox.run(argv, cwd=self.env.project.root, timeout_s=timeout_s)
        return parse_installed(done.stdout) if done.returncode == 0 else None

    def overlay(self, name: str, files: Mapping[str, bytes]) -> str:
        """A copy of the snapshot, at ``.repro/<name>``, with ``files`` written over it; its path
        relative to the snapshot, for ``run(directory=...)``."""
        if isinstance(self.sandbox, RemoteSandbox):
            return self.sandbox.overlay(name, files)
        if not name.isidentifier():
            raise SandboxError(f"{name!r} is not a plain name")
        root = self.env.project.root.resolve()
        target = root / ".repro" / name

        def skip_own(directory: str, _names: list[str]) -> list[str]:
            return [".repro"] if Path(directory).resolve() == root else []

        shutil.copytree(root, target, ignore=skip_own, symlinks=True)
        for path, data in files.items():
            destination = (target / path).resolve()
            if not destination.is_relative_to(target) or destination == target:
                raise SandboxError(f"{path!r} is outside the snapshot")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        return f".repro/{name}"

    def close(self) -> None:
        if isinstance(self.sandbox, RemoteSandbox):
            self.sandbox.close()
