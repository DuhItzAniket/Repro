"""The OpenAI-compatible backend: Groq and local servers (G10; ADR-0016).

Every test runs the backend against ``FakeOpenAIApi`` on 127.0.0.1: no network, a dummy key,
a scripted model.
"""

import asyncio
import json
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from fake_openai_api import Failure, FakeOpenAIApi, Raw, Script, call_tools, say
from repro.agents import (
    AgentRequest,
    AgentResult,
    Budget,
    CassetteBackend,
    Progress,
    ReproTool,
    openai_compat,
)
from repro.agents.openai_compat import (
    GROQ_PRICES,
    Endpoint,
    OpenAICompatibleBackend,
    strict_allowed,
)

KEY = "gsk_test_not_a_real_key"
MODEL = "openai/gpt-oss-120b"
STRICT: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["supported", "contradicted"]}},
    "required": ["verdict"],
    "additionalProperties": False,
}


class Pings:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, Any]] = []

    async def __call__(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(dict(arguments))
        return f"pong {arguments.get('word', '')}".strip()

    def tool(self) -> ReproTool:
        return ReproTool("ping", "Answers pong.", {"type": "object", "properties": {}}, self)


def endpoint(api: FakeOpenAIApi, **changes: Any) -> Endpoint:
    groq = Endpoint.groq()
    fields = {
        "base_url": api.base_url,
        "api_key_env": "GROQ_API_KEY",
        "prices": groq.prices,
        "temperature": groq.temperature,
        "reasoning_controls": True,
        "retries": 1,
        "request_timeout_s": 10.0,
    }
    return Endpoint(**(fields | changes))


def request(**changes: Any) -> AgentRequest:
    fields: dict[str, Any] = {
        "role": "review",
        "system_prompt": "Judge the claim.",
        "prompt": "Is it supported?",
        "model": MODEL,
        "prompt_version": "review/1",
        "budget": Budget(max_turns=4, max_budget_usd=1.0, timeout_s=30),
        "effort": "high",
    }
    return AgentRequest(**(fields | changes))


def run(
    script: Script, monkeypatch: pytest.MonkeyPatch, *, progress: list[Progress] | None = None,
    end: Mapping[str, Any] | None = None, **changes: Any,
) -> tuple[AgentResult, FakeOpenAIApi]:  # fmt: skip
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    api = FakeOpenAIApi(script)
    with api.serving():
        backend = OpenAICompatibleBackend(endpoint(api, **(end or {})))
        seen = progress if progress is not None else []
        result = asyncio.run(backend.run(request(**changes), seen.append))
    return result, api


def turns(body: Mapping[str, Any]) -> int:
    messages: list[Mapping[str, Any]] = body["messages"]
    return sum(1 for message in messages if message["role"] == "assistant")


def test_a_plain_call_sends_the_request_and_counts_its_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, api = run(lambda body: say("Supported."), monkeypatch)

    assert (result.outcome, result.text, result.turns) == ("ok", "Supported.", 1)
    [body] = api.requests
    assert body["model"] == MODEL
    assert body["messages"] == [
        {"role": "system", "content": "Judge the claim."},
        {"role": "user", "content": "Is it supported?"},
    ]
    assert (body["temperature"], body["reasoning_effort"], body["include_reasoning"]) == (
        0.5,
        "high",
        False,
    )
    assert "tools" not in body
    assert api.keyed == [True]
    price = GROQ_PRICES[MODEL]
    expected = (1000 * price.input + 100 * price.output) / 1_000_000
    assert result.usage.cost_usd == pytest.approx(expected)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 100)
    assert result.by_model[MODEL].priced


