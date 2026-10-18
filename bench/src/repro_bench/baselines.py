"""The systems Repro is compared with (J03; ``docs/paper/EVALUATION_PROTOCOL.md`` §5).

Each gets J01's sealed input and nothing else: the repository at base, the agent's diff and the
claim (the problem statement and the agent's summary). Each answers VERIFIED, FLAGGED or
UNVERIFIABLE by a rule fixed here before any S2 data exists (``docs/paper/BASELINES.md``):

- **B0, CI-only.** The project's own tests, those the patch adds included, on base and on head,
  in the task's image. FLAGGED when a test that passes on base fails on head, or a test the
  patch adds fails; VERIFIED otherwise; UNVERIFIABLE when either side gives no valid result. The
  command is the task's test command with every file argument removed, so the hidden tests'
  file names never reach it (J01's contract). With ``--manifest`` it runs in the image the
  manifest pinned at sealing; with ``--image-budget-gb``, images are pulled as tasks come and
  trimmed to the budget (``repro_bench.images``).
- **B1, diff-only LLM reviewer.** The claim and the diff, one call, the same model, budget and
  effort as Repro's reviewer agent (``REVIEW_BUDGET``, ``high``). ``accept`` is VERIFIED,
  ``reject`` FLAGGED, ``cannot_tell`` UNVERIFIABLE; a call that fails is UNVERIFIABLE and
  counted as the system's failure.
- **B2, agentic static LLM reviewer.** B1's inputs and read-only tools over the repository at
  base and at head (list files, read a file, search), no execution; the same dollar budget as
  Repro's reviewer, more turns to use the tools.
- **B3, PR-Agent** v0.48.0 (``The-PR-Agent/pr-agent`` at ``981344be``, MIT, checked
  2026-10-18), as shipped, with the same model through its LiteLLM support, run on a local
  repository whose head commit's message is the claim (its local git provider: the PR's
  description is the commits' messages [``pr_agent/git_providers/local_git_provider.py`` at
  v0.48.0]). Its review JSON decides: FLAGGED when it lists a key issue or a security concern,
  VERIFIED when it lists neither, UNVERIFIABLE when there is no review.

Testora (B4 in the protocol) is not run: see ``docs/paper/BASELINES.md``.
"""

import argparse
import asyncio
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal

from repro.agents import CassetteBackend, LLMBackend
from repro.agents.backend import AgentRequest, AgentResult, Budget, ReproTool
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.prompts import load_prompt
from repro.agents.reviewer import REVIEW_BUDGET
from repro.agents.setup import GROQ_MODEL
from repro.agents.untrusted import block
from repro.gitops import Git, GitError
from repro.gitops.snapshot import read_blobs, regular_files
from repro_bench import images as task_images
from repro_bench import swe, truth
from repro_bench.truth import ERROR, FAILED, PASSED, XFAIL, ContainerRun, Environment

Status = Literal["VERIFIED", "FLAGGED", "UNVERIFIABLE"]
PROMPTS: Final = Path(__file__).parent / "prompts"
VERDICTS: Final[Mapping[str, Status]] = {
    "accept": "VERIFIED",
    "reject": "FLAGGED",
    "cannot_tell": "UNVERIFIABLE",
}
SCHEMA: Final = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "problems": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "problems", "rationale"],
    "additionalProperties": False,
}
#: B2: Repro's reviewer's dollar budget, with turns to use the tools. On Groq's free tier each
#: turn may wait out the minute's 8,000 tokens, so ten turns need more than Repro's reviewer's
#: 600 s of wall-clock time (J03 measured one time out at 600 s): 1,800 s.
STATIC_BUDGET: Final = Budget(
    max_turns=10, max_budget_usd=REVIEW_BUDGET.max_budget_usd, timeout_s=1800.0
)
#: What one tool call returns at most. On Groq's free tier a request, with its 3,000-token
#: answer cap, must fit 8,000 tokens (J03 measured a 9,306-token request refused), so B2 reads
#: in small pieces; Repro's own agents work under the same cap.
TOOL_OUTPUT_MAX: Final = 3_000
LIST_MAX: Final = 120
READ_MAX: Final = 80
SEARCH_MAX: Final = 25
#: A call Groq refuses because the model named a tool or an argument wrongly is made again,
#: twice at most, as fixed before S2 (``docs/paper/BASELINES.md``).
RETRIES: Final = 2


