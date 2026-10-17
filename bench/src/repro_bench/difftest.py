"""Differential tests written for a task, for tier B (J02).

PatchDiff asks a model for tests that exercise where a candidate patch and the gold patch may
behave differently, then runs them on both, keeping only tests stable across reruns [Wang,
Pradel, Liu, "Are 'Solved Issues' in SWE-bench Really Solved Correctly?", ICSE 2026; research/06
§4]. Here the model gets the issue, the gold patch, the tests the maintainers added and the
candidate, and answers with one pytest module; ``truth.differential`` runs it.

The prompt is versioned and locked like the engine's (``prompts/difftest.md``, ``difftest/1``),
so a result names the text that produced its tests. The module is model-written code: it runs
only in the task's container, with no network (``truth.run_tests``). These tests are part of
the ground truth: the gold patch is the oracle here, and no system under evaluation sees them.
"""

import ast
import posixpath
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from repro.agents.backend import AgentRequest, AgentResult, Budget, LLMBackend
from repro.agents.prompts import Prompt, load_prompt
from repro.agents.untrusted import block
from repro_bench.truth import Oracle, OracleError

PROMPTS: Final = Path(__file__).parent / "prompts"
BUDGET: Final = Budget(max_turns=2, max_budget_usd=0.25, timeout_s=600.0)
MODULE_NAME: Final = "test_repro_difftest.py"
SCHEMA: Final = {
    "type": "object",
    "properties": {"module": {"type": "string"}},
    "required": ["module"],
    "additionalProperties": False,
}


def prompt() -> Prompt:
    return load_prompt("difftest", PROMPTS)


def request(oracle: Oracle, problem_statement: str, candidate: str, model: str) -> AgentRequest:
    shown = prompt()
    body = "\n\n".join(
        [
            "The issue:\n" + block("issue", problem_statement),
            "The reference fix:\n" + block("diff", oracle.gold_patch, side="reference"),
            "The tests the maintainers added with it:\n" + block("diff", oracle.test_patch),
            "The candidate fix:\n" + block("diff", candidate, side="candidate"),
        ]
    )
    return AgentRequest(
        role="probe",
        system_prompt=shown.text,
        prompt=body,
        model=model,
        prompt_version=shown.prompt_version,
        budget=BUDGET,
        output_schema=SCHEMA,
        effort="medium",
    )


def module_path(oracle: Oracle) -> str:
    """Beside the maintainers' first test file, so the project's test configuration applies."""
    if not oracle.test_files:
        raise OracleError(f"{oracle.instance_id}: the test patch adds no test file")
    return posixpath.join(posixpath.dirname(oracle.test_files[0]), MODULE_NAME)


def as_patch(path: str, source: str) -> str:
    """A diff that adds ``source`` as the new file ``path``."""
    lines = source.splitlines()
    added = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{added}"
    )


def module_from(result: AgentResult) -> str:
    """The model's module, checked to be Python with at least one test (raises
    ``OracleError``)."""
    answer: Mapping[str, Any] | None = result.structured
    if result.outcome != "ok" or not isinstance(answer, Mapping):
        raise OracleError(f"no tests were written: {result.outcome} {result.detail}".strip())
    source = str(answer.get("module", "")).strip()
    source = source.removeprefix("```python").removeprefix("```").removesuffix("```").strip()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise OracleError(
            f"the written tests are not Python: {exc.msg} (line {exc.lineno})"
        ) from None
    tests = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")
    ]
    if not tests:
        raise OracleError("the written module has no test")
    return source + "\n"


async def write_tests(
    oracle: Oracle, problem_statement: str, candidate: str, backend: LLMBackend, model: str
) -> tuple[str, AgentResult]:
    """The tests as a patch adding one module, and the call's result (its cost)."""
    result = await backend.run(request(oracle, problem_statement, candidate, model))
    return as_patch(module_path(oracle), module_from(result)), result