def test_the_tool_loop_runs_the_calls_own_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    pings = Pings()
    progress: list[Progress] = []

    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        if turns(body) == 0:
            return call_tools(("ping", {"word": "a"}), text="Checking.")
        return say("Supported.")

    result, api = run(script, monkeypatch, progress=progress, tools=(pings.tool(),))

    assert (result.outcome, result.text, result.turns) == ("ok", "Supported.", 2)
    assert pings.calls == [{"word": "a"}]
    assert result.tool_calls == (("ping", True),)
    first, second = api.requests
    assert first["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "ping",
                "description": "Answers pong.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "pong a"}
    assert [(p.state, p.turn, p.tool) for p in progress] == [
        ("thinking", 1, None),
        ("tool_call", 1, "ping"),
        ("thinking", 2, None),
    ]


@pytest.mark.parametrize(
    ("name", "arguments", "answer"),
    [
        ("bash", {"command": "ls"}, "error: bash is not one of this call's tools"),
        ("ping", "{not json", "error: the arguments are not JSON"),
        ("ping", "[1, 2]", "error: the arguments are not a JSON object"),
    ],
)
def test_a_call_outside_the_calls_tools_or_malformed_is_refused(
    monkeypatch: pytest.MonkeyPatch, name: str, arguments: Any, answer: str
) -> None:
    pings = Pings()

    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        return call_tools((name, arguments)) if turns(body) == 0 else say("done")

    result, api = run(script, monkeypatch, tools=(pings.tool(),))
    assert result.outcome == "ok"
    assert pings.calls == []
    assert api.requests[1]["messages"][-1]["content"] == answer
    assert result.tool_calls == ((name, name == "ping"),)


def test_a_tool_that_raises_tells_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(arguments: Mapping[str, Any]) -> str:
        raise KeyError("no evidence ev_1")

    tool = ReproTool("get_evidence", "Reads.", {"type": "object"}, broken)

    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        return call_tools(("get_evidence", {})) if turns(body) == 0 else say("done")

    result, api = run(script, monkeypatch, tools=(tool,))
    assert api.requests[1]["messages"][-1]["content"] == "error: 'no evidence ev_1'"
    assert result.outcome == "ok"


def test_a_structured_answer_is_asked_for_alone_and_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pings = Pings()

    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        if "response_format" in body:
            return say('{"verdict": "supported"}')
        return call_tools(("ping", {})) if turns(body) == 0 else say("I think it is supported.")

    result, api = run(script, monkeypatch, tools=(pings.tool(),), output_schema=STRICT)

    assert result.outcome == "ok", result.detail
    assert result.structured == {"verdict": "supported"}
    assert result.turns == 3
    final = api.requests[-1]
    assert "tools" not in final
    assert final["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "strict": True, "schema": STRICT},
    }
    assert final["messages"][-1]["content"].startswith("Give your final answer now")


def test_the_last_turn_is_kept_for_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    pings = Pings()

    def script(body: Mapping[str, Any]) -> dict[str, Any]:  # it would look things up for ever
        return (
            say('{"verdict": "supported"}')
            if "response_format" in body
            else call_tools(("ping", {}))
        )

    result, api = run(script, monkeypatch, tools=(pings.tool(),), output_schema=STRICT)
    assert result.outcome == "ok", result.detail
    assert result.structured == {"verdict": "supported"}
    assert result.turns == 3  # two lookups, then the answer (the fourth turn for its retry)
    assert ["tools" in body for body in api.requests] == [True, True, False]
    assert api.requests[-1]["messages"][-1]["content"].startswith("Give your final answer now")


def test_an_answer_that_breaks_the_schema_is_retried_once_then_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        return say('{"verdict": "maybe"}') if "response_format" in body else say("hmm")

    result, api = run(script, monkeypatch, output_schema=STRICT)
    assert result.outcome == "invalid_output"
    assert result.structured is None
    assert "did not match the schema" in result.detail
    assert len(api.requests) == 2  # the answer and one retry (no tools: no conversation first)
    assert "did not match the schema" in api.requests[-1]["messages"][-1]["content"]


def test_strict_mode_only_for_schemas_it_can_take() -> None:
    assert strict_allowed(STRICT)
    assert not strict_allowed({"type": "object", "properties": {"a": {"type": "string"}}})
    loose = {**STRICT, "properties": {**STRICT["properties"], "note": {"type": "string"}}}
    assert not strict_allowed(loose)  # "note" is not required
    nested = {
        **STRICT,
        "properties": {"v": {"type": "object", "properties": {}}},
        "required": ["v"],
    }
    assert not strict_allowed(nested)  # the inner object allows other properties


def test_a_rate_limit_waits_for_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(body: Mapping[str, Any]) -> dict[str, Any] | Failure:
        if len(api_requests) == 0:
            api_requests.append(body)
            return Failure(429, "rate limit", {"retry-after": "0.2"})
        return say("ok")

    api_requests: list[Any] = []
    started = time.monotonic()
    seen: list[Progress] = []
    result, api = run(script, monkeypatch, progress=seen)
    assert result.outcome == "ok"
    assert len(api.requests) == 2
    assert time.monotonic() - started >= 0.2
    said = [p.detail for p in seen if p.detail and "asking again" in p.detail]
    assert said == ["rate limited (429); asking again in 0 s (attempt 2 of 2)"]


def test_a_wait_past_the_calls_time_ends_it_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A spent daily limit answers "retry after" in tens of minutes (1,287 s seen on Groq): a
    call that cannot wait so long says so now, instead of sleeping into a timeout."""
    started = time.monotonic()
    result, api = run(
        lambda body: Failure(429, "Rate limit reached: tokens per day", {"retry-after": "1287"}),
        monkeypatch,
    )
    assert time.monotonic() - started < 5
    assert result.outcome == "error"
    assert "asks to wait 1287 s, past this call's time" in (result.detail or "")
    assert len(api.requests) == 1


@pytest.mark.parametrize(("status", "retried"), [(500, True), (401, False), (400, False)])
def test_an_api_error_ends_the_call_without_the_key(
    monkeypatch: pytest.MonkeyPatch, status: int, retried: bool
) -> None:
    monkeypatch.setattr("repro.agents.openai_compat.BACKOFF_S", 0.01)
    result, api = run(lambda body: Failure(status, "nope"), monkeypatch)
    assert result.outcome == "error"
    assert result.detail.startswith(f"HTTP {status}: nope")
    assert KEY not in json.dumps(result.detail)
    assert len(api.requests) == (2 if retried else 1)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (b"<html>bad gateway</html>", "HTTP 0: the API's answer is not JSON"),
        (b'{"choices": []}', "HTTP 0: the API's answer has no choices"),
        (b'{"choices": [{"index": 0}]}', "HTTP 0: the API's answer has no message"),
    ],
)
def test_an_unusable_answer_is_asked_again_then_an_error(
    monkeypatch: pytest.MonkeyPatch, body: bytes, detail: str
) -> None:
    """H01: an answer that cannot be used (a proxy's error page, no choices) is a failure the
    call can recover from, never a crash of the job that made it."""
    monkeypatch.setattr("repro.agents.openai_compat.BACKOFF_S", 0.01)
    result, api = run(lambda b: Raw(body), monkeypatch)
    assert (result.outcome, result.detail) == ("error", detail)
    assert len(api.requests) == 2  # asked again once (the endpoint's retries)
    answers: Iterator[dict[str, Any] | Failure | Raw] = iter([Raw(body), say("ok")])
    result, api = run(lambda b: next(answers), monkeypatch)
    assert (result.outcome, result.text) == ("ok", "ok")


def test_an_api_that_cannot_be_reached_is_asked_again_then_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H01: a connection refused (an outage, a DNS failure) is retried like a 5xx."""
    monkeypatch.setattr("repro.agents.openai_compat.BACKOFF_S", 0.01)
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    attempts: list[str] = []
    real = openai_compat._post

    def counted(url: str, *args: Any) -> dict[str, Any]:
        attempts.append(url)
        return real(url, *args)

    monkeypatch.setattr(openai_compat, "_post", counted)
    closed = FakeOpenAIApi(lambda b: say("never"))
    end = endpoint(closed, base_url="http://127.0.0.1:9/v1")  # nothing listens on port 9
    result = asyncio.run(OpenAICompatibleBackend(end).run(request()))
    assert result.outcome == "error"
    assert result.detail.startswith("HTTP 0: cannot reach the API")
    assert KEY not in result.detail
    assert len(attempts) == 2


def test_no_key_means_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeOpenAIApi(lambda body: say("ok"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with api.serving():
        result = asyncio.run(OpenAICompatibleBackend(endpoint(api)).run(request()))
    assert (result.outcome, result.detail) == ("error", "HTTP 0: GROQ_API_KEY is not set")
    assert api.requests == []


def test_a_local_server_gets_no_key_and_an_unpriced_model_no_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, api = run(
        lambda body: say("ok"),
        monkeypatch,
        end={"api_key_env": None, "prices": {}, "reasoning_controls": False, "temperature": None},
        model="llama3.2",
    )
    assert api.keyed == [False]
    body = api.requests[0]
    assert "temperature" not in body
    assert "reasoning_effort" not in body
    assert result.usage.cost_usd == 0.0
    assert not result.by_model["llama3.2"].priced


def test_turns_budget_and_time_end_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    pings = Pings()
    looping, _ = run(lambda body: call_tools(("ping", {})), monkeypatch, tools=(pings.tool(),))
    assert (looping.outcome, looping.turns) == ("max_turns", 4)

    costly, _ = run(
        lambda body: call_tools(("ping", {})),
        monkeypatch,
        tools=(pings.tool(),),
        budget=Budget(max_turns=4, max_budget_usd=0.0001, timeout_s=30),
    )
    assert (costly.outcome, costly.turns) == ("max_budget", 1)

    def slow(body: Mapping[str, Any]) -> dict[str, Any]:
        time.sleep(1.5)
        return say("late")

    late, _ = run(slow, monkeypatch, budget=Budget(max_turns=4, timeout_s=0.5))
    assert late.outcome == "timeout"


def test_a_call_records_and_replays_through_a_cassette(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pings = Pings()

    def script(body: Mapping[str, Any]) -> dict[str, Any]:
        if "response_format" in body:
            return say('{"verdict": "supported"}')
        return call_tools(("ping", {"word": "b"})) if turns(body) == 0 else say("ok")

    monkeypatch.setenv("GROQ_API_KEY", KEY)
    api = FakeOpenAIApi(script)
    with api.serving():
        live = OpenAICompatibleBackend(endpoint(api))
        recorded = asyncio.run(
            CassetteBackend(tmp_path, "record", live).run(
                request(tools=(pings.tool(),), output_schema=STRICT)
            )
        )
    again = asyncio.run(
        CassetteBackend(tmp_path, "replay").run(
            request(tools=(pings.tool(),), output_schema=STRICT)
        )
    )
    assert recorded.structured == again.structured == {"verdict": "supported"}
    assert again.replayed
    assert (again.usage, dict(again.by_model)) == (recorded.usage, dict(recorded.by_model))
    assert pings.calls == [{"word": "b"}, {"word": "b"}]  # replay makes the tool call again
    assert len(api.requests) == 3


def test_a_call_with_a_schema_and_no_tools_asks_for_the_answer_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, api = run(
        lambda body: say('{"verdict": "supported"}'), monkeypatch, output_schema=STRICT
    )
    assert (result.outcome, result.structured, result.turns) == ("ok", {"verdict": "supported"}, 1)
    [body] = api.requests
    assert "response_format" in body
    assert "tools" not in body


def test_an_answer_the_api_refuses_as_off_schema_is_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Groq's strict mode answers a 400 "Failed to validate JSON" when the model's output does
    not fit: that is an invalid answer, asked again, not an outage."""
    replies: list[dict[str, Any] | Failure] = [
        Failure(400, "Failed to validate JSON. Please adjust your prompt."),
        say('{"verdict": "supported"}'),
    ]
    result, api = run(lambda body: replies.pop(0), monkeypatch, output_schema=STRICT)
    assert (result.outcome, result.structured) == ("ok", {"verdict": "supported"})
    assert len(api.requests) == 2
    assert "did not match the schema" in api.requests[1]["messages"][-1]["content"]


def test_a_tool_call_where_the_answer_was_due_is_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Groq refuses a tool call on the answer's turn (a 400 "Tool choice is none, but model
    called a tool", seen with gpt-oss): a slip, asked again, not an outage."""
    replies: list[dict[str, Any] | Failure] = [
        Failure(400, "Tool choice is none, but model called a tool"),
        say('{"verdict": "supported"}'),
    ]
    result, api = run(lambda body: replies.pop(0), monkeypatch, output_schema=STRICT)
    assert (result.outcome, result.structured) == ("ok", {"verdict": "supported"})
    assert "Call no tool now" in api.requests[1]["messages"][-1]["content"]


def test_two_answers_off_schema_are_an_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = run(
        lambda body: Failure(400, "Failed to validate JSON."), monkeypatch, output_schema=STRICT
    )
    assert result.outcome == "invalid_output"