@dataclass(frozen=True)
class Answer:
    """A system's answer for one task, by the system's rule."""

    status: Status
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)
    tokens: tuple[int, int] | None = None


# -- B0: CI-only ---------------------------------------------------------------------------------

#: pytest options that take the next argument as their value: it is kept with them.
_VALUE_OPTIONS: Final = frozenset(
    {
        "-p",
        "-k",
        "-m",
        "-c",
        "-o",
        "-n",
        "-W",
        "-x",
        "--tb",
        "--color",
        "--rootdir",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--timeout",
        "--maxfail",
        "--durations",
        "--confcutdir",
        "--basetemp",
        "--import-mode",
        "-r",
    }
)


def generic_command(test_cmd: str) -> str:
    """The task's test command without its file and test arguments: the project's whole suite,
    and nothing that names the hidden tests."""
    tokens = shlex.split(test_cmd)
    kept: list[str] = []
    for index, token in enumerate(tokens):
        value_of_option = index > 0 and tokens[index - 1] in _VALUE_OPTIONS
        path_like = "/" in token or "::" in token or token.endswith(".py")
        if path_like and not token.startswith("-") and not value_of_option:
            continue
        kept.append(token)
    return shlex.join(kept)


def environment(record: Mapping[str, Any]) -> tuple[Environment, str]:
    """B0's environment from an instance: its image, base commit and generic test command."""
    oracle = truth.Oracle.from_record(record)
    return Environment(oracle.image, oracle.base_commit), generic_command(oracle.test_cmd)


def ci_only(env: Environment, command: str, diff: str, *, run: Any = truth.run_tests) -> Answer:
    base = run(env, [], command)
    if not base.valid:
        return Answer("UNVERIFIABLE", f"the suite gave no valid result on base: {base.problem}")
    head = run(env, [diff], command)
    if not head.applied:
        return Answer("FLAGGED", f"the change does not apply: {head.problem}")
    if not head.valid:
        return Answer("UNVERIFIABLE", f"the suite gave no valid result on head: {head.problem}")
    return ci_answer(base, head)


def ci_answer(base: ContainerRun, head: ContainerRun) -> Answer:
    before, after = base.statuses, head.statuses
    failing = {t for t, s in after.items() if s in (FAILED, ERROR)}
    regressions = sorted(t for t in failing if before.get(t) in (PASSED, XFAIL))
    new_failing = sorted(t for t in failing if t not in before)
    detail = {
        "tests_base": len(before),
        "tests_head": len(after),
        "regressions": regressions,
        "new_tests_failing": new_failing,
    }
    if regressions or new_failing:
        return Answer(
            "FLAGGED", "a test fails on head that passed on base, or a new test fails", detail
        )
    return Answer("VERIFIED", "no test that passed on base fails, and no new test fails", detail)


# -- B1 and B2: LLM reviewers ---------------------------------------------------------------------


def _shown(sealed: swe.Sealed) -> str:
    return (
        f"The issue and the author's summary of the change:\n{block('claim', sealed.claim)}\n\n"
        f"The change:\n{block('diff', sealed.diff)}"
    )


def diff_request(sealed: swe.Sealed, model: str) -> AgentRequest:
    prompt = load_prompt("baseline_diff", PROMPTS)
    return AgentRequest(
        role="review",
        system_prompt=prompt.text,
        prompt=_shown(sealed),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=REVIEW_BUDGET,
        output_schema=SCHEMA,
        effort="high",
    )


