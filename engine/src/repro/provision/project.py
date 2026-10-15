"""What kind of Python project a snapshot is, and what it needs installed (D03).

Read from the snapshot's files only: nothing of the target is imported, built or run here. The
project's kind and its pinned or declared requirements come from, in order:

- ``uv.lock``: ``uv export --frozen`` (uv reads the lock; it resolves and builds nothing);
- ``poetry.lock`` / ``pdm.lock``: the lock's packages and versions, read as TOML;
- ``requirements*.txt``: the files themselves (``-r`` includes inside the snapshot);
- ``pyproject.toml`` ``[project]`` and dependency groups, then ``setup.py`` / ``setup.cfg``
  literals (``install_requires`` and test extras, read with ``ast`` and ``configparser``).

Whatever the requirements come from, what the metadata (``[project]``, ``setup.py``,
``setup.cfg``) declares is read too (``Project.declared``), for the dependency comparison: a
requirements file or a lock can leave out a dependency the metadata adds. It is None when it
cannot be read statically (``dynamic`` dependencies, a ``setup()`` that is not literal).

Every requirement must come from the package index: a URL, a path, a VCS reference or a pip
option (another index, ``--find-links``) is refused with its reason, because the install step
that fetches them has network access. ``pytest`` is added when the project does not declare it,
and noted.
"""

import ast
import configparser
import hashlib
import os
import re
import subprocess
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from packaging.requirements import InvalidRequirement, Requirement

ProjectKind = Literal["uv", "poetry", "pdm", "requirements", "setuptools", "unknown"]

#: Requirement files read for a requirements project, in this order (all that exist).
REQUIREMENT_FILES: Final = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements-tests.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
)
#: Extras and dependency groups that hold a project's test dependencies.
TEST_GROUPS: Final = ("test", "tests", "testing", "dev")
#: PEP 518: a project without ``[build-system]`` builds with setuptools.
DEFAULT_BUILD_REQUIRES: Final = ("setuptools",)
#: What a build backend asks for at editable-build time on top of ``build-system.requires``
#: (PEP 660's ``get_requires_for_build_editable``), read from the backend's own source, so that
#: no backend has to run before the network is off. hatchling 1.25.0 returns
#: ``editables~=0.3`` (``hatchling/build.py``); poetry-core, pdm-backend and setuptools needed
#: nothing more in D03's fixtures.
EDITABLE_REQUIRES: Final = {"hatchling.build": ("editables~=0.3",)}
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class ProjectError(Exception):
    """The project cannot be provisioned safely; the message says why (``environment_failed``)."""


@dataclass(frozen=True, slots=True)
class Project:
    kind: ProjectKind
    root: Path
    #: The file the requirements come from (relative), and its SHA-256.
    source: str | None
    lock_sha256: str | None
    requirements: tuple[str, ...]  # PEP 508, from the package index only
    build_requires: tuple[str, ...]
    #: Whether the project itself is installed (it has a pyproject.toml or setup.py).
    installable: bool
    notes: tuple[str, ...] = field(default=())
    #: What the project's metadata declares (``[project]``, ``setup.py``, ``setup.cfg``),
    #: whatever ``requirements`` come from; None if it cannot be read statically (E05, F02).
    declared: tuple[str, ...] | None = ()
    #: The metadata file (``pyproject.toml``, ``setup.py`` or ``setup.cfg``), if any.
    declared_file: str | None = None


