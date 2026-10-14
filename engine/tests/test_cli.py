import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repro import __version__
from repro.cli import NOT_YET, app

runner = CliRunner()


def test_version_comes_from_installed_metadata() -> None:
    assert __version__ == version("repro-engine")


def test_version_flag_prints_version_and_exits_cleanly() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"repro {__version__}\n"


def test_no_arguments_shows_usage() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_module_entry_point_runs_in_a_fresh_interpreter() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "repro", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"repro {__version__}"


def clean_env(tmp_path: Path, **variables: str) -> dict[str, str]:
    """The real environment without REPRO_* variables, with the data under ``tmp_path``."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("REPRO_")}
    return {**env, "REPRO_DATA_DIR": str(tmp_path / "data"), **variables}


@pytest.mark.parametrize(
    ("argv", "phase"),
    [
        (["run", "--repo", ".", "--base", "main", "--head", "fix"], "C03"),
        (["replay", "01J9ZQ4R6M3X8T2K5V7N0P1QWE"], "C08"),
        (["serve"], "C04"),
        (["export", "01J9ZQ4R6M3X8T2K5V7N0P1QWE", "--format", "sarif"], "F05"),
    ],
)
def test_unfinished_commands_say_so_and_exit_2(tmp_path: Path, argv: list[str], phase: str) -> None:
    result = runner.invoke(app, argv, env=clean_env(tmp_path))
    assert result.exit_code == NOT_YET
    assert "not available yet" in result.output
    assert phase in result.output


def test_run_requires_its_refs(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--repo", "."], env=clean_env(tmp_path))
    assert result.exit_code == 2
    assert "--base" in result.output


def test_a_configuration_error_stops_a_command_with_its_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["serve"], env=clean_env(tmp_path, REPRO_CONCURRENCY="lots"))
    assert result.exit_code == 2
    assert "configuration error: REPRO_CONCURRENCY" in result.output


def test_doctor_reports_a_configuration_error_and_still_checks(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"], env=clean_env(tmp_path, REPRO_SANDBOX="vm"))
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    first = report["checks"][0]
    assert (first["name"], first["status"]) == ("config", "fail")
    assert "REPRO_SANDBOX" in first["summary"]
    assert {check["name"] for check in report["checks"]} >= {"python", "git", "data dir"}


def test_doctor_prints_text_by_default(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor"], env=clean_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(f"repro {__version__} doctor - ")
    assert "Ready: every required check passed" in result.stdout


def test_global_options_override_the_environment(tmp_path: Path) -> None:
    other = tmp_path / "other"
    result = runner.invoke(
        app,
        ["--data-dir", str(other), "--log-format", "text", "doctor", "--json"],
        env=clean_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    data_dir = next(c for c in json.loads(result.stdout)["checks"] if c["name"] == "data dir")
    assert str(other) in data_dir["summary"]


def test_config_option_names_the_file(tmp_path: Path) -> None:
    config = tmp_path / "custom.toml"
    config.write_text('sandbox = "nonsense"\n', encoding="utf-8")
    result = runner.invoke(app, ["--config", str(config), "serve"], env=clean_env(tmp_path))
    assert result.exit_code == 2
    assert "custom.toml (sandbox)" in result.output
