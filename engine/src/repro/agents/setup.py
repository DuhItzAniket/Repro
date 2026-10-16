"""What a run's agents run on: the backend, its mode, each role's model and the run's limits.

Built from the settings (G04) once per run. ``agents = "off"`` (the default) gives no setup: the
run is deterministic only, and no model is reached unless the user asks for one.

- ``claude``: the Claude Agent SDK, locked down (ADR-0007), each role on ARCHITECTURE §10.1's
  model; as many calls at once as ``repro.agents.dispatch`` allows.
- ``groq``: Groq's OpenAI-compatible API (ADR-0016), every role on ``openai/gpt-oss-120b``,
  one call at a time (its free limits are per minute).
- ``openai``: any OpenAI-compatible endpoint (``agent_base_url``, a key from
  ``agent_api_key_env`` or none), on ``agent_model``; one call at a time.

``agent_model`` puts every role on one model. The mode wraps the backend in cassettes (G02):
``record`` calls the model and writes them; ``replay`` builds no backend at all, so it cannot
reach a model, and a call without its cassette fails.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from repro.agents.backend import LLMBackend, Role
from repro.agents.cassette import CassetteBackend
from repro.agents.cost import RunLedger
from repro.agents.dispatch import Dispatch, default_concurrency
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.sdk import AgentSdkBackend
from repro.config import Settings

#: Each role's model on the Claude backend (ARCHITECTURE §10.1).
CLAUDE_MODELS: Final[Mapping[Role, str]] = {
    "read": "claude-haiku-5-5",
    "build": "claude-sonnet-5-5",
    "review": "claude-opus-5-5",
    "gap": "claude-opus-5-5",
    "probe": "claude-sonnet-5-5",
    "qa": "claude-opus-5-5",
}
#: The model every role uses on Groq (ADR-0016).
GROQ_MODEL: Final = "openai/gpt-oss-120b"
ROLES: Final[tuple[Role, ...]] = ("read", "build", "review", "gap", "probe", "qa")


@dataclass(frozen=True, slots=True)
class AgentSetup:
    """One run's agents: the backend to call, each role's model, and the run's limits."""

    backend: LLMBackend
    models: Mapping[Role, str]
    dispatch: Dispatch
    ledger: RunLedger
    #: What the backend is, for the log: ``groq (record)``, ``claude (replay)``...
    label: str

    def model(self, role: Role) -> str:
        return self.models[role]


def _live(settings: Settings, scratch: Path) -> tuple[LLMBackend, int]:
    """The backend that reaches the model, and how many of its calls may run at once."""
    if settings.agents == "claude":
        return AgentSdkBackend(scratch / "agents"), default_concurrency()
    if settings.agents == "groq":
        return OpenAICompatibleBackend(Endpoint.groq()), 1
    endpoint = Endpoint(str(settings.agent_base_url), settings.agent_api_key_env)
    return OpenAICompatibleBackend(endpoint), 1


def _models(settings: Settings) -> dict[Role, str]:
    if settings.agent_model:
        return dict.fromkeys(ROLES, settings.agent_model)
    if settings.agents == "claude":
        return dict(CLAUDE_MODELS)
    if settings.agents == "groq":
        return dict.fromkeys(ROLES, GROQ_MODEL)
    raise ValueError("agents = openai needs agent_model: an endpoint has no default model")


def agent_setup(settings: Settings, scratch: Path) -> AgentSetup | None:
    """The run's agents from the settings; None when they are off."""
    if settings.agents == "off":
        return None
    models = _models(settings)
    label = f"{settings.agents} ({settings.agent_mode})"
    ledger = RunLedger(settings.agent_budget_usd)
    cassettes = settings.agent_cassettes
    if settings.agent_mode == "replay":
        assert cassettes is not None  # noqa: S101 - the settings require it
        concurrency = 1 if settings.agents != "claude" else default_concurrency()
        return AgentSetup(
            CassetteBackend(cassettes, "replay"), models, Dispatch(concurrency), ledger, label
        )
    live, concurrency = _live(settings, scratch)
    if settings.agent_mode == "record":
        assert cassettes is not None  # noqa: S101 - the settings require it
        live = CassetteBackend(cassettes, "record", live)
    return AgentSetup(live, models, Dispatch(concurrency), ledger, label)
