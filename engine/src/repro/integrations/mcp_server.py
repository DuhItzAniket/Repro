"""Repro as an MCP server: an agent asks for its change to be verified and reads the evidence
(K03; roadmap: "while the verifier stays independent").

Model Context Protocol servers expose tools that an agent's host calls
[modelcontextprotocol.io/specification]. This one runs on stdio through the official Python
SDK (`mcp`, MIT; `MCPServer`), which Repro already ships as a dependency of the Claude Agent SDK.
`repro mcp` starts it.

**Independence** is the point, and the tools are shaped by it:
- **The agent names commits, never content.** `start_verification` takes a repository and two
  commits. Repro snapshots them from git objects (no working tree, no `.git`), runs them in its
  own sandbox, and judges the claim against what it ran. The agent cannot hand it a test
  result, a trace or a file that is not in a commit.
- **Everything else is read-only.** The agent can read the run's status, its card, and its
  evidence, but it cannot write to the store, and every card is the engine's. The evidence
  each verdict cites is there to check, by ID.
- **A run is Repro's run.** It is started as `repro run --no-serve` in its own process, with
  the engine's settings (sandbox, image, agents, budget). It appears in the cockpit and in the
  fleet view like any other run.

The tools' answers are JSON text; a card can also be Markdown, as `repro export` writes it.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from repro import __version__
from repro.card import render
from repro.config import Settings
from repro.store import StoreError, StoreReader

START_TIMEOUT_S: Final = 120.0
_RUN_ID: Final = re.compile(r"\brun_[0-9A-HJKMNP-TV-Z]{26}\b")
EVIDENCE_PAGE: Final = 200
INSTRUCTIONS: Final = (
    "Repro reproduces a code change and judges its claims against what running it showed. Commit "
    "your change first: start_verification names a repository and two commits (base and head), "
    "and Repro reads them from git, never from your working tree. Then poll verification_status "
    "until the run is no longer running, and read get_card. Each verdict cites evidence by ID: "
    "get_evidence shows any of it. A card is VERIFIED, FLAGGED or UNVERIFIABLE; its missing list "
    "says what could not be checked."
)
_READ_ONLY: Final = ToolAnnotations(read_only_hint=True, open_world_hint=False)


class Verifier:
    """What the tools do, apart from the protocol, so it can be tested directly."""

    def __init__(
        self, settings: Settings, *, python: str = sys.executable, extra: Sequence[str] = ()
    ) -> None:
        self.settings = settings
        self.python = python
        #: More ``repro run`` options for every run (a test's ``--analyse-only``).
        self.extra = tuple(extra)
        self.logs = settings.paths.data_dir / "mcp"

    def _stored(self) -> bool:
        """Whether the engine has stored anything yet (no database before its first run)."""
        return self.settings.paths.database.is_file()

    def _reader(self) -> StoreReader:
        return StoreReader(self.settings.paths.database)

    def _has(self, run_id: str) -> bool:
        """Whether the run is in the store yet: ``repro run`` names it before its first commit."""
        if not self._stored():
            return False
        try:
            with self._reader() as store:
                return store.run(run_id) is not None
        except StoreError:  # the database is still being created
            return False

    def start(self, repo: str, base: str, head: str, claim: str = "") -> dict[str, Any]:
        """Starts ``repro run`` on the change; its run ID once the run is stored, so the other
        tools find it."""
        self.logs.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{time.monotonic_ns()}"
        log = self.logs / f"start-{stamp}.log"
        argv = [
            self.python,
            "-m",
            "repro",
            "run",
            "--repo",
            repo,
            "--base",
            base,
            "--head",
            head,
            "--no-serve",
        ]
        argv += self.extra
        if claim.strip():
            pr = Path(tempfile.mkdtemp(prefix="repro-mcp-")) / "pr.txt"
            first = claim.strip().splitlines()[0][:200]
            pr.write_bytes(f"{first}\n{claim}".encode())
            argv += ["--pr-file", str(pr)]
        env = {**os.environ, "REPRO_DATA_DIR": str(self.settings.paths.data_dir)}
        with log.open("wb") as out:
            process = subprocess.Popen(  # noqa: S603 - Repro itself, with the agent's refs as args
                argv, stdout=out, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL
            )
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            said = log.read_text(encoding="utf-8", errors="replace")
            found = _RUN_ID.search(said)
            if found and f"{found[0]} started" in said and self._has(found[0]):
                return {"run_id": found[0], "status": "running"}
            if process.poll() is not None:
                lines = said.strip().splitlines()
                return {"error": lines[-1] if lines else f"repro run exited {process.returncode}"}
            time.sleep(0.2)
        return {"error": f"the run did not start within {START_TIMEOUT_S:g} s"}

    def status(self, run_id: str) -> dict[str, Any]:
        if not self._stored():
            return {"error": "no such run"}
        with self._reader() as store:
            found = store.run(run_id)
            if found is None:
                return {"error": "no such run"}
            card = store.card(run_id)
            return {
                "run_id": run_id,
                "status": found.status,
                "events": store.last_seq(run_id),
                "card_status": card.get("status") if card else None,
            }

    def card(self, run_id: str, form: Literal["markdown", "json"] = "markdown") -> str:
        if not self._stored():
            return json.dumps({"error": "this run has no card yet"})
        with self._reader() as store:
            found = store.card(run_id)
        if found is None:
            return json.dumps({"error": "this run has no card yet"})
        return render(found) if form == "markdown" else json.dumps(found, sort_keys=True)

    def evidence(self, run_id: str) -> list[dict[str, Any]]:
        if not self._stored():
            return []
        with self._reader() as store:
            records = store.evidence_of(run_id)[:EVIDENCE_PAGE]
        keys = ("id", "type", "summary", "stability", "origin")
        return [{key: record.get(key) for key in keys} for record in records]

    def one(self, run_id: str, evidence_id: str) -> dict[str, Any]:
        if not self._stored():
            return {"error": "no such evidence in this run"}
        with self._reader() as store:
            record = store.evidence(evidence_id)
        if record is None or record.get("run_id") != run_id:
            return {"error": "no such evidence in this run"}
        return record

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self._stored():
            return []
        with self._reader() as store:
            return [
                {"run_id": r.id, "repo": r.repo, "status": r.status, "created_at": r.created_at}
                for r in store.runs(max(1, min(limit, 100)))
            ]


def server(verifier: Verifier) -> MCPServer:
    """The MCP server over ``verifier``: one tool that starts a run, the rest read-only."""
    mcp = MCPServer("repro", instructions=INSTRUCTIONS, version=__version__)

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def start_verification(repo: str, base: str, head: str, claim: str = "") -> str:
        """Start verifying a change: Repro runs base and head (commits in the git repository at
        `repo`, a local path) in its sandbox and judges `claim` (what the change says it does)
        against what it ran. Returns the run's ID; the run takes minutes."""
        return json.dumps(verifier.start(repo, base, head, claim))

    @mcp.tool(annotations=_READ_ONLY)
    def verification_status(run_id: str) -> str:
        """A run's status (running, completed, failed, cancelled), its event count, and its card's
        status once it has a card."""
        return json.dumps(verifier.status(run_id))

    @mcp.tool(annotations=_READ_ONLY)
    def get_card(run_id: str, form: Literal["markdown", "json"] = "markdown") -> str:
        """A run's Reproduction Card: its status, why, its claims' verdicts with the evidence they
        cite, and what could not be checked."""
        return verifier.card(run_id, form)

    @mcp.tool(annotations=_READ_ONLY)
    def list_evidence(run_id: str) -> str:
        """A run's evidence, one line each: ID, type, summary, stability, origin."""
        return json.dumps(verifier.evidence(run_id))

    @mcp.tool(annotations=_READ_ONLY)
    def get_evidence(run_id: str, evidence_id: str) -> str:
        """One evidence item in full, as the card cites it."""
        return json.dumps(verifier.one(run_id, evidence_id))

    @mcp.tool(annotations=_READ_ONLY)
    def list_runs(limit: int = 20) -> str:
        """The engine's most recent runs, newest first."""
        return json.dumps(verifier.runs(limit))

    return mcp
