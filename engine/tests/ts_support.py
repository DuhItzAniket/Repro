"""The pinned TypeScript compiler for the tests (K11).

It is fetched once per checkout into pytest's cache (``.pytest_cache``, git-ignored), checked
against the registry's integrity as in a run, and reused by later sessions: nothing of it is in
the repository. Without the network on a first run the tests that need it are skipped, except in
CI (``CI`` set), where that is a failure.
"""

import os
import shutil
from pathlib import Path

import pytest

from repro.analysis import typescript

NODE = shutil.which("node")
NEEDS_NODE = pytest.mark.skipif(NODE is None, reason="needs node")


def tools(config: pytest.Config, factory: pytest.TempPathFactory) -> Path:
    """Where the tests keep Repro's fetched tools."""
    cache: pytest.Cache | None = getattr(config, "cache", None)  # None: -p no:cacheprovider
    if cache is not None:
        return cache.mkdir("repro-tools")
    return factory.mktemp("tools")


def pinned(config: pytest.Config, factory: pytest.TempPathFactory) -> Path:
    """The pinned compiler's package directory; the test is skipped if it cannot be fetched
    (outside CI)."""
    try:
        return typescript.ensure(tools(config, factory))
    except typescript.TypeScriptError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"the pinned TypeScript could not be fetched: {exc}")
