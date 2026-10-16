"""A run's agents from the settings: backend, mode, models, limits (G04)."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from repro.agents import AgentSdkBackend, CassetteBackend, OpenAICompatibleBackend
from repro.agents.setup import CLAUDE_MODELS, GROQ_MODEL, ROLES, agent_setup
from repro.config import Settings


def settings(tmp_path: Path, **fields: Any) -> Settings:
    return Settings(data_dir=tmp_path / "data", run_root=tmp_path / "runs", **fields)


def test_agents_are_off_unless_asked_for(tmp_path: Path) -> None:
    assert settings(tmp_path).agents == "off"
    assert agent_setup(settings(tmp_path), tmp_path) is None


def test_groq_runs_every_role_on_gpt_oss_one_call_at_a_time(tmp_path: Path) -> None:
    setup = agent_setup(settings(tmp_path, agents="groq"), tmp_path)
    assert setup is not None
    assert isinstance(setup.backend, OpenAICompatibleBackend)
    assert setup.backend.endpoint.base_url == "https://api.groq.com/openai/v1"
    assert setup.dispatch.concurrency == 1
    assert {setup.model(role) for role in ROLES} == {GROQ_MODEL}
    assert setup.ledger.limit_usd == 2.0
    assert setup.label == "groq (live)"


def test_claude_runs_each_role_on_its_model(tmp_path: Path) -> None:
    setup = agent_setup(settings(tmp_path, agents="claude", agent_budget_usd=5), tmp_path)
    assert setup is not None
    assert isinstance(setup.backend, AgentSdkBackend)
    assert dict(setup.models) == dict(CLAUDE_MODELS)
    assert setup.ledger.limit_usd == 5


def test_the_probe_writer_runs_unless_switched_off(tmp_path: Path) -> None:
    on = agent_setup(settings(tmp_path, agents="groq"), tmp_path)
    off = agent_setup(settings(tmp_path, agents="groq", agent_probes="off"), tmp_path)
    assert on is not None
    assert off is not None
    assert (on.probes, off.probes) == (True, False)


def test_one_model_for_every_role(tmp_path: Path) -> None:
    setup = agent_setup(
        settings(tmp_path, agents="claude", agent_model="claude-sonnet-5-5"), tmp_path
    )
    assert setup is not None
    assert {setup.model(role) for role in ROLES} == {"claude-sonnet-5-5"}


def test_an_openai_compatible_endpoint(tmp_path: Path) -> None:
    setup = agent_setup(
        settings(
            tmp_path,
            agents="openai",
            agent_base_url="http://127.0.0.1:11434/v1",
            agent_model="llama3.2",
        ),
        tmp_path,
    )
    assert setup is not None
    assert isinstance(setup.backend, OpenAICompatibleBackend)
    assert (setup.backend.endpoint.base_url, setup.backend.endpoint.api_key_env) == (
        "http://127.0.0.1:11434/v1",
        None,
    )
    assert setup.model("review") == "llama3.2"


def test_recording_wraps_the_backend_and_replay_has_none(tmp_path: Path) -> None:
    cassettes = tmp_path / "cassettes"
    recording = agent_setup(
        settings(tmp_path, agents="groq", agent_mode="record", agent_cassettes=cassettes), tmp_path
    )
    assert recording is not None
    assert isinstance(recording.backend, CassetteBackend)
    assert recording.backend.mode == "record"
    assert isinstance(recording.backend.backend, OpenAICompatibleBackend)

    replaying = agent_setup(
        settings(tmp_path, agents="groq", agent_mode="replay", agent_cassettes=cassettes), tmp_path
    )
    assert replaying is not None
    assert isinstance(replaying.backend, CassetteBackend)
    assert (replaying.backend.mode, replaying.backend.backend) == ("replay", None)
    assert replaying.label == "groq (replay)"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"agents": "openai"}, "agent_base_url and agent_model"),
        ({"agents": "openai", "agent_base_url": "http://x/v1"}, "agent_base_url and agent_model"),
        ({"agents": "groq", "agent_mode": "replay"}, "needs agent_cassettes"),
        ({"agents": "groq", "agent_budget_usd": 0}, "greater than 0"),
        ({"agents": "gpt"}, "Input should be"),
        ({"agent_cassettes": Path("relative")}, "absolute path"),
    ],
)
def test_incomplete_agent_settings_are_refused(
    tmp_path: Path, fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(tmp_path, **fields)
