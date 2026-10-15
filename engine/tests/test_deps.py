"""Dependency differences and lock drift (E05). The ``new-dep`` fixture runs end to end in
``test_run_stage.py``; here the parts are tested on their own."""

import subprocess
import sys
from pathlib import Path

import pytest

from repro.provision import deps
from repro.provision.project import Project
from repro_events import models

RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"


def project(kind: str, *requirements: str) -> Project:
    return Project(kind, Path(), "uv.lock" if kind == "uv" else None, None, requirements, (), True)  # type: ignore[arg-type]


def test_requirements_by_name_pinned_or_as_written() -> None:
    found = deps.project_requirements(
        project(
            "unknown",
            "Six==1.17.0",
            "requests>=2.30,<3",
            "colorama==0.4.6; sys_platform == 'win32'",
            "attrs",
            "not a requirement ===",
        )
    )
    assert found == {
        "six": "1.17.0",
        "requests": "<3,>=2.30",
        "colorama": '==0.4.6; sys_platform == "win32"',  # a marker: compared as text
        "attrs": "any version",
    }
    assert deps.source_of(project("uv")) == "lockfile"
    assert deps.source_of(project("requirements")) == "declared"


def test_each_kind_of_change() -> None:
    base = {"a": "1.0", "b": "2.0", "c": "1.5", "d": ">=1", "e": "3"}
    head = {"a": "1.2", "b": "1.9", "c": "1.5", "d": ">=2", "f": "0.1"}
    found = deps.compare(base, head, "lockfile", "uv.lock")
    assert [(c.package, c.change, c.base, c.head) for c in found] == [
        ("a", "upgraded", "1.0", "1.2"),
        ("b", "downgraded", "2.0", "1.9"),
        ("d", "changed", ">=1", ">=2"),
        ("e", "removed", "3", None),
        ("f", "added", None, "0.1"),
    ]
    assert found[0].summary() == "a upgraded: 1.0 → 1.2, in the lock"
    for change in found:
        record = change.evidence(RUN_ID)
        record["seq"] = 1
        models.Evidence.model_validate(record)
        models.DiffDepsPayload.model_validate(change.payload(record["id"]))


@pytest.mark.parametrize(
    "output",
    [b"", b"not json", b'{"a": 1}', b"[[1, 2]]"],
    ids=["empty", "text", "object", "numbers"],
)
def test_unreadable_listings(output: bytes) -> None:
    found = deps.parse_installed(output)
    assert found is None or found == {}


def test_the_listing_script_on_this_environment() -> None:
    """Run as Side.installed runs it: this venv's interpreter, -I -S, the venv's root. The
    workspace's own packages are editable installs and are left out."""
    root = Path(sys.prefix)
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-c", deps.LIST_INSTALLED, str(root)],
        capture_output=True,
        check=True,
        timeout=60,
    )
    found = deps.parse_installed(done.stdout)
    assert found is not None
    assert "griffelib" in found
    assert "packaging" in found
    assert "repro-engine" not in found  # editable


def test_lock_drift() -> None:
    locked = project("uv", "six==1.17.0", "attrs==24.2.0", "colorama==0.4.6")
    drift = deps.lock_drift("head", locked, {"six": "1.16.0", "attrs": "24.2", "pytest": "9.1.1"})
    assert [(d.package, d.locked, d.installed) for d in drift] == [("six", "1.17.0", "1.16.0")]
    record = drift[0].evidence(RUN_ID)
    record["seq"] = 1
    models.Evidence.model_validate(record)
    assert deps.lock_drift("head", project("unknown", "six==1.17.0"), {"six": "1.0"}) == []