def normalise(name: str) -> str:
    """PEP 503's normalised name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_problem(line: str) -> str | None:
    """Why a requirement line cannot be fetched from the index, or None."""
    text = line.split(" #", 1)[0].strip()
    if text.startswith("-"):
        return f"a pip option ({text.split()[0]}): Repro installs from the package index only"
    if "://" in text or "@" in text.split(";", 1)[0] or text.startswith(("git+", "hg+", "svn+")):
        return "a direct reference (URL, path or VCS): Repro installs from the package index only"
    if _NAME.match(text) is None:
        return "not a requirement"
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(lines: Iterable[str], source: str) -> list[str]:
    found = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        problem = requirement_problem(line)
        if problem is not None:
            raise ProjectError(f"{source}: {line!r} is {problem}")
        found.append(line.split(" #", 1)[0].strip())
    return found


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError(f"{path.name} cannot be read: {exc}") from None


def _uv_export(root: Path, uv: str) -> list[str]:
    command = [
        uv, "export", "--frozen", "--format", "requirements.txt", "--all-groups",
        "--no-emit-project", "--no-hashes", "--no-header", "--no-annotate",
    ]  # fmt: skip
    try:
        done = subprocess.run(  # noqa: S603 - uv, reading the lock only (--frozen)
            command,
            cwd=root,
            capture_output=True,
            timeout=120,
            check=False,
            env={"UV_NO_CONFIG": "1", "UV_OFFLINE": "1", **_uv_env()},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(f"uv export failed: {exc}") from None
    if done.returncode != 0:
        problem = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ProjectError(f"uv.lock cannot be exported: {problem[-1] if problem else '?'}")
    return _checked(done.stdout.decode("utf-8").splitlines(), "uv.lock")


def _uv_env() -> dict[str, str]:
    """What uv needs from the host environment to start (it reads no target configuration)."""
    keep = ("PATH", "SYSTEMROOT", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "TEMP", "TMP")
    return {name: os.environ[name] for name in keep if name in os.environ}


def _lock_packages(path: Path, kind: str) -> list[str]:
    """``name==version`` for every package of a poetry or pdm lock, with its markers."""
    lock = _toml(path)
    lines = []
    for package in lock.get("package", []):
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ProjectError(f"{path.name}: a package without a name or version")
        source = package.get("source")
        if isinstance(source, dict) and source.get("type") not in (None, "legacy", "pypi"):
            raise ProjectError(
                f"{path.name}: {name} comes from a {source.get('type')} source: Repro installs "
                "from the package index only"
            )
        marker = package.get("markers") if kind == "poetry" else package.get("marker")
        lines.append(f"{name}=={version}" + (f"; {marker}" if isinstance(marker, str) else ""))
    return _checked(lines, path.name)


def _requirement_file(path: Path, root: Path, seen: set[Path]) -> list[str]:
    """A requirements file's lines, following ``-r`` includes that stay inside the snapshot."""
    if path in seen:
        return []
    seen.add(path)
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith(("-r ", "--requirement ")):
            target = (path.parent / line.split(None, 1)[1].strip()).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ProjectError(f"{path.name}: {line!r} names a file outside the snapshot")
            lines += _requirement_file(target, root, seen)
            continue
        lines.append(line)
    return lines


