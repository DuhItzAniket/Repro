"""The model the study's systems and instruments call (J06).

Two backends, chosen with ``--backend``:

- ``groq`` (the default): Groq's OpenAI-compatible API on ``openai/gpt-oss-120b`` (ADR-0016),
  as Stage G's recordings and the J02 to J05 measurements were made. Its key comes from
  ``GROQ_API_KEY``.
- ``claude``: Repro's own Claude backend, the Claude Agent SDK locked down as every Repro agent
  call is (ADR-0007), on Claude Haiku 5.5. The owner chose it for the study on 2026-10-23. Its
  key comes from ``ANTHROPIC_API_KEY``, and calls are billed to the Console organisation the key
  belongs to: each call's configuration directory is new and holds no login (``lockdown``).

A cassette keys a call by its request, the model included, so one backend's recordings never
answer the other's calls.
"""

import argparse
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from repro.agents.backend import LLMBackend
from repro.agents.cassette import CassetteBackend
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.sdk import AgentSdkBackend
from repro.agents.setup import GROQ_MODEL

BACKENDS: Final = ("groq", "claude")
#: The model the study runs on Claude (the owner's choice, 2026-10-23).
CLAUDE_STUDY_MODEL: Final = "claude-haiku-5-5"
MODELS: Final[Mapping[str, str]] = {"groq": GROQ_MODEL, "claude": CLAUDE_STUDY_MODEL}
#: Where each backend's key is read from: an environment variable, never an argument.
KEYS: Final[Mapping[str, str]] = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def add_arguments(parser: argparse.ArgumentParser, *, model: bool = True) -> None:
    """``--backend``, and ``--model`` unless the command has its own."""
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default="groq",
        help="groq: openai/gpt-oss-120b, key in GROQ_API_KEY; claude: claude-haiku-5-5 through "
        "Repro's locked-down Agent SDK backend, key in ANTHROPIC_API_KEY",
    )
    if model:
        parser.add_argument("--model", help="the model; by default the backend's")


def resolve(args: argparse.Namespace) -> None:
    """Fills ``args.model`` with the backend's model when none was named."""
    if getattr(args, "model", None) is None:
        args.model = MODELS[args.backend]


def live(backend: str) -> LLMBackend:
    """A backend that reaches the model."""
    if backend == "claude":
        return AgentSdkBackend(Path(tempfile.mkdtemp(prefix="repro-bench-agents-")))
    return OpenAICompatibleBackend(Endpoint.groq())


def recording(mode: str, cassettes: Path, backend: str) -> LLMBackend:
    """``replay``: the cassettes alone, no model reached; else recorded calls replayed and the
    missing ones made live and recorded."""
    if mode == "replay":
        return CassetteBackend(cassettes, "replay")
    return CassetteBackend(cassettes, "record", live(backend))


def run_settings(backend: str, model: str | None = None) -> dict[str, str]:
    """The ``REPRO_*`` variables that put a ``repro run``'s agents on ``backend``: on Claude,
    every role on the study's model rather than ARCHITECTURE §10.1's mix."""
    if backend == "claude":
        return {"REPRO_AGENTS": "claude", "REPRO_AGENT_MODEL": model or CLAUDE_STUDY_MODEL}
    return {"REPRO_AGENTS": "groq", **({"REPRO_AGENT_MODEL": model} if model else {})}
