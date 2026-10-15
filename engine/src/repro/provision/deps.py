"""Dependency differences between base and head, and lock drift (E05; ARCHITECTURE §4.5).

Two sources per side, compared by PEP 503 name:

- **What the project asks for**: the requirements D03 read for provisioning
  (``Project.requirements``): a lock's pins (``uv.lock``, ``poetry.lock``, ``pdm.lock``: source
  ``lockfile``) or the declared requirements (``pyproject.toml``, ``requirements*.txt``,
  ``setup.py`` / ``setup.cfg``: source ``declared``). A pinned requirement (``==``) is compared
  by version; any other by its text. When those come from a lock or requirement files, what the
  metadata declares is compared as well (``declared_changes``, F02): a dependency added to
  ``[project]`` alone is still a declared one. Metadata that cannot be read statically, with no
  lock, is said so (``undeclared``): what it adds would go unseen.
- **What was installed**: each side's environment, listed inside its own sandbox by its own
  interpreter (``-I -S``: distribution metadata is read, nothing is imported); the project's own
  editable install is left out (source ``installed``).

Versions are compared with ``packaging`` (PEP 440): ``upgraded``, ``downgraded``; a change that
is not between two versions (a specifier, a marker) is ``changed``.

**Lock drift.** For a locked project, a package installed at a version other than its pin.
Packages a pin's environment marker leaves out on this platform are not installed, so only
installed packages are compared.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from repro import __version__
from repro.ids import new_evidence_id
from repro.provision.project import Project, normalise

Source = Literal["lockfile", "declared", "installed"]
Change = Literal["added", "removed", "upgraded", "downgraded", "changed"]
LOCKED: Final = frozenset({"uv", "poetry", "pdm"})
_TEXT: Final = 100

#: Lists an environment's distributions as JSON ``[[name, version], ...]``, run with the
#: environment's interpreter and ``-I -S``, the environment's root as its argument: metadata
#: files are read, no distribution's code runs, and an editable install (``direct_url.json``
#: says so) is left out. Without ``site`` the interpreter does not know it is in a virtual
#: environment (``site`` sets ``sys.prefix`` from ``pyvenv.cfg``), so the root is given.
LIST_INSTALLED: Final = """
import importlib.metadata as metadata, json, sys
from pathlib import Path
root = Path(sys.argv[1])
paths = [root / "Lib" / "site-packages", *root.glob("lib/python*/site-packages")]
found = set()
for dist in metadata.distributions(path=[str(p) for p in paths if p.is_dir()]):
    try:
        editable = json.loads(dist.read_text("direct_url.json") or "{}")
        editable = editable.get("dir_info", {}).get("editable", False)
    except ValueError:
        editable = False
    name = dist.metadata["Name"]
    if name and not editable:
        found.add((name, dist.version))
print(json.dumps(sorted(found)))
"""


def project_requirements(project: Project) -> dict[str, str]:
    """Each requirement by name: its pinned version, or its specifier and marker as text."""
    return by_name(project.requirements)


def by_name(lines: Iterable[str]) -> dict[str, str]:
    """Requirement lines by PEP 503 name: the pinned version, or the specifier and marker."""
    found: dict[str, str] = {}
    for line in lines:
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue  # D03 accepted it for pip; what packaging cannot read is not compared
        found[normalise(requirement.name)] = _pinned(requirement) or _rest(requirement)
    return found


def _pinned(requirement: Requirement) -> str | None:
    specifiers = list(requirement.specifier)
    if (
        len(specifiers) == 1
        and specifiers[0].operator in ("==", "===")
        and requirement.marker is None
    ):
        version = specifiers[0].version
        return None if "*" in version else version
    return None


def _rest(requirement: Requirement) -> str:
    text = str(requirement.specifier) or "any version"
    if requirement.marker is not None:
        text += f"; {requirement.marker}"
    return text[:_TEXT]


def source_of(project: Project) -> Source:
    return "lockfile" if project.kind in LOCKED else "declared"


def parse_installed(output: bytes) -> dict[str, str] | None:
    """``LIST_INSTALLED``'s output as ``{name: version}``, or None if it is not that."""
    try:
        rows = json.loads(output.decode("utf-8", "replace").strip() or "null")
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    found: dict[str, str] = {}
    for row in rows:
        if isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) for x in row):  # noqa: PLR2004
            found[normalise(row[0])] = row[1][:_TEXT]
    return found


