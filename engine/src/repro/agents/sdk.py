"""The default ``LLMBackend``: the Claude Agent SDK, locked down (G01; ADR-0007).

Each call runs in a workspace of its own under ``scratch``: an empty working directory, a
Claude configuration directory and the system prompt file, removed when the call ends. Repro's
tools run in-process as one SDK MCP server (``mcp__repro__*``); everything else is closed by
``repro.agents.lockdown``. The SDK starts one Claude Code process per call (research/04 §1.10:
about 1 GiB of memory each), which ``repro.agents.dispatch`` bounds.

What the model does never raises: a run that hits its turn or dollar budget, its time limit, or
returns no valid structured output is a result with that outcome. Only a missing CLI raises.
After an error result, the CLI exits non-zero and the SDK raises ``ResultError``; the result it
already yielded says what happened, so that is what the call reports.
"""

import asyncio
import shutil
import tempfile
from collections.abc import AsyncGenerator, Mapping
from contextlib import aclosing
from pathlib import Path
from typing import Any, Final, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKError,
    CLINotFoundError,
    Message,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolAnnotations,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from claude_agent_sdk.types import McpSdkServerConfig

from repro import __version__
from repro.agents.backend import (
    AgentRequest,
    AgentResult,
    OnProgress,
    Outcome,
    Progress,
    ReproTool,
    Usage,
)
from repro.agents.lockdown import SERVER, lockdown_options, permitted_tools

#: How each ``ResultMessage.subtype`` that is not a success ends a run.
SUBTYPES: Final[dict[str, Outcome]] = {
    "error_max_turns": "max_turns",
    "error_max_budget_usd": "max_budget",
    "error_max_structured_output_retries": "invalid_output",
}
#: Characters of text or tool input shown as an ``agent.state`` detail.
DETAIL: Final = 200


def _sdk_tool(spec: ReproTool) -> Any:
    async def handle(arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            text = await spec.handler(arguments)
        except Exception as exc:  # noqa: BLE001 - the model is told, the run goes on
            return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": text}]}

    return tool(
        spec.name,
        spec.description,
        dict(spec.input_schema),
        annotations=ToolAnnotations(readOnlyHint=True),
    )(handle)


def _server(tools: tuple[ReproTool, ...]) -> McpSdkServerConfig | None:
    if not tools:
        return None
    return create_sdk_mcp_server(SERVER, version=__version__, tools=[_sdk_tool(t) for t in tools])


def _usage(result: ResultMessage) -> Usage:
    usage: Mapping[str, Any] = result.usage or {}
    return Usage(
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cost_usd=float(result.total_cost_usd or 0.0),
    )


def _outcome(result: ResultMessage, expects_structure: bool) -> tuple[Outcome, str]:
    if result.subtype in SUBTYPES:
        return SUBTYPES[result.subtype], result.subtype
    if result.is_error:
        status = f" (HTTP {result.api_error_status})" if result.api_error_status else ""
        return "error", f"{result.subtype}{status}: {'; '.join(result.errors or [])}"[:500]
    if expects_structure and result.structured_output is None:
        return "invalid_output", "no structured output"  # a success without it is a failure
    return "ok", ""


class _Transcript:
    """What a session has said so far: its turns, tool calls, text and result."""

    def __init__(self, permitted: frozenset[str], on_progress: OnProgress | None) -> None:
        self.permitted = permitted
        self.on_progress = on_progress
        self.turn = 0
        self.calls: list[tuple[str, bool]] = []
        self.texts: list[str] = []
        self.result: ResultMessage | None = None
        self._last_id: str | None = None

    def _progress(self, update: Progress) -> None:
        if self.on_progress is not None:
            self.on_progress(update)

    def take(self, message: Message) -> None:
        if isinstance(message, ResultMessage):
            self.result = message
            return
        if not isinstance(message, AssistantMessage):
            return
        # One response can arrive as several messages with one id.
        if message.message_id is None or message.message_id != self._last_id:
            self.turn += 1
        self._last_id = message.message_id
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                self.calls.append((block.name, block.name in self.permitted))
                detail = f"{block.name}({block.input})"[:DETAIL]
                self._progress(Progress("tool_call", self.turn, block.name, detail))
            elif isinstance(block, TextBlock):
                self.texts.append(block.text)
                said = block.text[:DETAIL] or None
                self._progress(Progress("thinking", self.turn, detail=said))
            elif isinstance(block, ThinkingBlock):
                self._progress(Progress("thinking", self.turn))

    def failed(self, outcome: Outcome, detail: str) -> AgentResult:
        return AgentResult(outcome, turns=self.turn, detail=detail, tool_calls=tuple(self.calls))

    def ended(self, expects_structure: bool) -> AgentResult:
        result = self.result
        if result is None:
            return self.failed("error", "the session ended without a result")
        outcome, detail = _outcome(result, expects_structure)
        return AgentResult(
            outcome=outcome,
            structured=result.structured_output if outcome == "ok" else None,
            text=result.result or "\n".join(self.texts),
            turns=result.num_turns,
            usage=_usage(result),
            detail=detail,
            tool_calls=tuple(self.calls),
        )


class AgentSdkBackend:
    """Runs agent calls through the Claude Agent SDK, each in a workspace under ``scratch``."""

    def __init__(self, scratch: Path, *, cli_path: Path | None = None) -> None:
        self.scratch = scratch
        self.cli_path = cli_path

    async def run(
        self, request: AgentRequest, on_progress: OnProgress | None = None
    ) -> AgentResult:
        self.scratch.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="agent-", dir=self.scratch))
        try:
            return await self._run(request, workspace, on_progress)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    async def _run(
        self, request: AgentRequest, workspace: Path, on_progress: OnProgress | None
    ) -> AgentResult:
        cwd, config = workspace / "cwd", workspace / "config"
        cwd.mkdir()
        config.mkdir()
        prompt_file = workspace / "system.md"
        prompt_file.write_text(request.system_prompt, encoding="utf-8")
        options = lockdown_options(
            request,
            cwd=cwd,
            config_dir=config,
            system_prompt_file=prompt_file,
            server=_server(tuple(request.tools)),
        )
        if self.cli_path is not None:
            options.cli_path = str(self.cli_path)
        transcript = _Transcript(permitted_tools(request), on_progress)
        try:
            async with asyncio.timeout(request.budget.timeout_s):
                stream = query(prompt=request.prompt, options=options)
                async with aclosing(cast(AsyncGenerator[Message], stream)) as messages:
                    async for message in messages:
                        transcript.take(message)
        except TimeoutError:
            return transcript.failed("timeout", f"took over {request.budget.timeout_s:g} s")
        except CLINotFoundError:
            raise
        except ClaudeSDKError as exc:
            result = transcript.result
            if result is None or not result.is_error:  # not the exit after an error result
                return transcript.failed("error", f"{type(exc).__name__}: {exc}"[:500])
        return transcript.ended(request.output_schema is not None)