def _literal_strings(node: ast.expr | None) -> list[str] | None:
    """The strings of a literal list or tuple of strings, or None if it is anything else."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for item in node.elts:
        if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
            return None
        values.append(item.value)
    return values


def _setup_py(path: Path, *, strict: bool = False) -> list[str]:
    """``install_requires``, ``tests_require`` and test extras, when ``setup()`` gives literals.

    ``strict``: anything else that could hide a requirement (``**`` arguments, extras that are
    not literal, no ``setup()`` call) is a ``ProjectError`` too.
    """
    try:
        tree = ast.parse(path.read_bytes())
    except (SyntaxError, ValueError) as exc:
        raise ProjectError(f"setup.py does not parse: {exc}") from None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "setup":
            return _setup_call(node, strict=strict)
    if strict:
        raise ProjectError("setup.py: no setup() call")
    return []


def _setup_call(node: ast.Call, *, strict: bool) -> list[str]:
    if strict and any(kw.arg is None for kw in node.keywords):
        raise ProjectError("setup.py: setup() takes ** arguments")
    keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    found: list[str] = []
    for key in ("install_requires", "tests_require"):
        if key in keywords:
            values = _literal_strings(keywords[key])
            if values is None:
                raise ProjectError(f"setup.py: {key} is not a literal list")
            found += values
    extras = keywords.get("extras_require")
    if strict and extras is not None and not isinstance(extras, ast.Dict):
        raise ProjectError("setup.py: extras_require is not a literal dict")
    if isinstance(extras, ast.Dict):
        for extra, value in zip(extras.keys, extras.values, strict=True):
            if isinstance(extra, ast.Constant) and extra.value in TEST_GROUPS:
                values = _literal_strings(value)
                if strict and values is None:
                    raise ProjectError(f"setup.py: the {extra.value} extra is not a literal")
                found += values or []
    return found


def _setup_cfg(path: Path) -> list[str]:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise ProjectError(f"setup.cfg cannot be read: {exc}") from None
    found = parser.get("options", "install_requires", fallback="").splitlines()
    for group in TEST_GROUPS:
        found += parser.get("options.extras_require", group, fallback="").splitlines()
    return [line for line in found if line.strip()]


def _pyproject_requirements(pyproject: dict[str, Any]) -> list[str]:
    project = pyproject.get("project", {})
    found = list(project.get("dependencies", []))
    extras = project.get("optional-dependencies", {})
    groups = pyproject.get("dependency-groups", {})
    for group in TEST_GROUPS:
        found += extras.get(group, [])
        found += [item for item in groups.get(group, []) if isinstance(item, str)]
    return found


def _declared(root: Path, pyproject: dict[str, Any]) -> tuple[str, ...] | None:
    """What the project's metadata declares, read as ``_pyproject_requirements``, ``_setup_py``
    and ``_setup_cfg`` read it; None if a requirement could hide from that reading: dependencies
    the build computes (``dynamic``), Poetry's own table (not PEP 508), a ``setup()`` that is not
    literal, a line that is not a requirement."""
    project = pyproject.get("project", {})
    poetry = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    dynamic = project.get("dynamic", [])
    if {"dependencies", "optional-dependencies"} & set(dynamic) or set(poetry) - {"python"}:
        return None
    found = _pyproject_requirements(pyproject)
    try:
        if (root / "setup.py").is_file():
            found += _setup_py(root / "setup.py", strict=True)
        if (root / "setup.cfg").is_file():
            found += _setup_cfg(root / "setup.cfg")
    except ProjectError:
        return None
    lines = [line.split(" #", 1)[0].strip() for line in found]
    lines = [line for line in lines if line and not line.startswith("#")]
    for line in lines:
        try:
            Requirement(line)
        except InvalidRequirement:
            return None  # "file: requirements.in", a pip option: not a requirement to compare
    return tuple(dict.fromkeys(lines))


def _kind(root: Path, pyproject: dict[str, Any]) -> ProjectKind:
    tool = pyproject.get("tool", {})
    if (root / "uv.lock").is_file():
        return "uv"
    if (root / "poetry.lock").is_file() or "poetry" in tool:
        return "poetry"
    if (root / "pdm.lock").is_file() or "pdm" in tool:
        return "pdm"
    if any((root / name).is_file() for name in REQUIREMENT_FILES):
        return "requirements"
    if (root / "setup.py").is_file() or (root / "setup.cfg").is_file():
        return "setuptools"
    return "unknown"


def inspect_project(root: Path, *, uv: str = "uv") -> Project:
    """The project at ``root``: its kind, requirements and build requirements."""
    pyproject_path = root / "pyproject.toml"
    pyproject = _toml(pyproject_path) if pyproject_path.is_file() else {}
    kind = _kind(root, pyproject)
    notes: list[str] = []
    source: str | None = None
    if kind == "uv":
        source, requirements = "uv.lock", _uv_export(root, uv)
    elif kind in ("poetry", "pdm") and (root / f"{kind}.lock").is_file():
        source = f"{kind}.lock"
        requirements = _lock_packages(root / source, kind)
    elif kind == "requirements":
        present = [name for name in REQUIREMENT_FILES if (root / name).is_file()]
        source = present[0]
        seen: set[Path] = set()
        lines = [line for name in present for line in _requirement_file(root / name, root, seen)]
        requirements = _checked(lines, ", ".join(present))
    else:
        declared = _pyproject_requirements(pyproject)
        if (root / "setup.py").is_file():
            declared += _setup_py(root / "setup.py")
        if (root / "setup.cfg").is_file():
            declared += _setup_cfg(root / "setup.cfg")
        requirements = _checked(declared, "the project's declared dependencies")
        if kind in ("poetry", "pdm"):
            notes.append(f"no {kind}.lock: the declared dependencies are resolved instead")
    names = {normalise(m.group(1)) for line in requirements if (m := _NAME.match(line))}
    if "pytest" not in names:
        requirements.append("pytest")
        notes.append("pytest added: the project does not declare it")
    build_system = pyproject.get("build-system", {})
    build = build_system.get("requires")
    installable = pyproject_path.is_file() or (root / "setup.py").is_file()
    build_requires = _checked(build if isinstance(build, list) else DEFAULT_BUILD_REQUIRES, "build")
    build_requires += EDITABLE_REQUIRES.get(build_system.get("build-backend", ""), ())
    return Project(
        kind=kind,
        root=root,
        source=source,
        lock_sha256=_sha256(root / source) if source else None,
        requirements=tuple(dict.fromkeys(requirements)),
        build_requires=tuple(build_requires) if installable else (),
        installable=installable,
        notes=tuple(notes),
        declared=_declared(root, pyproject),
        declared_file=next(
            (
                name
                for name in ("pyproject.toml", "setup.py", "setup.cfg")
                if (root / name).is_file()
            ),
            None,
        ),
    )
