"""Cassettes: agent calls recorded once, then replayed offline (G02; ARCHITECTURE §10.5).

A cassette holds one agent call: what was asked (the request, kept for review), what happened
(the model's progress and the Repro tools it called, with what each returned, in order) and
how it ended (the result). It is keyed by the prompt's version, the model and a digest of the
input, and stored at ``<root>/<prompt name>/<prompt version>/<model>/<digest>.json``.

**Run-specific identifiers.** Evidence, event and run IDs are ULIDs drawn afresh in every run,
and prompts carry them, so the same call made in two runs differs in its IDs and nothing else.
The digest is taken over the input with each distinct ID replaced by its kind and the order it
was first seen in (``ev_#1``, ``run_#2``, ...), so the same call in another run has the same
digest. On replay, the recording's IDs are mapped to the current run's by that order, in the
tool calls made again, the progress shown and the answer: an ``ev_`` ID the answer cites is the
current run's. An ID the model made up, never seen in its input, is left as it is.

**Replay never reaches a model**: ``replay`` mode has no other backend to call. A missing
cassette raises ``MissingCassetteError``, so a test without its recording fails instead of calling
the API. The recorded tool calls are made again with the current run's tools, and each must
return what it returned when recorded (IDs normalised); otherwise ``StaleCassetteError``: the
evidence the model saw has changed, and so might its answer.

**Recording** (``record`` mode) serves a call from its cassette when one exists and is still
true (not stale), and otherwise makes it through the given backend, writes the cassette and
returns the result: recording a run again calls the model only for what is new or changed, and
leaves the rest as it was (delete a cassette to record it again). A call that ends in
``timeout`` or ``error`` is not recorded: that is the infrastructure, not the model.
Cassettes are canonical JSON (sorted keys, two-space indent, LF), scrubbed of credentials like
every event (``repro.scrub``) and of the home directory (written ``~``), and hold no recording
time, so a cassette changes only when the call does.
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from importlib import metadata
from pathlib import Path
from typing import Any, Final, Literal

from repro.agents.backend import (
    AgentRequest,
    AgentResult,
    LLMBackend,
    OnProgress,
    Progress,
    ReproTool,
    Usage,
)
from repro.agents.untrusted import without_home
from repro.scrub import scrub

CASSETTE_VERSION: Final = 1
#: The run-specific identifiers a call's input can carry (the event schema's ``RunId``,
#: ``EventId`` and ``EvidenceId``).
RUN_SPECIFIC_ID: Final = re.compile(r"\b(ev|evt|run)_[0-9A-HJKMNP-TV-Z]{26}\b")
#: Outcomes that say something about the infrastructure, not the model: never recorded.
UNRECORDED: Final = frozenset({"timeout", "error"})
_PATH_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]")

Mode = Literal["replay", "record"]


class CassetteError(Exception):
    """A cassette that cannot serve the call."""


class MissingCassetteError(CassetteError, LookupError):
    """No cassette for this call: in replay mode the call is never made."""


class StaleCassetteError(CassetteError):
    """A tool returned something other than what the model saw when the call was recorded."""


@dataclass(slots=True)
class Ids:
    """The run-specific IDs of one call, in the order they were first seen."""

    seen: list[str] = field(default_factory=list)
    _index: dict[str, int] = field(default_factory=dict)

    def normalise(self, text: str) -> str:
        """``text`` with each ID replaced by its kind and its first-seen position; IDs not
        seen before are added."""

        def placeholder(match: re.Match[str]) -> str:
            ident = match.group(0)
            if ident not in self._index:
                self._index[ident] = len(self.seen)
                self.seen.append(ident)
            return f"{match.group(1)}_#{self._index[ident] + 1}"

        return RUN_SPECIFIC_ID.sub(placeholder, text)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _input(request: AgentRequest) -> dict[str, Any]:
    """What the model is given, which decides what it does. Not the budget: a run's ledger
    can lower a call's dollar budget without changing the call."""
    return {
        "role": request.role,
        "system_prompt": request.system_prompt,
        "prompt": request.prompt,
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)}
            for t in request.tools
        ],
        "output_schema": dict(request.output_schema) if request.output_schema is not None else None,
        "effort": request.effort,
    }


def _normalised(value: Any, ids: Ids) -> Any:
    """``value`` with the IDs in its strings normalised, keys and values in the order the
    canonical JSON writes them. Each string is normalised as it is, not as JSON writes it: an
    ID right after a line break would follow the ``\\n`` escape's ``n``, where the pattern's
    word boundary does not match, and stay as it is."""
    if isinstance(value, str):
        return ids.normalise(value)
    if isinstance(value, dict):
        return {ids.normalise(key): _normalised(value[key], ids) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalised(item, ids) for item in value]
    return value


