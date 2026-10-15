"""Reviewer agents: the LLM backend, its lockdown and dispatch (Stage G; ADR-0007).

``LLMBackend`` is the one way the engine reaches a model; ``AgentSdkBackend`` is its default,
the Claude Agent SDK under the lockdown in ``lockdown``. ``run_agent`` runs a call in one of a
run's dispatch slots and reports it as ``agent.*`` events.
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
from repro.agents.dispatch import SLOTS, Dispatch, concurrency_for, default_concurrency
from repro.agents.events import run_agent
from repro.agents.sdk import AgentSdkBackend

__all__ = [
    "SLOTS",
    "AgentRequest",
    "AgentResult",
    "AgentSdkBackend",
    "Budget",
    "Dispatch",
    "LLMBackend",
    "OnProgress",
    "Outcome",
    "Progress",
    "ReproTool",
    "Role",
    "Usage",
    "concurrency_for",
    "default_concurrency",
    "run_agent",
]
