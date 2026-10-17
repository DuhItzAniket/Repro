"""The baselines' rules (J03): what each system is given and how its answer is mapped.

Containers and models are faked; the live runs (SWE-rebench ``pypa__twine-1309``) are in the
phase record.
"""

import asyncio
import io
import json
import tarfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro.agents.backend import AgentRequest, AgentResult, Usage
from repro.agents.reviewer import REVIEW_BUDGET
from repro.gitops import Git
from repro_bench import baselines, swe, truth
from repro_bench.truth import ERROR, FAILED, PASSED, SKIPPED, ContainerRun, Environment

HIDDEN = "tests/test_hidden_canary.py"
SEALED = swe.Sealed("o/r", "a" * 40, "diff --git a/m.py b/m.py\n+x\n", "Issue title\n\nbody")


def run_of(statuses: dict[str, str], *, applied: bool = True, problem: str = "") -> ContainerRun:
    return ContainerRun(applied, ((statuses, 0),) if not problem else (), 0.1, problem)


@pytest.mark.parametrize(
    ("command", "generic"),
    [
        (f"pytest --no-header -rA --tb=line -p no:cacheprovider {HIDDEN}",
         "pytest --no-header -rA --tb=line -p no:cacheprovider"),
        (f"pytest -rA {HIDDEN}::test_one tests/other.py --deselect tests/x.py::slow",
         "pytest -rA --deselect tests/x.py::slow"),
        ("python -m pytest -rA -k 'not network' src/pkg", "python -m pytest -rA -k 'not network'"),
    ],
)  # fmt: skip
def test_ci_runs_the_whole_suite_and_never_names_the_hidden_tests(
    command: str, generic: str
) -> None:
    assert baselines.generic_command(command) == generic
    assert HIDDEN not in generic


def test_ci_resets_nothing_and_applies_only_the_agents_diff() -> None:
    text = truth.script(Environment("img", "a" * 40), ["diff"], "pytest -rA")
    assert "git checkout" not in text
    assert text.count("base64 -d") == 1


@pytest.mark.parametrize(
    ("base", "head", "status"),
    [
        ({"t::a": PASSED}, {"t::a": FAILED}, "FLAGGED"),  # a regression
        ({"t::a": PASSED}, {"t::a": PASSED, "t::new": ERROR}, "FLAGGED"),  # a new test fails
        ({"t::a": FAILED}, {"t::a": FAILED}, "VERIFIED"),  # failing before too
        ({"t::a": PASSED}, {"t::a": SKIPPED}, "VERIFIED"),
        ({"t::a": PASSED, "t::gone": PASSED}, {"t::a": PASSED}, "VERIFIED"),  # removed: no failure
    ],
)
def test_ci_flags_regressions_and_failing_new_tests(
    base: dict[str, str], head: dict[str, str], status: str
) -> None:
    assert baselines.ci_answer(run_of(base), run_of(head)).status == status


def test_ci_without_a_valid_run_cannot_tell_and_a_diff_that_does_not_apply_is_flagged() -> None:
    env = Environment("img", "a" * 40)

    def broken(target: Any, patches: Sequence[str], command: str, repeat: int = 1) -> ContainerRun:
        return run_of({}, problem="no test result")

    assert baselines.ci_only(env, "pytest", "d", run=broken).status == "UNVERIFIABLE"

    def refused(target: Any, patches: Sequence[str], command: str, repeat: int = 1) -> ContainerRun:
        return run_of({"t::a": PASSED}, applied=not patches, problem="")

    assert baselines.ci_only(env, "pytest", "d", run=refused).status == "FLAGGED"


@pytest.mark.parametrize(
    ("result", "status"),
    [
        (AgentResult("ok", {"verdict": "accept", "problems": [], "rationale": "r"}), "VERIFIED"),
        (AgentResult("ok", {"verdict": "reject", "problems": ["p"], "rationale": "r"}), "FLAGGED"),
        (AgentResult("ok", {"verdict": "cannot_tell", "problems": [], "rationale": ""}),
         "UNVERIFIABLE"),
        (AgentResult("max_turns", detail="error_max_turns"), "UNVERIFIABLE"),
    ],
)  # fmt: skip
def test_a_reviewers_verdict_maps_to_a_status(result: AgentResult, status: str) -> None:
    answer = baselines.llm_answer(result)
    assert answer.status == status
    assert answer.detail.get("system_error", False) is (result.outcome != "ok")


class Flaky:
    """A model whose first calls Groq refuses."""

    def __init__(self, refusals: int, detail: str) -> None:
        self.refusals, self.detail, self.calls = refusals, detail, 0

    async def run(self, request: AgentRequest, on_progress: Any = None) -> AgentResult:
        self.calls += 1
        if self.calls <= self.refusals:
            return AgentResult("error", detail=self.detail)
        return AgentResult("ok", {"verdict": "accept", "problems": [], "rationale": ""},
                           usage=Usage(10, 5))  # fmt: skip


