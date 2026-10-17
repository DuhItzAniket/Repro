"""The project's own test selection, kept when Repro runs its tests (H02)."""

from pathlib import Path

import pytest

from repro.runner.pytest_config import addopts, kept, selection


def test_only_what_selects_or_collects_tests_is_kept() -> None:
    options = [
        "-ra", "-q", "-x", "--maxfail=2", "-n", "4", "--dist", "loadscope", "--cov=pkg",
        "--cov-report", "term", "--lf", "--durations=10", "--timeout", "30",
        "-m", "not slow", "-knot flaky", "--ignore=docs", "--ignore-glob", "*_old.py",
        "--deselect", "tests/t.py::a", "--import-mode=importlib", "--doctest-modules",
        "--doctest-glob", "*.rst", "--strict-markers", "--strict-config", "-W", "error",
        "--pythonwarnings=ignore::DeprecationWarning",
        "-p", "xdist", "-p", "no:legacypath", "-pno:cacheprovider", "-p=pytest_cov",
    ]  # fmt: skip
    assert kept(options) == [
        "-m", "not slow", "-knot flaky", "--ignore=docs", "--ignore-glob", "*_old.py",
        "--deselect", "tests/t.py::a", "--import-mode=importlib", "--doctest-modules",
        "--doctest-glob", "*.rst", "--strict-markers", "--strict-config", "-W", "error",
        "--pythonwarnings=ignore::DeprecationWarning",
        "-p", "no:legacypath", "-pno:cacheprovider",
    ]  # fmt: skip
    assert kept(["-m"]) == []  # a value missing: nothing to keep


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"pytest.ini": "[pytest]\naddopts = -m 'not stress' -ra\n"}, ["-m", "not stress", "-ra"]),
        ({".pytest.ini": "[pytest]\naddopts = -k fast\n"}, ["-k", "fast"]),
        (
            {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = \"-m 'not stress'\"\n"},
            ["-m", "not stress"],
        ),
        ({"pyproject.toml": '[tool.pytest]\naddopts = ["-m", "not slow"]\n'}, ["-m", "not slow"]),
        ({"tox.ini": "[pytest]\naddopts = --ignore=docs\n"}, ["--ignore=docs"]),
        ({"setup.cfg": "[tool:pytest]\naddopts = --strict-markers\n"}, ["--strict-markers"]),
        ({"pyproject.toml": '[project]\nname = "x"\n'}, []),  # no pytest table
        ({"pytest.ini": "[pytest]\naddopts = -m 'unclosed\n"}, []),  # pytest refuses it too
        ({}, []),
    ],
    ids=[
        "pytest.ini",
        ".pytest.ini",
        "ini_options",
        "native",
        "tox",
        "setup.cfg",
        "none",
        "unclosed",
        "nothing",
    ],
)
def test_the_file_pytest_would_use_is_read(
    tmp_path: Path, files: dict[str, str], expected: list[str]
) -> None:
    assert addopts(write(tmp_path, files)) == expected


def test_pytest_ini_wins_over_pyproject(tmp_path: Path) -> None:
    root = write(
        tmp_path,
        {
            "pytest.ini": "[pytest]\naddopts = -k first\n",
            "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-k second"\n',
            "setup.cfg": "[tool:pytest]\naddopts = -k third\n",
        },
    )
    assert selection(root) == ["-k", "first"]
    (root / "pytest.ini").unlink()
    assert selection(root) == ["-k", "second"]
