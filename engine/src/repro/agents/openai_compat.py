"""An ``LLMBackend`` for OpenAI-compatible Chat Completions APIs: Groq, local servers (G10).

ADR-0016. Repro runs the agent loop itself, so there is nothing to lock down but the loop:

- the request's ``ReproTool``s are the only functions offered, and a call to any other name is
  answered with a refusal, never run; there is no CLI, file system or shell to reach;
- each model response is one turn; the call ends at ``max_turns``, at ``max_budget_usd`` of
  estimated cost, or at ``timeout_s``;
- with an output schema, the loop's last step asks for the answer alone, with
  ``response_format`` ``json_schema`` (strict when the schema allows it), since such an API
  cannot combine structured output with tools; the answer is validated against the schema and
  refused (``invalid_output``) if it does not match, after one retry.

Rate limits are honoured: a 429 waits for its ``retry-after`` (within the call's time), and
a 5xx is retried after a pause, each up to ``Endpoint.retries`` times. The API key is read
from the environment variable the endpoint names when a call is made, and appears in no
result, error or log. Costs come from the endpoint's price table, each price with its source
(ADR-0016); a model with no known price gets no cost (``Usage.priced`` is false).
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from jsonschema import Draft7Validator

from repro.agents.backend import AgentRequest, AgentResult, OnProgress, Outcome, Progress, Usage

#: Groq's OpenAI-compatible endpoint (console.groq.com/docs/openai, read 2026-10-16).
GROQ_BASE_URL: Final = "https://api.groq.com/openai/v1"
DETAIL: Final = 200
#: Seconds to wait before retrying a 5xx, then twice as long each time.
BACKOFF_S: Final = 2.0
ANSWER_NOW: Final = (
    "Give your final answer now, as JSON matching the required schema, and nothing else."
)


@dataclass(frozen=True, slots=True)
class Price:
    """US dollars per million tokens, and where and when the price was read."""

    input: float
    output: float
    source: str


#: Groq's prices (each model's page on console.groq.com/docs/model/, read 2026-10-16).
GROQ_PRICES: Final = {
    "openai/gpt-oss-120b": Price(0.15, 0.60, "console.groq.com/docs/model/openai/gpt-oss-120b"),
    "openai/gpt-oss-20b": Price(0.075, 0.30, "console.groq.com/docs/model/openai/gpt-oss-20b"),
    "qwen/qwen3.8-27b": Price(0.80, 4.00, "console.groq.com/docs/model/qwen/qwen3.8-27b"),
}


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where the API is and how to call it."""

    base_url: str
    #: The environment variable holding the key; None for a server that takes none (local).
    api_key_env: str | None
    prices: Mapping[str, Price] = field(default_factory=dict)
    temperature: float | None = None
    max_output_tokens: int = 4096
    #: Send ``reasoning_effort`` (from the request's effort) and ``include_reasoning: false``.
    reasoning_controls: bool = False
    retries: int = 3
    #: Seconds one HTTP request may take.
    request_timeout_s: float = 120.0

    @classmethod
    def groq(cls) -> "Endpoint":
        """Groq: gpt-oss's reasoning controls, temperature 0.5 (the low end of the range Groq
        recommends for reasoning models, for the most consistent answers; docs/reasoning)."""
        return cls(
            GROQ_BASE_URL,
            "GROQ_API_KEY",
            GROQ_PRICES,
            temperature=0.5,
            reasoning_controls=True,
        )


class _HttpError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retry_after = retry_after


