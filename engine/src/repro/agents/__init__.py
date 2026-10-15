"""Reviewer agents: the LLM backend, its lockdown and dispatch (Stage G; ADR-0007).

``LLMBackend`` is the one way the engine reaches a model; ``AgentSdkBackend`` is its default,
the Claude Agent SDK under the lockdown in ``lockdown``, and ``CassetteBackend`` records calls
and replays them offline. Prompts are versioned files (``prompts``). ``run_agent`` runs a call
in one of a run's dispatch slots, within its ``RunLedger``, and reports it as events.
"""

from repro.agents.backend import (
    AgentRequest,
    AgentResult,
    Budget,
    LLMBackend,
    OnProgress,
    Outcome,
    Progress,
    ReproTool,
    Role,
    Usage,
)
from repro.agents.cassette import (
    CassetteBackend,
    CassetteError,
    MissingCassetteError,
    StaleCassetteError,
)
from repro.agents.cost import RunLedger
from repro.agents.dispatch import SLOTS, Dispatch, concurrency_for, default_concurrency
from repro.agents.events import run_agent
from repro.agents.sdk import AgentSdkBackend

__all__ = [
    "SLOTS",
    "AgentRequest",
    "AgentResult",
    "AgentSdkBackend",
    "Budget",
    "CassetteBackend",
    "CassetteError",
    "Dispatch",
    "LLMBackend",
    "MissingCassetteError",
    "OnProgress",
    "Outcome",
    "Progress",
    "ReproTool",
    "Role",
    "RunLedger",
    "StaleCassetteError",
    "Usage",
    "concurrency_for",
    "default_concurrency",
    "run_agent",
]