@pytest.mark.parametrize(
    ("refusals", "detail", "calls", "outcome"),
    [
        (2, "HTTP 400: Tool call validation failed: parameters for tool x", 3, "ok"),
        (1, "HTTP 400: attempted to call tool 'grep_repo<|channel|>commentary'", 2, "ok"),
        (3, "HTTP 400: The model generated output that could not be parsed.", 3, "error"),
        (1, "HTTP 413: Request too large", 1, "error"),  # not the model's mistake: no retry
    ],
)
def test_a_refused_tool_call_is_made_again_twice_at_most(
    refusals: int, detail: str, calls: int, outcome: str
) -> None:
    model = Flaky(refusals, detail)
    result, made = asyncio.run(baselines.ask(model, baselines.diff_request(SEALED, "m")))
    assert (made, result.outcome) == (calls, outcome)


def test_the_diff_reviewer_gets_the_claim_and_diff_with_repros_budget() -> None:
    request = baselines.diff_request(SEALED, "m")
    assert request.prompt_version == "baseline_diff/1"
    assert request.budget == REVIEW_BUDGET
    assert request.effort == "high"
    assert not request.tools
    assert request.prompt.count("<untrusted_content") == 2
    assert SEALED.claim in request.prompt


@pytest.fixture
def tools(tmp_path: Path) -> baselines.RepoTools:
    repo = Repo(tmp_path / "r")
    base = repo.commit({"pkg/m.py": "".join(f"x{n} = {n}\n" for n in range(200)),
                        "pkg/old.py": "OLD = 1\n"})  # fmt: skip
    head = repo.commit({"pkg/m.py": "x0 = 'changed'\n", "pkg/old.py": None})
    return baselines.RepoTools(Git(repo.path), base, head)


def test_the_static_reviewers_tools_read_either_side(tools: baselines.RepoTools) -> None:
    async def ask(tool: str, given: dict[str, Any]) -> str:
        return await {t.name: t for t in tools.tools()}[tool].handler(given)

    def call(tool: str, **given: Any) -> str:
        return asyncio.run(ask(tool, given))

    assert "pkg/old.py" in call("list_repo_files", side="base", prefix="pkg/")
    assert "pkg/old.py" not in call("list_repo_files", side="head", prefix="pkg/")
    shown = call("read_repo_file", side="base", path="pkg/m.py", line_start=5, line_end=500)
    assert "    5  x4 = 4" in shown
    assert f"   {4 + baselines.READ_MAX}  " in shown  # 80 lines from line 5, no more
    assert "x84 = 84" not in shown
    assert "(the file has 200 lines)" in shown
    assert "x0 = 'changed'" in call("read_repo_file", path="pkg/m.py")  # head by default
    assert "pkg/m.py:1:x0 = 'changed'" in call("grep_repo", side="head", query="changed")
    assert "is not a file at head" in call("read_repo_file", side="head", path="pkg/old.py")


def test_the_static_reviewers_tools_have_names_of_their_own() -> None:
    names = {tool.name for tool in baselines.RepoTools(None, "a", "b").tools()}  # type: ignore[arg-type]
    assert names == {"list_repo_files", "read_repo_file", "grep_repo"}
    assert "search" not in names  # gpt-oss's browser tool has one, with other arguments


@pytest.mark.parametrize(
    ("review", "status"),
    [
        ({"review": {"key_issues_to_review": [{"issue_header": "Bug"}],
                     "security_concerns": "No"}}, "FLAGGED"),
        ({"review": {"key_issues_to_review": [], "security_concerns": "SQL injection: ..."}},
         "FLAGGED"),
        ({"review": {"key_issues_to_review": [], "security_concerns": "No\n"}}, "VERIFIED"),
    ],
)  # fmt: skip
def test_pr_agents_review_maps_to_a_status(review: dict[str, Any], status: str) -> None:
    assert baselines.pr_agent_answer(json.dumps(review)).status == status


def test_no_review_is_unverifiable() -> None:
    answer = baselines.pr_agent_answer("Traceback ... litellm.RateLimitError")
    assert answer.status == "UNVERIFIABLE"
    assert answer.detail["system_error"] is True


def test_pr_agent_gets_the_base_tree_unconverted_with_the_claim_as_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = Repo(tmp_path / "r")
    base = repo.commit({"m.py": "a = 1\nb = 2\n"})
    # A machine whose git converts line endings on the way out (Windows' core.autocrlf).
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    sealed = swe.Sealed("o/r", base, "diff", "The title\n\nThe claim")
    with tarfile.open(fileobj=io.BytesIO(baselines._bundle(Git(repo.path), sealed))) as outer:
        names = outer.getnames()
        claim = outer.extractfile("claim.txt").read().decode()  # type: ignore[union-attr]
        tree = outer.extractfile("tree.tar").read()  # type: ignore[union-attr]
    assert names == ["tree.tar", "change.diff", "claim.txt", "run.sh"]
    assert claim == "The title\n\nThe title\n\nThe claim"
    with tarfile.open(fileobj=io.BytesIO(tree)) as inner:
        assert inner.extractfile("m.py").read() == b"a = 1\nb = 2\n"  # type: ignore[union-attr]


def test_pr_agent_without_a_key_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    answer = baselines.pr_agent(None, SEALED, "m")  # type: ignore[arg-type]
    assert (answer.status, answer.reason) == ("UNVERIFIABLE", "GROQ_API_KEY is not set")
    settings = baselines.pr_agent_env("openai/gpt-oss-120b")
    assert settings["CONFIG__GIT_PROVIDER"] == "local"
    assert settings["CONFIG__MODEL"] == "groq/openai/gpt-oss-120b"
