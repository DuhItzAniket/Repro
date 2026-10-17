"""What leaves a run, audited for secrets and the home directory (H03; THREAT_MODEL T12).

One ``repro run`` with credentials of each kind Repro or its users hold in the host's
environment, on a target whose test prints the environment it sees and fails with a message
that holds a token. Then every place the run wrote is searched:
- the host's credentials are in no file under the data directory or the run root (the stored
  events, evidence and artifacts, and the target's own output), and not in Repro's output;
- the target's token, and the home directory, are in none of the events, nor in the card or
  its exports, which are what a user shares.

The raw artifacts (JUnit XML, the plugin's results) keep the target's output as it was, the
token included; they stay on this machine and the API serves them only with the session token
(T13). That is the residual risk THREAT_MODEL T12 states.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from cli_support import clean_env
from fixtures.repo_builder import RepoSpec, build_repo
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader

runner = CliRunner()

#: Built at run time: a literal credential in the repository would trip its secret scan.
HOST_SECRETS = {
    "GITHUB_TOKEN": "gh" + "p_" + "Z9y8" * 9,
    "ANTHROPIC_API_KEY": "sk-" + "ant-api03-" + "Qw3r" * 20,
    "GROQ_API_KEY": "gs" + "k_" + "Lp0o" * 13,
    "AWS_SECRET_ACCESS_KEY": "wJalr" + "XUtnFEMI" * 4,
}
TARGET_TOKEN = "gh" + "p_" + "q7R8" * 9

_CORE = """def total(items):
    return sum(items)
"""
_TEST = """import os

from calc.core import total


def test_total():
    print(sorted(os.environ.items()))  # all the target sees of the host
    token = "gh" + "p_" + "q7R8" * 9
    assert total([1, 2]) == 3, f"total failed while holding {token}"
"""
LEAKY = RepoSpec(
    name="leaky",
    description="A test that prints its environment and fails with a token in its message.",
    base={
        "pyproject.toml": '[project]\nname = "calc-fixture"\nversion = "0.1.0"\n',
        "calc/__init__.py": "",
        "calc/core.py": _CORE,
        "tests/test_core.py": _TEST,
    },
    heads={"break/total": {"calc/core.py": _CORE.replace("sum(items)", "sum(items) + 1")}},
)


def readable_files(*roots: Path) -> dict[Path, str]:
    """Every file under ``roots``, as text (undecodable bytes replaced)."""
    return {
        path: path.read_bytes().decode("utf-8", "replace")
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_nothing_secret_or_personal_leaves_a_run(tmp_path: Path) -> None:
    built = build_repo(LEAKY, tmp_path / "repo")
    [head] = built.head_shas.values()
    scratch = tmp_path / "scratch"
    env = clean_env(tmp_path, REPRO_SANDBOX="process", REPRO_RUN_ROOT=str(scratch), **HOST_SECRETS)
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    result = runner.invoke(app, [*argv, "--no-serve"], env=env)
    assert result.exit_code == 0, result.output
    paths = load_settings(env=env).paths
    with StoreReader(paths.database) as reader:
        (stored,) = reader.runs(10)
        events = [e.body for e in reader.events(stored.id, 0, 100_000)]
    exports = []
    for kind in ("md", "json"):
        exported = runner.invoke(app, ["export", stored.id, "--format", kind], env=env)
        assert exported.exit_code == 0, exported.output
        exports.append(exported.stdout)

    # The target failed as it should, holding its token, so the scrubbing had work to do.
    parsed = [json.loads(event) for event in events]
    outcomes = [e["payload"]["class"] for e in parsed if e["kind"] == "diff.outcome"]
    assert outcomes == ["P2F"]
    assert any("[redacted]" in event for event in events)

    written = readable_files(paths.data_dir, scratch)
    assert written, "the run wrote nothing to search"
    for name, value in HOST_SECRETS.items():
        assert value not in result.output, name
        leaks = [str(path) for path, text in written.items() if value in text]
        assert leaks == [], (name, leaks)
    home = str(Path.home())
    for shared in [*events, *exports]:
        assert TARGET_TOKEN not in shared
        assert home not in shared
        assert home.replace("\\", "/") not in shared
        assert json.dumps(home)[1:-1] not in shared  # as JSON escapes it
