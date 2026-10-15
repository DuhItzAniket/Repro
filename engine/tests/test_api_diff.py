"""The public API's breaking changes (E05): griffe statically, plus Repro's annotation check.

Roadmap E05: "griffe never imports target code (test with a module that raises on import)".
The repositories here are built with ``gitrepo``'s helpers; the ``api-break`` fixture runs end
to end in ``test_run_stage.py``.
"""

from pathlib import Path

from gitrepo import Repo
from repro.analysis.api import ApiDiff, api_diff
from repro.gitops import Git
from repro_events import models

RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"

TRAP = '''"""Importing this module is what the API diff must never do."""
from pathlib import Path

Path(__file__).with_name("IMPORTED").write_text("imported")
raise SystemExit("imported")

'''

BASE = {
    "pkg/__init__.py": "from pkg.core import greet\n",
    "pkg/core.py": TRAP
    + """
LIMIT: int = 3
VERSION = "1.0"


def greet(name, punctuation="!", *, loud=False):
    return name + punctuation


def area(width: int, height: int) -> int:
    return width * height


def _private(x):
    return x


class Box:
    size: int = 1

    def volume(self) -> int:
        return self.size**3

    def lid(self):
        return None


def gone():
    return 1
""",
    "pkg/sub/__init__.py": "",
    "pkg/sub/tools.py": "def helper(a):\n    return a\n",
    "tests/__init__.py": "",
    "tests/test_core.py": "def test_x():\n    pass\n",
    "conftest.py": "",
    "setup.py": "def setup(a):\n    pass\n",
}

HEAD = {
    **BASE,
    "pkg/core.py": TRAP
    + """
LIMIT: float = 3
VERSION = "2.0"


def greet(name, *, loud):
    return name


def area(width: int, height: int) -> float:
    return width * height


def _private(y, z):
    return y


class Box:
    size: str = 1

    def volume(self) -> int:
        return self.size**3

    def lid(self, closed):
        return closed
""",
    "tests/test_core.py": "def test_x(a):\n    pass\n",
    "setup.py": "def setup():\n    pass\n",
}


def diff_of(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> ApiDiff:
    repo = Repo(tmp_path / "repo")
    old = repo.commit(dict(base), "base")
    new = repo.commit(dict(head), "head", fresh=True)  # exactly head's files
    return api_diff(Git(repo.path), old, new, tmp_path / "api")


def test_breaking_changes_without_importing_anything(tmp_path: Path) -> None:
    found = diff_of(tmp_path, BASE, HEAD)
    assert not list(tmp_path.rglob("IMPORTED"))  # the trap module never ran
    assert found.packages == ("pkg",)  # tests, conftest.py and setup.py are not API
    assert found.problems == []
    listed = [(b.symbol, b.breakage, b.source) for b in found.breaks]
    assert listed == [
        ("pkg.core:Box.lid#0", "parameter_added_required", "griffe"),
        ("pkg.core:Box.size#0", "attribute_changed_type", "annotations"),
        ("pkg.core:LIMIT#0", "attribute_changed_type", "annotations"),
        ("pkg.core:VERSION#0", "attribute_changed_value", "griffe"),
        ("pkg.core:area#0", "return_changed_type", "annotations"),
        ("pkg.core:gone#0", "object_removed", "griffe"),
        ("pkg.core:greet#0", "parameter_changed_required", "griffe"),  # loud: no default now
        ("pkg.core:greet#0", "parameter_removed", "griffe"),
    ]
    (removed,) = [b for b in found.breaks if b.breakage == "parameter_removed"]
    assert removed.explanation == "pkg.core.greet: Parameter was removed (punctuation = '!')"
    assert removed.file == "pkg/core.py"
    (returns,) = [b for b in found.breaks if b.breakage == "return_changed_type"]
    assert returns.explanation == "pkg.core.area: Return annotation changed (int → float)"
    assert all(str(tmp_path) not in b.explanation for b in found.breaks)


def test_evidence_and_payload_match_the_schema(tmp_path: Path) -> None:
    found = diff_of(tmp_path, BASE, HEAD)
    for item in found.breaks:
        record = item.evidence(RUN_ID)
        record["seq"] = 1
        models.Evidence.model_validate(record)
        models.DiffApiPayload.model_validate(item.payload(record["id"]))


def test_a_removed_package_and_one_that_cannot_be_read(tmp_path: Path) -> None:
    base = {"alpha/__init__.py": "def a():\n    pass\n", "beta/__init__.py": "x = 1\n"}
    head = {"beta/__init__.py": "def broken(:\n"}
    found = diff_of(tmp_path, base, head)
    assert [(b.symbol, b.breakage) for b in found.breaks] == [
        ("alpha:<module>#0", "object_removed")
    ]
    assert [(side, package) for side, package, _ in found.problems] == [("head", "beta")]
    (item,) = found.missing()
    models.MissingRecordedPayload.model_validate(item)
    assert item["missing"]["reason"] == "unsupported_project"


def test_no_change_no_break(tmp_path: Path) -> None:
    assert diff_of(tmp_path, BASE, BASE).breaks == []