class RepoTools:
    """Read-only tools over the repository at base and at head, read from git objects alone."""

    def __init__(self, git: Git, base: str, head: str) -> None:
        self.git = git
        self.commits = {"base": base, "head": head}
        self._files: dict[str, dict[str, str]] = {}

    def files(self, side: str) -> dict[str, str]:
        if side not in self._files:
            self._files[side] = regular_files(self.git, self.commits[side])
        return self._files[side]

    async def list_files(self, given: Mapping[str, Any]) -> str:
        side = _side(given)
        prefix = str(_first(given, "prefix", "path", "directory", default=""))
        names = sorted(name for name in self.files(side) if name.startswith(prefix))
        more = f"\n... and {len(names) - LIST_MAX} more" if len(names) > LIST_MAX else ""
        shown = "\n".join(names[:LIST_MAX]) + more
        return block("files", shown[:TOOL_OUTPUT_MAX] or "no file", side=side)

    async def read_file(self, given: Mapping[str, Any]) -> str:
        side, path = _side(given), str(_first(given, "path", "file", default=""))
        sha = self.files(side).get(path)
        if sha is None:
            return f"{path} is not a file at {side}"
        lines = read_blobs(self.git, [sha])[sha].decode("utf-8", "replace").splitlines()
        start = max(1, _int(_first(given, "start_line", "line_start", "start", default=1), 1))
        end = _int(_first(given, "end_line", "line_end", "end", default=start), start)
        end = min(len(lines), max(start, end), start + READ_MAX - 1)
        numbered = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
        more = f"\n(the file has {len(lines)} lines)" if end < len(lines) else ""
        return block("file", numbered[:TOOL_OUTPUT_MAX] + more, side=side, path=_attr(path))

    async def search(self, given: Mapping[str, Any]) -> str:
        side = _side(given)
        text = str(_first(given, "pattern", "text", "query", default=""))
        if not text.strip():
            return "give the pattern to look for"
        try:
            found = self.git.run(
                "grep", "-n", "-I", "-F", "-e", text, self.commits[side], check=False
            )
        except GitError as exc:
            return f"the search failed: {exc}"
        hits = found.decode("utf-8", "replace").splitlines()
        hits = [hit.split(":", 1)[1] if ":" in hit else hit for hit in hits]  # drop "<sha>:"
        more = f"\n... and {len(hits) - SEARCH_MAX} more" if len(hits) > SEARCH_MAX else ""
        shown = "\n".join(hit[:200] for hit in hits[:SEARCH_MAX]) + more
        return block("search", shown[:TOOL_OUTPUT_MAX] or "no match", side=side)

    def tools(self) -> tuple[ReproTool, ...]:
        """Names of their own: gpt-oss was trained with a browser tool whose ``search`` takes
        other arguments, and Groq refuses a call that does not match the schema. The schemas
        require little and allow other names for an argument (``line_start`` for
        ``start_line``), which the handlers read (J03)."""
        side = {"type": "string", "enum": ["base", "head"], "description": "base or head"}
        text = {"type": "string"}
        line = {"type": "integer"}

        def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "object", "properties": {"side": side, **properties},
                    "required": required}  # fmt: skip

        return (
            ReproTool(
                "list_repo_files",
                "Lists the repository's files at base or head (side) whose path starts with "
                f'prefix ("" for all), {LIST_MAX} at most.',
                schema({"prefix": text}, []),
                self.list_files,
            ),
            ReproTool(
                "read_repo_file",
                "Shows a file's lines at base or head (side), from start_line to end_line, "
                f"{READ_MAX} lines at most a call.",
                schema({"path": text, "start_line": line, "end_line": line}, ["path"]),
                self.read_file,
            ),
            ReproTool(
                "grep_repo",
                "Lists the lines at base or head (side) that contain pattern (plain text, not "
                f"a regular expression), with their file and line number, {SEARCH_MAX} at most.",
                schema({"pattern": text}, ["pattern"]),
                self.search,
            ),
        )


