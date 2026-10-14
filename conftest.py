"""Repository-wide pytest configuration: Hypothesis profiles and shared fixtures."""

import difflib
import os
from pathlib import Path

import pytest
from hypothesis import settings

from repro_events.schemas import SchemaSet, load_schema_set

# "ci" is derandomised so a CI failure reproduces exactly; "dev" explores new examples each run.
settings.register_profile("ci", derandomize=True, deadline=None, max_examples=200, print_blob=True)
settings.register_profile("dev", deadline=None, max_examples=100)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

# Fixture projects (D03) are target code with tests of their own, run only inside a sandbox.
collect_ignore_glob = ["engine/tests/data/*"]


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
