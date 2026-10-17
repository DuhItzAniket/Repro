"""The memorisation probe (J04): file and 5-gram scores against the gold patch."""

from repro.agents.prompts import read_lock, read_prompt
from repro_bench import memo

GOLD = (
    "diff --git a/pkg/core.py b/pkg/core.py\n--- a/pkg/core.py\n+++ b/pkg/core.py\n"
    "@@ -1,2 +1,3 @@\n def f(x):\n-    return x\n+    if x is None:\n+        return 0\n"
    "diff --git a/pkg/util.py b/pkg/util.py\n--- a/pkg/util.py\n+++ b/pkg/util.py\n"
    "@@ -1 +1 @@\n-A = 1\n+A = 2\n"
)
RECORD = {
    "instance_id": "o__r-1",
    "repo": "o/r",
    "problem_statement": "f(None) fails",
    "patch": GOLD,
}


def test_the_added_code_and_its_5_grams() -> None:
    assert memo.added_code(GOLD) == "    if x is None:\n        return 0\nA = 2"
    assert ("if", "x", "is", "None", ":") in memo.grams(memo.added_code(GOLD))
    assert memo.grams("a b c") == set()


def test_a_model_that_remembers_the_fix_scores_high() -> None:
    answer = {"files": ["./pkg/core.py", "pkg/other.py"], "code": "if x is None:\n    return 0"}
    found = memo.score(RECORD, answer, (100, 20), "ok")
    assert found.file_hit
    assert found.file_recall == 0.5  # one of the two files
    assert found.ngram5 == 0.5  # 3 of the 6 added 5-grams; "A = 2" is not reproduced
    blank = memo.score(RECORD, None, (100, 0), "error")
    assert (blank.file_hit, blank.file_recall, blank.ngram5) == (False, 0.0, 0.0)


def test_the_model_sees_the_repository_and_issue_alone() -> None:
    request = memo.request("o/r", "f(None) fails", "m")
    assert request.prompt_version == "memorisation/1"
    assert (
        read_lock(memo.PROMPTS)["memorisation/1"]
        == read_prompt(memo.PROMPTS / "memorisation.md").sha256
    )
    assert "def f" not in request.prompt  # no code
    assert request.prompt.count("<untrusted_content") == 1