def _post(url: str, body: Mapping[str, Any], key: str | None, timeout: float) -> dict[str, Any]:
    headers = {"content-type": "application/json", "user-agent": "repro"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(  # noqa: S310 - the endpoint's own https or loopback URL
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data: dict[str, Any] = json.loads(response.read())
            return data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            message = str(json.loads(raw)["error"]["message"])
        except (ValueError, KeyError, TypeError):
            message = raw[:300] or exc.reason
        after = exc.headers.get("retry-after") if exc.headers else None
        try:
            retry_after = float(after) if after is not None else None
        except ValueError:
            retry_after = None
        raise _HttpError(exc.code, message[:300], retry_after) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _HttpError(0, f"cannot reach the API: {exc}") from None


def strict_allowed(schema: Any) -> bool:
    """Whether the API's strict mode can take ``schema``: every object lists all its
    properties as required and allows no others (docs/structured-outputs)."""
    if isinstance(schema, list):
        return all(strict_allowed(item) for item in schema)
    if not isinstance(schema, Mapping):
        return True
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            return False
        if set(schema.get("required", [])) != set(properties):
            return False
    return all(strict_allowed(value) for value in schema.values())


class _Session:
    """One call's conversation, usage and progress."""

    def __init__(
        self,
        backend: "OpenAICompatibleBackend",
        request: AgentRequest,
        on_progress: OnProgress | None,
    ) -> None:
        self.backend = backend
        self.request = request
        self.on_progress = on_progress
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.prompt},
        ]
        self.tools = {tool.name: tool for tool in request.tools}
        self.turn = 0
        self.calls: list[tuple[str, bool]] = []
        self.tokens: dict[str, list[int]] = {}

    def progress(self, update: Progress) -> None:
        if self.on_progress is not None:
            self.on_progress(update)

    def usage(self) -> tuple[Usage, dict[str, Usage]]:
        prices = self.backend.endpoint.prices
        by_model = {}
        for model, (prompt, completion, cached) in self.tokens.items():
            price = prices.get(model)
            cost = (
                (prompt * price.input + completion * price.output) / 1_000_000
                if price is not None
                else 0.0
            )
            by_model[model] = Usage(prompt, completion, cached, cost, priced=price is not None)
        total = Usage(
            sum(u.input_tokens for u in by_model.values()),
            sum(u.output_tokens for u in by_model.values()),
            sum(u.cache_read_tokens for u in by_model.values()),
            sum(u.cost_usd for u in by_model.values()),
            priced=all(u.priced for u in by_model.values()),
        )
        return total, by_model

    def result(self, outcome: Outcome, **fields: Any) -> AgentResult:
        usage, by_model = self.usage()
        return AgentResult(
            outcome,
            turns=self.turn,
            usage=usage,
            tool_calls=tuple(self.calls),
            by_model=by_model,
            **fields,
        )

    def over_budget(self) -> bool:
        usage, _ = self.usage()
        return usage.priced and usage.cost_usd > self.request.budget.max_budget_usd

    async def ask(self, extra: Mapping[str, Any]) -> dict[str, Any]:
        """One model response: a turn."""
        self.turn += 1
        reply = await self.backend.complete(self.request, self.messages, extra)
        model = str(reply.get("model") or self.request.model)
        used = reply.get("usage") or {}
        cached = (used.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        totals = self.tokens.setdefault(model, [0, 0, 0])
        totals[0] += int(used.get("prompt_tokens") or 0)
        totals[1] += int(used.get("completion_tokens") or 0)
        totals[2] += int(cached)
        message: dict[str, Any] = reply["choices"][0]["message"]
        return message

    async def answer_tool(self, call: Mapping[str, Any]) -> str:
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        tool = self.tools.get(name)
        self.calls.append((name, tool is not None))
        arguments_text = str(function.get("arguments") or "{}")
        detail = f"{name}({arguments_text})"[:DETAIL]
        self.progress(Progress("tool_call", self.turn, name, detail))
        if tool is None:
            return f"error: {name} is not one of this call's tools"
        try:
            arguments = json.loads(arguments_text)
        except ValueError:
            return "error: the arguments are not JSON"
        if not isinstance(arguments, dict):
            return "error: the arguments are not a JSON object"
        try:
            return await tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001 - the model is told, the call goes on
            return f"error: {exc}"


class OpenAICompatibleBackend:
    """Runs agent calls against an OpenAI-compatible Chat Completions endpoint."""

    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint

    def _key(self) -> str | None:
        if self.endpoint.api_key_env is None:
            return None
        key = os.environ.get(self.endpoint.api_key_env, "").strip()
        if not key:
            raise _HttpError(0, f"{self.endpoint.api_key_env} is not set")
        return key

    async def complete(
        self, request: AgentRequest, messages: list[dict[str, Any]], extra: Mapping[str, Any]
    ) -> dict[str, Any]:
        """One chat completion, retried on rate limits and server errors."""
        endpoint = self.endpoint
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_completion_tokens": endpoint.max_output_tokens,
            **extra,
        }
        if endpoint.temperature is not None:
            body["temperature"] = endpoint.temperature
        if endpoint.reasoning_controls:
            body["include_reasoning"] = False
            if request.effort is not None:
                body["reasoning_effort"] = {"xhigh": "high", "max": "high"}.get(
                    request.effort, request.effort
                )
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        key = self._key()
        for attempt in range(endpoint.retries + 1):
            try:
                return await asyncio.to_thread(_post, url, body, key, endpoint.request_timeout_s)
            except _HttpError as exc:
                retryable = exc.status == 429 or exc.status >= 500  # noqa: PLR2004 - HTTP codes
                if not retryable or attempt == endpoint.retries:
                    raise
                pause = exc.retry_after if exc.retry_after is not None else BACKOFF_S * 2**attempt
                await asyncio.sleep(pause)
        raise AssertionError("unreachable")  # pragma: no cover

    async def run(
        self, request: AgentRequest, on_progress: OnProgress | None = None
    ) -> AgentResult:
        session = _Session(self, request, on_progress)
        started = time.monotonic()
        try:
            async with asyncio.timeout(request.budget.timeout_s):
                return await self._loop(session)
        except TimeoutError:
            took = time.monotonic() - started
            return session.result(
                "timeout", detail=f"took over {request.budget.timeout_s:g} s ({took:.0f} s)"
            )
        except _HttpError as exc:
            return session.result("error", detail=str(exc)[:500])

    async def _loop(self, session: _Session) -> AgentResult:
        request = session.request
        functions = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                },
            }
            for tool in request.tools
        ]
        if not functions and request.output_schema is not None:
            return await self._answer(session, "")  # nothing to look up: straight to the answer
        text = ""
        while True:
            if session.turn == request.budget.max_turns:
                return session.result("max_turns", detail="error_max_turns")
            message = await session.ask({"tools": functions} if functions else {})
            if session.over_budget():
                return session.result("max_budget", detail="error_max_budget_usd")
            text = str(message.get("content") or "")
            if text:
                session.progress(Progress("thinking", session.turn, detail=text[:DETAIL]))
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break
            session.messages.append(
                {"role": "assistant", "content": text or None, "tool_calls": tool_calls}
            )
            for call in tool_calls:
                answer = await session.answer_tool(call)
                session.messages.append(
                    {"role": "tool", "tool_call_id": call.get("id"), "content": answer}
                )
        if request.output_schema is None:
            return session.result("ok", text=text)
        return await self._answer(session, text)

    async def _answer(self, session: _Session, text: str) -> AgentResult:
        """The structured answer, asked for on its own and checked against the schema."""
        request = session.request
        schema = dict(request.output_schema or {})
        validator = Draft7Validator(schema)
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": strict_allowed(schema), "schema": schema},
        }
        if text:
            session.messages.append({"role": "assistant", "content": text})
        problem = ""
        for _ in range(2):  # the answer, and one retry
            if session.turn == request.budget.max_turns:
                return session.result("max_turns", detail="error_max_turns")
            session.messages.append({"role": "user", "content": ANSWER_NOW + problem})
            message = await session.ask({"response_format": response_format})
            if session.over_budget():
                return session.result("max_budget", detail="error_max_budget_usd")
            content = str(message.get("content") or "")
            session.messages.append({"role": "assistant", "content": content})
            try:
                answer = json.loads(content)
            except ValueError:
                problem = " The last answer was not JSON."
                continue
            errors = sorted(validator.iter_errors(answer), key=lambda e: list(e.path))
            if not errors:
                session.progress(Progress("thinking", session.turn, detail=content[:DETAIL]))
                return session.result("ok", structured=answer, text=content)
            problem = f" The last answer did not match the schema: {errors[0].message[:200]}."
        return session.result(
            "invalid_output", detail=f"no valid structured output:{problem}"[:500]
        )
