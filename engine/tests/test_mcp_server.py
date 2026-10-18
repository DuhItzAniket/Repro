"""Repro as an MCP server (K03): through the SDK's own client, in-process."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from mcp import Client

from cli_support import clean_env
from gitrepo import Repo
from repro.config import load_settings
from repro.integrations.mcp_server import INSTRUCTIONS, Verifier, server

BASE = {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n"}
HEAD = {"pkg/core.py": "def f():\n    return 2\n"}


def call(verifier: Verifier, tool: str, **arguments: Any) -> str:
    async def go() -> str:
        async with Client(server(verifier)) as client:
            result = await client.call_tool(tool, arguments)
            return "".join(getattr(part, "text", "") for part in result.content)

    return asyncio.run(go())


def test_the_tools_and_which_of_them_only_read(tmp_path: Path) -> None:
    async def go() -> dict[str, Any]:
        async with Client(server(Verifier(load_settings(env=clean_env(tmp_path))))) as client:
            listed = await client.list_tools()
            return {tool.name: tool for tool in listed.tools}

    tools = asyncio.run(go())
    assert set(tools) == {
        "start_verification",
        "verification_status",
        "get_card",
        "list_evidence",
        "get_evidence",
        "list_runs",
    }
    for name, tool in tools.items():
        reads_only = name != "start_verification"
        assert tool.annotations is not None
        assert bool(tool.annotations.read_only_hint) is reads_only, name
    assert "Commit your change first" in INSTRUCTIONS


def test_an_agent_starts_a_run_and_reads_its_card(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "target")
    base = repo.commit(BASE)
    head = repo.commit(HEAD)
    settings = load_settings(env=clean_env(tmp_path, REPRO_SANDBOX="process"))
    verifier = Verifier(settings, extra=["--analyse-only"])
    started = json.loads(
        call(
            verifier,
            "start_verification",
            repo=str(repo.path),
            base=base,
            head=head,
            claim="Make f return 2",
        )
    )
    run_id = started["run_id"]
    assert started["status"] == "running"
    # The run is stored before start_verification answers, so the other tools find it at once.
    assert json.loads(call(verifier, "verification_status", run_id=run_id))["run_id"] == run_id
    deadline = time.monotonic() + 120
    while (status := json.loads(call(verifier, "verification_status", run_id=run_id)))[
        "status"
    ] == "running":
        assert time.monotonic() < deadline, status
        time.sleep(0.5)
    assert status["card_status"] in {"VERIFIED", "FLAGGED", "UNVERIFIABLE"}
    card = call(verifier, "get_card", run_id=run_id)
    assert status["card_status"] in card  # the Markdown card, as repro export writes it
    assert json.loads(call(verifier, "get_card", run_id=run_id, form="json"))["run_id"] == run_id
    evidence = json.loads(call(verifier, "list_evidence", run_id=run_id))
    assert all({"id", "type", "summary"} <= set(e) for e in evidence)
    if evidence:
        full = json.loads(
            call(verifier, "get_evidence", run_id=run_id, evidence_id=evidence[0]["id"])
        )
        assert full["run_id"] == run_id
    assert [r["run_id"] for r in json.loads(call(verifier, "list_runs"))] == [run_id]


def test_what_does_not_exist_is_said_so(tmp_path: Path) -> None:
    verifier = Verifier(load_settings(env=clean_env(tmp_path)))
    missing = "run_" + "0" * 26
    assert json.loads(call(verifier, "verification_status", run_id=missing)) == {
        "error": "no such run"
    }
    assert "no card yet" in call(verifier, "get_card", run_id=missing)
    started = json.loads(
        call(verifier, "start_verification", repo=str(tmp_path / "nowhere"), base="a", head="b")
    )
    assert "not a git repository" in started["error"]