def _first(given: Mapping[str, Any], *names: str, default: Any) -> Any:
    return next((given[name] for name in names if given.get(name) not in (None, "")), default)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _side(given: Mapping[str, Any]) -> str:
    return "base" if str(given.get("side", "head")).lower() == "base" else "head"


def _attr(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_./+-]", "_", text)[:200]


def static_request(sealed: swe.Sealed, tools: RepoTools, model: str) -> AgentRequest:
    prompt = load_prompt("baseline_static", PROMPTS)
    return AgentRequest(
        role="review",
        system_prompt=prompt.text,
        prompt=_shown(sealed),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=STATIC_BUDGET,
        tools=tools.tools(),
        output_schema=SCHEMA,
        effort="high",
    )


def _refused_call(result: AgentResult) -> bool:
    """Groq refused the request over output the model got wrong: a tool call (a name or an
    argument), or text it could not parse."""
    said = result.detail.lower()
    return result.outcome == "error" and (
        "tool call validation failed" in said
        or "attempted to call tool" in said
        or "could not be parsed" in said
    )


async def ask(backend: LLMBackend, request: AgentRequest) -> tuple[AgentResult, int]:
    """The call, made again up to ``RETRIES`` times when Groq refused a malformed tool call;
    the result and how many calls it took."""
    result = await backend.run(request)
    calls = 1
    while _refused_call(result) and calls <= RETRIES:
        result = await backend.run(request)
        calls += 1
    return result, calls


def llm_answer(result: AgentResult, calls: int = 1) -> Answer:
    tokens = (result.usage.input_tokens, result.usage.output_tokens)
    answer = result.structured
    if result.outcome != "ok" or not isinstance(answer, Mapping):
        return Answer(
            "UNVERIFIABLE",
            f"the system failed: {result.outcome} {result.detail}".strip(),
            {"system_error": True},
            tokens,
        )
    verdict = str(answer.get("verdict"))
    detail = {
        "verdict": verdict,
        "problems": list(answer.get("problems", [])),
        "rationale": str(answer.get("rationale", "")),
        "turns": result.turns,
        "tool_calls": [name for name, _ in result.tool_calls],
        "calls": calls,
    }
    return Answer(
        VERDICTS.get(verdict, "UNVERIFIABLE"), f"the reviewer answered {verdict}", detail, tokens
    )


# -- B3: PR-Agent ---------------------------------------------------------------------------------

PR_AGENT_VERSION: Final = "0.48.0"
PR_AGENT_COMMIT: Final = "981344be2755e303df501e18e3f60b848a188a80"
PR_AGENT_IMAGE: Final = f"repro-bench-pr-agent:{PR_AGENT_VERSION}"
#: Python 3.12 (PR-Agent needs >= 3.12), pinned by digest (pulled 2026-10-18).
PYTHON_IMAGE: Final = (
    "python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
)
DOCKERFILE: Final = f"""FROM {PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pr-agent=={PR_AGENT_VERSION}
"""
RUN_SH: Final = """set -eu
cd /in && mkdir repo && tar -x -C repo -f tree.tar && cd repo
git init -q -b base && git -c user.name=base -c user.email=base@repro.invalid add -A
git -c user.name=base -c user.email=base@repro.invalid commit -q -m base --no-verify
git checkout -q -b candidate
git apply --whitespace=nowarn /in/change.diff
git add -A
git -c user.name=agent -c user.email=agent@repro.invalid commit -q -F /in/claim.txt --no-verify
python -m pr_agent.cli --pr_url=base --json-output /in/review.json review \
  >/in/agent.log 2>&1 || true
echo '>>>>> Review'
cat /in/review.json 2>/dev/null || tail -20 /in/agent.log
"""


