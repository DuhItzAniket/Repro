"""The pipeline's agent jobs (G04 on): each runs its agents through ``run_agent`` and emits
what they found as events, and a call that ends without a usable answer fails the job, which
the card then lists as ``agent_failed`` (ground rule 3: never unverified silently).

- ``claims`` (stage ``read``, G04): the reader agent on the PR's text and the change's files,
  then one ``claim.extracted`` per claim. It needs nothing else from the run, so it runs while
  the build and run stages do.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from repro.agents.backend import AgentResult
from repro.agents.events import run_agent
from repro.agents.prompts import load_prompt
from repro.agents.reader import PrText, read_claims, reader_request
from repro.agents.setup import AgentSetup
from repro.gitops import Git
from repro.gitops.changes import diff
from repro.orchestrator import Job, JobContext, OnFailure

READER_PROMPT: Final = "reader"


class AgentFailedError(RuntimeError):
    """An agent call ended without an answer the job can use."""


@dataclass(slots=True)
class AgentState:
    """What the agent jobs hand on to each other."""

    #: The claims read from the PR (``claim.extracted`` payloads' ``claim``); None until read.
    claims: list[dict[str, Any]] | None = None
    files: list[str] = field(default_factory=list)


def changed_files(git: Git, base: str, head: str) -> list[str]:
    """The paths the change touches, as git lists them (renames by their new path)."""
    return sorted({change.path for change in diff(git, base, head)})


def commit_messages(git: Git, base: str, head: str) -> list[str]:
    """The messages of the commits ``head`` has and ``base`` does not, oldest first."""
    raw = git.run("log", "--reverse", "--format=%B%x00", "--end-of-options", f"{base}..{head}")
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    return [message.strip() for message in text.split("\x00") if message.strip()]


def _call(ctx: JobContext, setup: AgentSetup, build: Callable[[], Any], agent: str) -> AgentResult:
    request = build()
    return asyncio.run(
        run_agent(ctx, setup.backend, setup.dispatch, request, agent=agent, ledger=setup.ledger)
    )


def claims_job(
    git: Git, *, base: str, head: str, pr: PrText, setup: AgentSetup, state: AgentState
) -> Job:
    def run(ctx: JobContext) -> None:
        files = changed_files(git, base, head)
        state.files = files
        if not pr.parts:
            ctx.log("the pull request has no text: no claims to read", level="warning")
            state.claims = []
            return
        prompt = load_prompt(READER_PROMPT)
        agent = setup.dispatch.agent_id()
        ctx.log(f"reading the pull request's claims ({setup.label}, {setup.model('read')})")
        result = _call(
            ctx,
            setup,
            lambda: reader_request(pr, files, prompt, setup.model("read")),
            agent,
        )
        if result.outcome != "ok":
            raise AgentFailedError(f"the reader ended {result.outcome}: {result.detail}"[:500])
        claims = read_claims(result.structured, files, [source for source, _ in pr.parts])
        for claim in claims:
            ctx.emit("claim.extracted", status="ok", payload={"claim": claim}, agent=agent)
        ctx.log(f"{len(claims)} claim{'s' if len(claims) != 1 else ''} read from the pull request")
        state.claims = claims

    return Job(
        "claims",
        "read",
        run,
        OnFailure(
            reason="agent_failed",
            detail="the pull request's claims could not be read",
            resolution="check the agent settings, the API or the cassettes, then run again",
        ),
    )