def input_digest(request: AgentRequest, ids: Ids | None = None) -> str:
    """The SHA-256 of the call's input, its run-specific IDs normalised (into ``ids``)."""
    found = ids if ids is not None else Ids()
    return _sha256(_canonical(_normalised(_input(request), found)))


@dataclass(frozen=True, slots=True)
class CassetteKey:
    prompt_version: str
    model: str
    input_sha256: str

    @classmethod
    def of(cls, request: AgentRequest, ids: Ids | None = None) -> "CassetteKey":
        return cls(request.prompt_version, request.model, input_digest(request, ids))

    def path(self, root: Path) -> Path:
        name, version = self.prompt_version.split("/")
        model = _PATH_UNSAFE.sub("_", self.model)
        return root / name / version / model / f"{self.input_sha256}.json"

    def as_dict(self) -> dict[str, str]:
        return {
            "prompt_version": self.prompt_version,
            "model": self.model,
            "input_sha256": self.input_sha256,
        }


def _translate(text: str, mapping: Mapping[str, str]) -> str:
    """The recording's IDs in ``text`` as the current run's; IDs it never saw stay."""
    return RUN_SPECIFIC_ID.sub(lambda match: mapping.get(match.group(0), match.group(0)), text)


def _translate_json(value: Any, mapping: Mapping[str, str]) -> Any:
    return json.loads(_translate(json.dumps(value, ensure_ascii=False), mapping))


def _usage(value: Mapping[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(value["input_tokens"]),
        output_tokens=int(value["output_tokens"]),
        cache_read_tokens=int(value["cache_read_tokens"]),
        cost_usd=float(value["cost_usd"]),
        priced=bool(value.get("priced", True)),
    )


def _usage_dict(usage: Usage) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cost_usd": usage.cost_usd,
        "priced": usage.priced,
    }


def _versions() -> dict[str, str]:
    """What the call was recorded with: the Agent SDK and the CLI it bundles."""
    try:
        sdk = metadata.version("claude-agent-sdk")
        from claude_agent_sdk._cli_version import __cli_version__  # noqa: PLC0415 - optional

        return {"claude_agent_sdk": sdk, "claude_code": str(__cli_version__)}
    except (metadata.PackageNotFoundError, ImportError):
        return {}


def _unhomed(value: Any) -> Any:
    """``value`` with the user's home directory written ``~`` in every string: a cassette is
    committed, and must not carry the machine it was recorded on (G03)."""
    if isinstance(value, str):
        return without_home(value)
    if isinstance(value, dict):
        return {key: _unhomed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unhomed(item) for item in value]
    return value


def _write(path: Path, document: Mapping[str, Any]) -> None:
    """Writes the cassette whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    handle, temporary = tempfile.mkstemp(prefix=".cassette-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class _Recorder:
    """Collects one call's transcript as it happens: progress and tool calls, in order."""

    def __init__(self, ids: Ids, on_progress: OnProgress | None) -> None:
        self.ids = ids
        self.on_progress = on_progress
        self.transcript: list[dict[str, Any]] = []

    def progress(self, update: Progress) -> None:
        self.transcript.append(
            {
                "progress": {
                    "state": update.state,
                    "turn": update.turn,
                    "tool": update.tool,
                    "detail": update.detail,
                }
            }
        )
        if self.on_progress is not None:
            self.on_progress(update)

    def wrap(self, spec: ReproTool) -> ReproTool:
        async def handle(arguments: Mapping[str, Any]) -> str:
            try:
                output = await spec.handler(arguments)
            except Exception as exc:
                self._tool(spec.name, arguments, str(exc), error=True)
                raise
            self._tool(spec.name, arguments, output, error=False)
            return output

        return replace(spec, handler=handle)

    def _tool(self, name: str, arguments: Mapping[str, Any], output: str, *, error: bool) -> None:
        call = {
            "name": name,
            "input": dict(arguments),
            "output": output,
            "output_sha256": _sha256(self.ids.normalise(output)),
            "error": error,
        }
        self.transcript.append({"tool": call})