@dataclass(frozen=True, slots=True)
class DepChange:
    package: str
    change: Change
    base: str | None
    head: str | None
    source: Source
    file: str | None  # where the requirement is (head's file, else base's); None: installed

    def summary(self) -> str:
        if self.change == "added":
            what = f"added ({self.head})"
        elif self.change == "removed":
            what = f"removed (was {self.base})"
        else:
            what = f"{self.change}: {self.base} → {self.head}"
        where = {"lockfile": "in the lock", "declared": "as declared", "installed": "installed"}
        return f"{self.package} {what}, {where[self.source]}"[:1000]

    def evidence(self, run_id: str) -> dict[str, Any]:
        """The ``dep_diff`` evidence record (the writer adds ``seq``)."""
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "dep_diff",
            "targets": [{"file": self.file or "."}],
            "summary": self.summary(),
            "data": {
                "package": self.package,
                "change": self.change,
                "base": self.base,
                "head": self.head,
                "source": self.source,
            },
            "artifacts": [],
            "stability": "stable",
            "origin": "introduced",
            "produced_by": {"component": "repro.provision.deps", "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        """The ``diff.deps`` payload."""
        return {
            "evidence_id": evidence_id,
            "package": self.package,
            "change": self.change,
            "base_version": self.base,
            "head_version": self.head,
            "source": self.source,
        }


def compare(
    base: Mapping[str, str], head: Mapping[str, str], source: Source, file: str | None
) -> list[DepChange]:
    """What changed from ``base`` to ``head`` (``{name: version or specifier}``)."""
    found = []
    for name in sorted(base.keys() | head.keys()):
        before, after = base.get(name), head.get(name)
        if before == after:
            continue
        change: Change
        if before is None:
            change = "added"
        elif after is None:
            change = "removed"
        else:
            change = _direction(before, after)
        found.append(DepChange(name, change, before, after, source, file))
    return found


def declared_changes(base: Project, head: Project) -> list[DepChange]:
    """What the metadata declares, compared when a side's requirements come from a lock or
    requirement files (otherwise the requirements are the metadata, compared already)."""
    if base.source is None and head.source is None:
        return []
    if base.declared is None or head.declared is None:
        return []  # ``undeclared`` says so
    file = head.declared_file or base.declared_file
    return compare(by_name(base.declared), by_name(head.declared), "declared", file)


def undeclared(project: Project) -> bool:
    """Whether a dependency the project declares could go unseen: its metadata cannot be read
    statically and no lock pins what it resolves to."""
    return project.declared is None and source_of(project) != "lockfile"


def _direction(before: str, after: str) -> Change:
    try:
        old, new = Version(before), Version(after)
    except InvalidVersion:
        return "changed"
    return "upgraded" if new > old else "downgraded" if new < old else "changed"


@dataclass(frozen=True, slots=True)
class LockDrift:
    side: str
    package: str
    locked: str
    installed: str
    file: str | None

    def evidence(self, run_id: str) -> dict[str, Any]:
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "lock_drift",
            "targets": [{"file": self.file or "."}],
            "summary": (
                f"{self.side}: {self.package} is locked at {self.locked} and installed at "
                f"{self.installed}"
            )[:1000],
            "data": {
                "side": self.side,
                "package": self.package,
                "locked": self.locked,
                "installed": self.installed,
            },
            "artifacts": [],
            "stability": "stable",
            "origin": "n/a",
            "produced_by": {"component": "repro.provision.deps", "version": __version__},
        }


def lock_drift(side: str, project: Project, installed: Mapping[str, str]) -> list[LockDrift]:
    """Installed packages whose version is not the lock's pin (locked projects only)."""
    if project.kind not in LOCKED:
        return []
    found = []
    for name, wanted in sorted(project_requirements(project).items()):
        have = installed.get(name)
        if have is None or not _is_version(wanted) or _same_version(wanted, have):
            continue
        found.append(LockDrift(side, name, wanted, have, project.source))
    return found


def _is_version(text: str) -> bool:
    try:
        Version(text)
    except InvalidVersion:
        return False
    return True


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b
