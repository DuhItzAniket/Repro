# ADR-0016: A second LLM backend for OpenAI-compatible APIs (Groq, local models)

- **Status:** accepted (decided by the project owner on 2026-10-16: no Anthropic API key is
  available for Stage G; the owner provided a Groq API key, for Stage G's recordings and
  evaluation, and asked to proceed with the full stage)
- **Date:** 2026-10-16
- **Phase:** G10 (implemented there; used from G04 on)

## Context
The decided stack (CLAUDE.md, ADR-0007) reaches models through the Claude Agent SDK, behind the
`LLMBackend` protocol built in G01 so that the backend can change without the agent stages
changing. Stage G needs real model output: to record the cassettes CI replays (G02), to
measure the agents on a labelled set (G04, G09) and to close Gate G. That needs API access,
and its cost is the owner's to decide.

On 2026-10-16 the owner declined to use an Anthropic API key and provided a Groq key instead.
What Groq offers, read on 2026-10-16:
- an OpenAI-compatible Chat Completions API at `https://api.groq.com/openai/v1`, mostly
  compatible, without `logprobs`, `logit_bias`, `messages[].name` or `n` > 1; temperature 0 is
  converted to 1e-8 **[V console.groq.com/docs/openai]**;
- tool use on all hosted models, the application running the loop; tool calls arrive as
  `tool_calls` with JSON-string arguments; results return as `role: "tool"` messages matching
  the call's `id`; gpt-oss models do not make parallel calls **[V docs/tool-use]**;
- structured outputs with `response_format: {"type": "json_schema", "json_schema": {...,
  "strict": true}}` using constrained decoding on `openai/gpt-oss-20b`, `openai/gpt-oss-120b`,
  `qwen/qwen3.8-27b` and `meta-models/muse-spark-open`; strict mode needs every property
  required and `additionalProperties: false`; **structured outputs cannot be combined with
  tool use or streaming** **[V docs/structured-outputs]**;
- `reasoning_effort` low, medium or high on gpt-oss; reasoning in a separate `reasoning`
  field, which `include_reasoning: false` leaves out; temperature 0.5–0.7 recommended for
  reasoning models **[V docs/reasoning]**;
- on the base developer plan, per model: 30 requests and 8,000 tokens a minute, 1,000
  requests and 200,000 tokens a day; a 429 with `retry-after` when exceeded
  **[V docs/rate-limits]**;
- prices per million tokens, input and output: gpt-oss-120b $0.15 and $0.60, gpt-oss-20b
  $0.075 and $0.30, qwen3.8-27b $0.80 and $4.00 **[V console.groq.com/docs/model/…]**.

The key's account lists gpt-oss-120b, gpt-oss-20b and qwen3.8-27b among its chat models
(`GET /openai/v1/models`, 2026-10-16).

The same API shape is offered by local servers (Ollama, vLLM) and routers (OpenRouter), which
would let a user without any paid key run the agent stages on their own machine.

## Decision
1. Add `OpenAICompatibleBackend`, a second `LLMBackend`, for any OpenAI-compatible Chat
   Completions endpoint. Repro runs the agent loop itself: the request's tools are offered as
   functions, each call is answered from the request's own `ReproTool` handlers, and a call to
   any other name is refused (the equivalent of ADR-0007's gate: there is no CLI, file system
   or other tool to reach). With an output schema, the loop's last step asks for the answer
   alone with `response_format` `json_schema` (strict where the schema allows), since the API
   cannot combine it with tools; the answer is validated against the schema before it is
   accepted.
2. The Claude Agent SDK remains the default backend and the decided stack; nothing about
   ADR-0007 changes.
3. Stage G's recordings and its evaluation use Groq's `openai/gpt-oss-120b` (owner's key).
   Every card, cassette and result states the model that produced it; results on one model
   are never reported as results on another.
4. The key is read from an environment variable when a call is made, never logged, written or
   committed. Tests never reach the API (G02's offline guard); a local stand-in for the
   OpenAI-compatible API drives the backend's own tests.
5. Costs are estimated from a price table with each entry's source and date; a model without
   a known price gets no `cost.estimate` rather than a made-up one (its tokens are still
   counted in the call's usage).

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| The owner's Anthropic API key | The decided stack, no second backend | Spend the owner declined | The owner's decision |
| Groq through its own SDK | Typed client | A new dependency for one provider; the OpenAI shape covers Groq, local servers and routers | Less general |
| The `openai` Python package | Maintained client | A new dependency for a few HTTP calls the standard library makes | Not needed |
| Leave Stage G unmeasured | No new code | Gate G cannot close; nothing about the agents is known | Defeats the stage |

## Consequences
- Two backends to keep working: both run the same `LLMBackend` tests where they apply, and
  cassettes record either.
- Agents are measured on an open-weight model. G09's numbers are about gpt-oss-120b; the
  same prompts on Claude models are unmeasured until someone records them, and the docs say so.
- Groq's free limits (8,000 tokens a minute) bound what one call may send: prompts and tool
  outputs must stay compact, Groq calls run one at a time, and recording a stage may take
  more than a day of quota.
- Revisit when the owner provides an Anthropic key, or when G09 shows the model cannot meet
  the thresholds.
