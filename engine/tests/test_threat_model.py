"""THREAT_MODEL.md against the tests (H03): every threat has a test or a stated residual risk.

Section 4 lists the threats; section 7 says, for each, which tests meet its mitigation, as
``file.py::test_name`` (modules in ``engine/tests``), or why none can. This keeps the two in
step: a threat added without a row fails, and so does a row naming a test that was renamed or
removed.
"""

import ast
import re
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "docs" / "THREAT_MODEL.md"
TESTS = Path(__file__).resolve().parent
_ROW = re.compile(r"^\| (T\d+) \|")
_REFERENCE = re.compile(r"`([\w.]+\.py)::(\w+)`")
_NONE = {"", "—", "-"}


def section(title: str) -> list[str]:
    """The lines of the section whose heading starts with ``title``."""
    lines = MODEL.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {title}"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), None)
    return lines[start + 1 : end]


def rows(title: str) -> dict[str, list[str]]:
    """The section's table rows by threat ID, as their cells."""
    found: dict[str, list[str]] = {}
    for line in section(title):
        match = _ROW.match(line)
        if match is not None:
            found[match.group(1)] = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return found


@cache
def defined_in(module: str) -> frozenset[str]:
    """The module-level test functions of ``engine/tests/<module>``."""
    tree = ast.parse((TESTS / module).read_text(encoding="utf-8"))
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )


def test_every_threat_has_a_row_of_tests() -> None:
    assert set(rows("4.")) == set(rows("7."))


def test_each_threat_is_tested_or_says_why_not() -> None:
    for threat, cells in rows("7.").items():
        _, tested, untested = cells
        references = _REFERENCE.findall(tested)
        assert references or untested not in _NONE, f"{threat}: no test and no reason"
        for module, name in references:
            assert (TESTS / module).is_file(), f"{threat}: {module} does not exist"
            assert name in defined_in(module), f"{threat}: {module}::{name} does not exist"