def pr_agent_env(model: str) -> dict[str, str]:
    """PR-Agent's settings (Dynaconf variables): the local git provider and the model."""
    return {
        "CONFIG__GIT_PROVIDER": "local",
        "CONFIG__MODEL": f"groq/{model}",
        "CONFIG__FALLBACK_MODELS": f'["groq/{model}"]',
        "CONFIG__CUSTOM_MODEL_MAX_TOKENS": "131072",
        "CONFIG__PUBLISH_OUTPUT": "true",
    }


def build_pr_agent(docker: str = "docker") -> None:
    present = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
        [docker, "image", "inspect", PR_AGENT_IMAGE],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if present.returncode != 0:
        subprocess.run(  # noqa: S603 - docker, building the pinned Dockerfile above
            [docker, "build", "--tag", PR_AGENT_IMAGE, "-"],
            input=DOCKERFILE.encode(),
            check=True,
            capture_output=True,
            timeout=1800,
        )


def _bundle(git: Git, sealed: swe.Sealed) -> bytes:
    """The container's input: base's tree, the diff, the claim and the script, as one tar."""
    # No line-ending conversion: Windows' core.autocrlf would rewrite the files and the diff
    # would no longer apply.
    tree = git.run("-c", "core.autocrlf=false", "archive", "--format=tar", sealed.base_commit)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, data in (
            ("tree.tar", tree),
            ("change.diff", sealed.diff.encode()),
            ("claim.txt", f"{sealed.title}\n\n{sealed.claim}".encode()),
            ("run.sh", RUN_SH.encode()),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def pr_agent(
    git: Git, sealed: swe.Sealed, model: str, *, docker: str = "docker", timeout_s: float = 900.0
) -> Answer:
    """PR-Agent's review of the change, in a container; the key from ``GROQ_API_KEY``."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return Answer("UNVERIFIABLE", "GROQ_API_KEY is not set", {"system_error": True})
    name = f"repro-pr-agent-{uuid.uuid4().hex[:12]}"
    settings = pr_agent_env(model)
    argv = [docker, "run", "--rm", "-i", "--name", name, "--memory", "2g", "-e", "GROQ__KEY"]
    for variable in settings:
        argv += ["-e", variable]
    argv += [
        "--entrypoint",
        "sh",
        PR_AGENT_IMAGE,
        "-c",
        "mkdir -p /in && tar -x -C /in && sh /in/run.sh",
    ]
    env = {**os.environ, **settings, "GROQ__KEY": key}
    try:
        done = subprocess.run(  # noqa: S603 - docker, with the image built above
            argv,
            input=_bundle(git, sealed),
            env=env,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", name], capture_output=True, check=False, timeout=120)  # noqa: S603
        return Answer("UNVERIFIABLE", f"PR-Agent took over {timeout_s:g} s", {"system_error": True})
    said = done.stdout.decode("utf-8", "replace").partition(">>>>> Review\n")[2]
    return pr_agent_answer(said.replace(key, "<key>"))


def pr_agent_answer(output: str) -> Answer:
    """The rule: a key issue or a security concern is FLAGGED; neither, VERIFIED."""
    try:
        review = json.loads(output)
    except ValueError:
        return Answer(
            "UNVERIFIABLE",
            "PR-Agent wrote no review",
            {"system_error": True, "log": output[-1500:]},
        )
    found = review.get("review", review) if isinstance(review, dict) else {}
    issues = found.get("key_issues_to_review") or []
    security = str(found.get("security_concerns", "No")).strip()
    concern = bool(security) and not security.lower().startswith("no")
    detail = {"key_issues": issues, "security_concerns": security, "review": found}
    if issues or concern:
        return Answer("FLAGGED", "PR-Agent listed a key issue or a security concern", detail)
    return Answer("VERIFIED", "PR-Agent listed no key issue and no security concern", detail)


# -- the command ----------------------------------------------------------------------------------


def _backend(mode: str, cassettes: Path) -> LLMBackend:
    if mode == "replay":
        return CassetteBackend(cassettes, "replay")
    return CassetteBackend(cassettes, "record", OpenAICompatibleBackend(Endpoint.groq()))


def answer_for(
    system: str,
    task: swe.Task,
    args: argparse.Namespace,
    environments: Mapping[str, tuple[Environment, str]],
    cache: task_images.ImageCache | None = None,
) -> Answer:
    sealed = task.input
    if system == "b0":
        env, command = environments[task.instance_id]
        if cache is not None:
            cache.ready(env.image)
        return ci_only(env, command, sealed.diff)
    owner, _, name = sealed.repo.partition("/")
    git = swe.fetch_base(args.mirrors / owner / f"{name}.git", sealed.repo, sealed.base_commit)
    backend = _backend(args.mode, args.cassettes)
    if system == "b1":
        return llm_answer(*asyncio.run(ask(backend, diff_request(sealed, args.model))))
    if system == "b2":
        head = swe.head_commit(git, sealed)
        request = static_request(sealed, RepoTools(git, sealed.base_commit, head), args.model)
        return llm_answer(*asyncio.run(ask(backend, request)))
    build_pr_agent()
    return pr_agent(git, sealed, args.model)


def pin_environments(
    environments: Mapping[str, tuple[Environment, str]],
    manifest: Path | None,
    cache: task_images.ImageCache | None,
) -> dict[str, tuple[Environment, str]]:
    """B0's environments in the images the manifest pinned; without a manifest, as the dataset
    names them, pinned by their registry when a budget lets images be pulled."""
    pinned = swe.manifest_images(manifest) if manifest else None
    found = {}
    for instance_id, (given, command) in environments.items():
        image = given.image
        if pinned is not None:
            if instance_id not in pinned:
                raise swe.ContractError(f"the manifest pins no image for {instance_id}")
            image = pinned[instance_id]
        elif cache is not None:
            image = swe.pinned(image, registry=True)
        found[instance_id] = (replace(given, image=image), command)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--system", choices=("b0", "b1", "b2", "b3"), required=True)
    parser.add_argument("--sealed", type=Path, required=True, help="J01's sealed.jsonl")
    parser.add_argument("--mirrors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--instances", type=Path, help="B0: the tasks' images and test commands")
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--cassettes", type=Path, default=Path("bench/cassettes"))
    parser.add_argument("--model", default=GROQ_MODEL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--manifest", type=Path, help="B0: the images pinned at sealing (J01)")
    task_images.add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        tasks = [swe.Task.from_row(row) for row in swe.read_jsonl(args.sealed)][: args.limit]
        environments = {}
        if args.system == "b0":
            if args.instances is None:
                parser.error("B0 needs --instances for the tasks' images and test commands")
            for record in swe.read_jsonl(args.instances):
                environments[str(record["instance_id"])] = environment(record)
            cache = task_images.from_arguments(args)
            environments = pin_environments(environments, args.manifest, cache)
        else:
            cache = None
    except (swe.ContractError, truth.OracleError, task_images.ImageError) as exc:
        sys.stderr.write(f"repro_bench.baselines: {exc}\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / f"{args.system}.jsonl").open("a", encoding="utf-8") as results:
        for task in tasks:
            started = time.monotonic()
            try:
                answer = answer_for(args.system, task, args, environments, cache)
            except (
                swe.ContractError,
                truth.OracleError,
                task_images.ImageError,
                GitError,
                subprocess.CalledProcessError,
            ) as exc:
                answer = Answer(
                    "UNVERIFIABLE", f"the system could not run: {exc}", {"system_error": True}
                )
            row = {
                "system": args.system,
                "instance_id": task.instance_id,
                "model": task.model,
                "patch_sha256": task.patch_sha256,
                "input_sha256": task.input.digest,
                "seconds": round(time.monotonic() - started, 1),
                **asdict(answer),
            }
            results.write(json.dumps(row, sort_keys=True) + "\n")
            results.flush()
            said = f"{answer.status} - {answer.reason}"
            sys.stdout.write(f"{args.system} {task.instance_id} ({task.model}): {said}\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
