"""Repository-wide pytest configuration: Hypothesis profiles and shared fixtures."""

import difflib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

from refusing_proxy import RefusingProxy
from repro_events.schemas import SchemaSet, load_schema_set

# "ci" is derandomised so a CI failure reproduces exactly; "dev" explores new examples each run.
settings.register_profile("ci", derandomize=True, deadline=None, max_examples=200, print_blob=True)
settings.register_profile("dev", deadline=None, max_examples=100)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

# Fixture projects (D03) are target code with tests of their own, run only inside a sandbox.
collect_ignore_glob = ["engine/tests/data/*"]

#: Where a test that reaches for the model API without its own stand-in ends up: a loopback
#: port nothing listens on (9, the discard service), with a key that is not one (G02).
OFFLINE_API = "http://127.0.0.1:9"
OFFLINE_KEY = "sk-ant-offline-test-key"
#: Variables that would route the model API elsewhere or sign in as someone.
_MODEL_ACCESS = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CONFIG_DIR",
)
_PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "model_cli: starts the Claude Code CLI, behind a proxy that refuses and records every "
        "connection past loopback; the test fails if there was one",
    )
    config.addinivalue_line(
        "markers",
        "agent_eval: replays the reviewed pull requests for G09's thresholds (CI runs it in its "
        "own job: pytest -m agent_eval)",
    )
    config.addinivalue_line(
        "markers",
        "chaos: runs repro run end to end into a catalogued failure (H01; CI runs it in its own "
        "job: pytest -m chaos)",
    )


@pytest.fixture(scope="session")
def refusing_proxy() -> Iterator[RefusingProxy]:
    with RefusingProxy().serving() as proxy:
        yield proxy


@pytest.fixture(autouse=True)
def _offline_model_api(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[None]:
    """No test reaches a real model, or anything else past this machine, through the CLI.

    The API is a closed loopback port and the key a dummy, whatever the machine's own
    environment holds; the CLI's nonessential traffic (update checks, telemetry, feature
    flags) is off. A test marked ``model_cli`` also runs behind ``refusing_proxy`` and fails
    if the CLI tried to connect past loopback (G02's acceptance: the agent suite runs offline).
    """
    for name in _MODEL_ACCESS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", OFFLINE_API)
    monkeypatch.setenv("ANTHROPIC_API_KEY", OFFLINE_KEY)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    if request.node.get_closest_marker("model_cli") is None:
        yield
        return
    proxy: RefusingProxy = request.getfixturevalue("refusing_proxy")
    for name in _PROXY_VARIABLES:
        monkeypatch.setenv(name, proxy.url)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    before = len(proxy.attempts)
    yield
    reached = proxy.attempts[before:]
    if reached:
        pytest.fail(f"the CLI tried to connect past this machine: {reached}")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite golden files from the current output instead of comparing",
    )


class Golden:
    """Compare text with ``<test dir>/golden/<name>``; ``--update-goldens`` rewrites it.

    Text is compared with LF line endings and a trailing newline on every platform, so the
    same golden file passes on Windows and Linux.
    """

    def __init__(self, directory: Path, update: bool) -> None:
        self.directory = directory
        self.update = update

    def check(self, name: str, actual: str) -> None:
        path = self.directory / name
        text = actual.replace("\r\n", "\n")
        if not text.endswith("\n"):
            text += "\n"
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            return
        if not path.exists():
            pytest.fail(f"golden file {path} does not exist; run pytest with --update-goldens")
        expected = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if text != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    text.splitlines(keepends=True),
                    fromfile=f"{name} (golden)",
                    tofile=f"{name} (actual)",
                    n=2,
                )
            )
            pytest.fail(f"output differs from golden {path}:\n{diff[:8000]}")


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    return Golden(
        Path(request.path).parent / "golden", request.config.getoption("--update-goldens")
    )


@pytest.fixture(scope="session")
def schema_set() -> SchemaSet:
    """The event schema set of this source tree (packages/events/schema)."""
    return load_schema_set()
