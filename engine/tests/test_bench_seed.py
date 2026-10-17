"""Seeded plausible-but-wrong patches for S0 (J04): edits become a diff the repository takes."""

from pathlib import Path

import pytest

from gitrepo import Repo
from repro.gitops import Git
from repro_bench import seed, swe

BASE = {"pkg/core.py": "def f(x):\n    return x\n", "pkg/util.py": "A = 1\n"}
GOLD = {"pkg/core.py": "def f(x):\n    if x is None:\n        return 0\n    return x\n"}


@pytest.fixture
def task(tmp_path: Path) -> tuple[Repo, str, str, str]:
    """A repository at base, its gold head and the gold diff."""
    repo = Repo(tmp_path / "r")
    base = repo.commit(BASE)
    head = repo.commit(GOLD)
    return repo, base, head, repo.git("diff", base, head) + "\n"


def test_a_seed_is_the_gold_fix_with_one_edit(task: tuple[Repo, str, str, str]) -> None:
    repo, base, head, _ = task
    git = Git(repo.path)
    edit = {"path": "pkg/core.py", "find": "return 0", "replace": "return 1"}
    patch = seed.seeded_patch(git, base, head, [edit])
    seeded = swe.head_commit(git, swe.Sealed("o/r", base, patch, ""))
    assert git.run("show", f"{seeded}:pkg/core.py").decode() == GOLD["pkg/core.py"].replace(
        "return 0", "return 1"
    )
    assert git.run("show", f"{seeded}:pkg/util.py").decode() == BASE["pkg/util.py"]


def test_a_seed_may_touch_a_file_the_fix_does_not(task: tuple[Repo, str, str, str]) -> None:
    repo, base, head, _ = task
    git = Git(repo.path)
    patch = seed.seeded_patch(
        git, base, head, [{"path": "pkg/util.py", "find": "A = 1", "replace": "A = 2"}]
    )
    seeded = swe.head_commit(git, swe.Sealed("o/r", base, patch, ""))
    assert git.run("show", f"{seeded}:pkg/util.py").decode() == "A = 2\n"
    assert "diff --git a/pkg/util.py b/pkg/util.py" in patch
    assert "diff --git a/pkg/core.py b/pkg/core.py" in patch  # the fix itself is kept


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"path": "pkg/core.py", "find": "return", "replace": "yield"}, "occurs 2 times"),
        ({"path": "pkg/core.py", "find": "nowhere", "replace": "x"}, "occurs 0 times"),
        ({"path": "pkg/missing.py", "find": "x", "replace": "y"}, "not a file the fix leaves"),
        ({"path": "pkg/core.py", "find": "    if x is None:\n        return 0\n", "replace": ""},
         "undo the fix entirely"),
    ],
)  # fmt: skip
def test_an_edit_that_does_not_fit_is_dropped(
    task: tuple[Repo, str, str, str], edit: dict[str, str], message: str
) -> None:
    repo, base, head, _ = task
    with pytest.raises(seed.SeedError, match=message):
        seed.seeded_patch(Git(repo.path), base, head, [edit])


def test_the_model_is_asked_for_one_defect_class() -> None:
    request = seed.request("the issue", "diff --git a/x b/x\n", "edge_case", "m")
    assert request.prompt_version == "seed/1"
    assert request.prompt.startswith("The defect to introduce: edge_case")
    assert request.prompt.count("<untrusted_content") == 2
