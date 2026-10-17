"""S2's patch generation (J05): edits parsed and applied, and the two-call scaffold end to end
with a fake model."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro.agents.backend import AgentRequest, AgentResult, Usage
from repro.gitops import Git
from repro_bench import edits, generate, swe

BASE = {
    "pkg/__init__.py": "",
    "pkg/status.py": (
        "import http\n\n\ndef phrase(code):\n    return http.HTTPStatus(code).phrase\n"
    ),
    "pkg/other.py": "X = 1\n",
    "tests/test_status.py": "def test_x():\n    pass\n",
}
ANSWER = """I catch the ValueError that HTTPStatus raises for a code it does not know.

FILE: pkg/status.py
<<<<<<< SEARCH
    return http.HTTPStatus(code).phrase
=======
    try:
        return http.HTTPStatus(code).phrase
    except ValueError:
        return "Unknown Status"
>>>>>>> REPLACE
"""


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Git, str]:
    made = Repo(tmp_path / "r")
    return Git(made.path), made.commit(BASE)


def test_search_replace_blocks_are_read_in_order() -> None:
    found = edits.parse_blocks(
        ANSWER + "\nFILE: ./pkg/other.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n"
    )
    assert [edit.path for edit in found] == ["pkg/status.py", "pkg/other.py"]
    assert found[0].find == "    return http.HTTPStatus(code).phrase\n"
    assert found[0].replace.endswith('        return "Unknown Status"\n')
    assert edits.parse_blocks("no blocks here") == []


def test_edits_become_a_diff_the_repository_takes(repo: tuple[Git, str]) -> None:
    git, base = repo
    patch = edits.diff(git, base, edits.apply(git, base, edits.parse_blocks(ANSWER)))
    head = swe.head_commit(git, swe.Sealed("o/r", base, patch, ""))
    assert b'return "Unknown Status"' in git.run("show", f"{head}:pkg/status.py")
    with pytest.raises(edits.EditError, match="occurs 0 times"):
        edits.apply(git, base, [edits.Edit("pkg/status.py", "nowhere\n", "x\n")])
    with pytest.raises(edits.EditError, match="change nothing"):
        edits.diff(git, base, {"pkg/other.py": "X = 1\n"})


def test_the_files_offered_are_code_ranked_by_the_issue() -> None:
    files = ["pkg/a.py", "pkg/status.py", "tests/test_status.py", "README.md", "pkg/zeta.py"]
    assert generate.ranked_files(files, "HTTPStatus phrase in status codes")[:2] == [
        "pkg/status.py",
        "pkg/a.py",
    ]
    assert "tests/test_status.py" not in generate.ranked_files(files, "status")
    named = generate.located("- `pkg/status.py::phrase`\npkg/nowhere.py\npkg/a.py", files)
    assert named == [("pkg/status.py", "phrase"), ("pkg/a.py", None)]


def test_a_long_file_is_shown_by_its_outline_and_the_definitions_named() -> None:
    text = "def a():\n    return 1\n\n\n" + "".join(
        f"def f{n}():\n    return {n}\n\n\n" for n in range(600)
    )
    shown = generate.context(text, ["f7"])
    assert "(outline)" in shown
    assert "def f7():\n    return 7\n" in shown
    assert "def f8():\n    return 8\n" not in shown.split("(code)")[1]


class Model:
    """Answers the localize call, then the repair call."""

    def __init__(self, repair: str) -> None:
        self.repair = repair
        self.prompts: list[str] = []

    async def run(self, request: AgentRequest, on_progress: Any = None) -> AgentResult:
        self.prompts.append(request.prompt_version)
        text = (
            "pkg/status.py::phrase"
            if request.prompt_version == "repair_localize/1"
            else self.repair
        )
        return AgentResult("ok", text=text, usage=Usage(100, 50))


def test_the_scaffold_makes_a_patch_and_keeps_its_trajectory(repo: tuple[Git, str]) -> None:
    git, base = repo
    record = {"instance_id": "o__r-1", "repo": "o/r", "base_commit": base,
              "problem_statement": "phrase() fails for status 499"}  # fmt: skip
    model = Model(ANSWER)
    made = asyncio.run(generate.repair(record, git, model, "m"))
    assert model.prompts == ["repair_localize/1", "repair_edit/1"]
    assert made.patch is not None
    assert "diff --git a/pkg/status.py b/pkg/status.py" in made.patch
    assert made.summary.startswith("I catch the ValueError")
    assert [step["tokens"] for step in made.trajectory.steps] == [[100, 50], [100, 50]]
    broken = asyncio.run(generate.repair(record, git, Model("I changed nothing."), "m"))
    assert (broken.patch, broken.problem) == (None, "the answer has no search/replace block")
