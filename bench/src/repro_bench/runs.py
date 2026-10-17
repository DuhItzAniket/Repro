"""Reviewed runs of the labelled pull requests that have a fixture repository (G09).

Each is built afresh from its spec (``engine/tests/fixtures``) and run end to end with
``repro run``, its agents on Groq, in one of three modes:

- ``replay`` (the default, and CI): the calls recorded in ``engine/tests/cassettes``; a call
  with no recording fails the run's agent;
- ``record``: recorded calls replayed, missing ones made live and recorded;
- ``live``: every call made, nothing recorded.

``record`` and ``live`` need ``GROQ_API_KEY`` in the environment. A run's events are read back
from its own data directory.
"""

import importlib
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.store import StoreReader
from repro_bench.claims import Item
from repro_bench.results import ROOT

TESTS: Final = ROOT / "engine" / "tests"
CASSETTES: Final = TESTS / "cassettes"
#: The pull requests reviewed end to end: Gate G's three, the injection twin, and G07's.
REVIEWED: Final = ("honest-fix", "injection", "silent-change", "false-claim", "probe-semantic")
RUN_TIMEOUT_S: Final = 3600


@dataclass(frozen=True, slots=True)
class Run:
    name: str
    exit_code: int
    events: list[dict[str, Any]]
    output: str

    @property
    def card(self) -> dict[str, Any]:
        (card,) = [e["payload"]["card"] for e in self.events if e["kind"] == "card.published"]
        return dict(card)


def expected_status(name: str) -> str:
    """The card status the fixture's expectation names (with its claims judged)."""
    found = tomllib.loads((TESTS / "fixtures" / f"{name}.toml").read_text(encoding="utf-8"))
    return str(found["expected"]["status"])


def build(name: str, dest: Path) -> tuple[Path, str, str]:
    """The fixture's repository at ``dest``: its path, base and head commits."""
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    specs = importlib.import_module("fixtures.specs")
    builder = importlib.import_module("fixtures.repo_builder")
    expected = tomllib.loads((TESTS / "fixtures" / f"{name}.toml").read_text(encoding="utf-8"))
    built = builder.build_repo(specs.ALL_SPECS[name], dest)
    return Path(built.path), str(built.base_sha), str(built.head_shas[expected["fixture"]["head"]])


def run(
    item: Item,
    work: Path,
    *,
    mode: str = "replay",
    cassettes: Path = CASSETTES,
    settings: Mapping[str, str] | None = None,
) -> Run:
    """``item``'s fixture built and run in ``work`` with its PR text and the agents on;
    ``settings``: more ``REPRO_*`` variables (``REPRO_AGENT_ORDER_SWAP``, say)."""
    repo, base, head = build(item.name, work / "repo")
    data = work / "data"
    env = {k: v for k, v in os.environ.items() if not k.startswith("REPRO_")}
    env |= {
        "REPRO_DATA_DIR": str(data),
        "REPRO_RUN_ROOT": str(work / "scratch"),
        "REPRO_SANDBOX": "process",
        "REPRO_AGENTS": "groq",
        "REPRO_AGENT_MODE": mode,
        "REPRO_AGENT_CASSETTES": str(cassettes),
        "REPRO_LOG_FORMAT": "text",
        **(settings or {}),
    }
    argv = [sys.executable, "-m", "repro", "run", "--repo", str(repo), "--base", base]
    argv += ["--head", head, "--pr-title", item.title, "--pr-body", item.description]
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [*argv, "--no-serve"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    with StoreReader(data / "repro.db") as reader:
        (stored,) = reader.runs(1)
        events = [json.loads(event.body) for event in reader.iter_events(stored.id)]
    return Run(item.name, done.returncode, events, done.stdout[-4000:] + done.stderr[-4000:])
