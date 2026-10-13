import subprocess
import sys
from importlib.metadata import version

from typer.testing import CliRunner

from repro import __version__
from repro.cli import app

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
