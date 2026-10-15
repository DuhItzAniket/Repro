"""The agent lockdown's options and tool gate, and the backend's request types (G01; ADR-0007).

These check what ``AgentSdkBackend`` asks of the SDK; ``test_agents_cli`` checks what the real
Claude Code CLI then does with it.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import HookContext, HookJSONOutput, PreToolUseHookInput

from repro.agents import AgentRequest, Budget, ReproTool
from repro.agents.lockdown import (
    STRUCTURED_OUTPUT,
    lockdown_env,
    lockdown_options,
    permitted_tools,
    tool_gate,
)


async def answer(arguments: Any) -> str:
    return "ok"


PING = ReproTool("ping", "Answers.", {"type": "object", "properties": {}}, answer)
EVIDENCE = ReproTool("read_evidence", "Reads.", {"type": "object", "properties": {}}, answer)
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def request(*, tools: tuple[ReproTool, ...] = (PING,), schema: Any = None) -> AgentRequest:
    return AgentRequest(
        role="review",
        system_prompt="Judge the claim.",
        prompt="<untrusted_pr_description>x</untrusted_pr_description>",
        model="claude-opus-5-5",
        prompt_version="review/1",
        budget=Budget(max_turns=5, max_budget_usd=0.5, timeout_s=60),
        tools=tools,
        output_schema=schema,
        effort="high",
    )


def decide(permitted: frozenset[str], tool_name: str) -> dict[str, Any]:
    hook_input = PreToolUseHookInput(
        session_id="s",
        transcript_path="t",
        cwd="c",
        hook_event_name="PreToolUse",
        tool_name=tool_name,
        tool_input={},
        tool_use_id="toolu_1",
    )
    context: HookContext = {"signal": None}

    async def ask() -> HookJSONOutput:
        return await tool_gate(permitted)(hook_input, "toolu_1", context)

    return dict(asyncio.run(ask()))


def test_the_options_close_every_way_in(tmp_path: Path) -> None:
    options = lockdown_options(
        request(),
        cwd=tmp_path / "cwd",
        config_dir=tmp_path / "config",
        system_prompt_file=tmp_path / "system.md",
        server=None,
    )
    assert options.tools == []  # no built-in tool in context
    assert options.allowed_tools == ["mcp__repro__ping"]
    assert options.disallowed_tools == []
    assert options.permission_mode == "dontAsk"
    assert options.can_use_tool is None  # dontAsk never asks
    assert options.setting_sources == []  # an empty list: None would load settings
    assert options.strict_mcp_config is True
    assert options.plugins == []
    assert options.skills is None
    assert options.verbatim_prompts is True
    assert options.add_dirs == []
    assert options.cwd == str(tmp_path / "cwd")
    assert options.system_prompt == {"type": "file", "path": str(tmp_path / "system.md")}
    assert options.env == lockdown_env(tmp_path / "config")
    assert (options.model, options.effort) == ("claude-opus-5-5", "high")
    assert (options.max_turns, options.max_budget_usd) == (5, 0.5)
    assert options.output_format is None
    assert options.mcp_servers == {}
    hooks = options.hooks or {}
    assert list(hooks) == ["PreToolUse"]
    assert [matcher.matcher for matcher in hooks["PreToolUse"]] == [None]  # every tool


def test_an_output_schema_permits_structured_output_and_nothing_more(tmp_path: Path) -> None:
    options = lockdown_options(
        request(schema=SCHEMA),
        cwd=tmp_path,
        config_dir=tmp_path,
        system_prompt_file=tmp_path / "system.md",
        server=None,
    )
    assert options.output_format == {"type": "json_schema", "schema": SCHEMA}
    assert options.allowed_tools == [STRUCTURED_OUTPUT, "mcp__repro__ping"]


def test_the_environment_disables_memory_settings_and_subagents(tmp_path: Path) -> None:
    env = lockdown_env(tmp_path)
    assert env == {
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
        "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "1",
    }
    assert not any(key.startswith("ANTHROPIC_") for key in env)  # credentials are inherited


def test_a_call_may_run_its_own_tools_only() -> None:
    assert permitted_tools(request()) == {"mcp__repro__ping"}
    assert permitted_tools(request(tools=(PING, EVIDENCE), schema=SCHEMA)) == {
        "mcp__repro__ping",
        "mcp__repro__read_evidence",
        STRUCTURED_OUTPUT,
    }
    assert permitted_tools(request(tools=())) == frozenset()


@pytest.mark.parametrize(
    "tool_name",
    [
        "Bash",
        "Read",
        "Write",
        "WebFetch",
        "Agent",
        "Skill",
        "mcp__other__ping",
        "mcp__repro__read_evidence",  # a Repro tool, but not this call's
        "mcp__repro__",
        "mcp__repro__ping__x",
        "MCP__REPRO__PING",
        STRUCTURED_OUTPUT,  # no output schema was asked for
        "",
    ],
)
def test_the_gate_denies_every_other_tool(tool_name: str) -> None:
    decision = decide(permitted_tools(request()), tool_name)
    specific = decision["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"


@pytest.mark.parametrize("tool_name", ["mcp__repro__ping", STRUCTURED_OUTPUT])
def test_the_gate_leaves_the_calls_own_tools_to_the_allow_rules(tool_name: str) -> None:
    assert decide(permitted_tools(request(schema=SCHEMA)), tool_name) == {}


@pytest.mark.parametrize(
    ("turns", "usd", "seconds"), [(0, 1.0, 1.0), (1, 0.0, 1.0), (1, 1.0, 0.0), (1, -1.0, 1.0)]
)
def test_every_budget_limit_is_positive(turns: int, usd: float, seconds: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        Budget(max_turns=turns, max_budget_usd=usd, timeout_s=seconds)


@pytest.mark.parametrize(
    "name", ["Ping", "read-evidence", "read evidence", "", "_", "mcp__x", "x_", "9lives", "a" * 49]
)
def test_tool_names_are_lower_snake_case(name: str) -> None:
    with pytest.raises(ValueError, match="lower_snake_case"):
        ReproTool(name, "x", {"type": "object"}, answer)
