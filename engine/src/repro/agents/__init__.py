"""Reviewer agents: the LLM backend, its lockdown and dispatch (Stage G; ADR-0007).

``LLMBackend`` is the one way the engine reaches a model; ``AgentSdkBackend`` is its default,
the Claude Agent SDK under the lockdown in ``lockdown``; ``OpenAICompatibleBackend`` reaches
Groq or a local server (ADR-0016); and ``CassetteBackend`` records calls and replays them
offline. Prompts are versioned files (``prompts``). ``run_agent`` runs a call in one of a run's
dispatch slots, within its ``RunLedger``, and reports it as events.
``EvidenceTools`` are what agents read: the run's evidence and the change's files (G03).
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
from repro.agents.evidence import EvidenceView
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.sdk import AgentSdkBackend
from repro.agents.sources import RepoSources, SourceError
from repro.agents.tools import EvidenceTools, ToolInputError

__all__ = [
    "SLOTS",
    "AgentRequest",
    "AgentResult",
    "AgentSdkBackend",
    "Budget",
    "CassetteBackend",
    "CassetteError",
    "Dispatch",
    "Endpoint",
    "EvidenceTools",
    "EvidenceView",
    "LLMBackend",
    "MissingCassetteError",
    "OnProgress",
    "OpenAICompatibleBackend",
    "Outcome",
    "Progress",
    "RepoSources",
    "ReproTool",
    "Role",
    "RunLedger",
    "SourceError",
    "StaleCassetteError",
    "ToolInputError",
    "Usage",
    "concurrency_for",
    "default_concurrency",
    "run_agent",
]