class CassetteBackend:
    """An ``LLMBackend`` over cassettes in ``root``: ``replay`` serves recorded calls only;
    ``record`` makes each call through ``backend`` and records it."""

    def __init__(self, root: Path, mode: Mode, backend: LLMBackend | None = None) -> None:
        if mode == "record" and backend is None:
            raise ValueError("recording needs a backend to make the calls")
        if mode == "replay" and backend is not None:
            raise ValueError("replay never makes a call: give it no backend")
        self.root = root
        self.mode = mode
        self.backend = backend

    async def run(
        self, request: AgentRequest, on_progress: OnProgress | None = None
    ) -> AgentResult:
        if self.mode == "record":
            return await self._record(request, on_progress)
        return await self._replay(request, on_progress)

    async def _record(self, request: AgentRequest, on_progress: OnProgress | None) -> AgentResult:
        assert self.backend is not None  # noqa: S101 - the constructor guarantees it
        if CassetteKey.of(request).path(self.root).exists():
            try:
                return await self._replay(request, on_progress)
            except StaleCassetteError:
                pass  # the evidence changed since: record the call again
        ids = Ids()
        key = CassetteKey.of(request, ids)
        recorder = _Recorder(ids, on_progress)
        recorded = replace(request, tools=tuple(recorder.wrap(t) for t in request.tools))
        result = await self.backend.run(recorded, recorder.progress)
        if result.outcome in UNRECORDED:
            return result
        document = {
            "cassette": CASSETTE_VERSION,
            "key": key.as_dict(),
            "request": {**_input(request), "budget": _budget(request)},
            "ids": list(ids.seen),
            "transcript": recorder.transcript,
            "result": {
                "outcome": result.outcome,
                "structured": result.structured,
                "text": result.text,
                "turns": result.turns,
                "usage": _usage_dict(result.usage),
                "by_model": {m: _usage_dict(u) for m, u in sorted(result.by_model.items())},
                "detail": result.detail,
                "tool_calls": [[name, allowed] for name, allowed in result.tool_calls],
            },
            "recorded_with": _versions(),
        }
        _write(key.path(self.root), _unhomed(scrub(document)))
        return result

    def _load(self, key: CassetteKey) -> dict[str, Any]:
        path = key.path(self.root)
        try:
            document: dict[str, Any] = json.loads(path.read_bytes())
        except FileNotFoundError:
            raise MissingCassetteError(
                f"no cassette for {key.prompt_version} on {key.model}, input "
                f"{key.input_sha256[:12]}: expected {path}; record it and commit it"
            ) from None
        except (OSError, ValueError) as exc:
            raise CassetteError(f"{path}: cannot be read: {exc}") from None
        if document.get("cassette") != CASSETTE_VERSION or document.get("key") != key.as_dict():
            raise CassetteError(f"{path}: not a version {CASSETTE_VERSION} cassette for this call")
        return document

    async def _replay(self, request: AgentRequest, on_progress: OnProgress | None) -> AgentResult:
        ids = Ids()
        document = self._load(CassetteKey.of(request, ids))
        recorded_ids: list[str] = document["ids"]
        tools = {t.name: t for t in request.tools}

        def mapping() -> dict[str, str]:
            return dict(zip(recorded_ids, ids.seen, strict=False))

        for entry in document["transcript"]:
            if "progress" in entry:
                step = entry["progress"]
                if on_progress is not None:
                    detail = step["detail"]
                    on_progress(
                        Progress(
                            step["state"],
                            int(step["turn"]),
                            step["tool"],
                            _translate(detail, mapping()) if detail is not None else None,
                        )
                    )
                continue
            await _call_again(entry["tool"], tools, ids, mapping())
        final = mapping()
        result = document["result"]
        structured = result["structured"]
        return AgentResult(
            outcome=result["outcome"],
            structured=_translate_json(structured, final) if structured is not None else None,
            text=_translate(result["text"], final),
            turns=int(result["turns"]),
            usage=_usage(result["usage"]),
            detail=_translate(result["detail"], final),
            tool_calls=tuple((str(name), bool(allowed)) for name, allowed in result["tool_calls"]),
            by_model={model: _usage(usage) for model, usage in result["by_model"].items()},
            replayed=True,
        )


def _budget(request: AgentRequest) -> dict[str, float]:
    budget = request.budget
    return {
        "max_turns": budget.max_turns,
        "max_budget_usd": budget.max_budget_usd,
        "timeout_s": budget.timeout_s,
    }


async def _call_again(
    call: Mapping[str, Any], tools: Mapping[str, ReproTool], ids: Ids, mapping: Mapping[str, str]
) -> None:
    """Makes a recorded tool call again; it must return what it returned then."""
    name = str(call["name"])
    tool = tools.get(name)
    if tool is None:
        raise StaleCassetteError(f"the recording called {name}, which this call does not have")
    arguments = _translate_json(call["input"], mapping)
    try:
        output, error = await tool.handler(arguments), False
    except Exception as exc:  # noqa: BLE001 - compared with what was recorded
        output, error = str(exc), True
    if error != bool(call["error"]) or _sha256(ids.normalise(output)) != call["output_sha256"]:
        raise StaleCassetteError(
            f"{name}({json.dumps(arguments, ensure_ascii=False)[:200]}) no longer returns what "
            "the model saw when the call was recorded: record the call again"
        )
