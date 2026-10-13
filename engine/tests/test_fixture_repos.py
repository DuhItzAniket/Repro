"""The fixture-repository builder is deterministic and the fixtures behave as specified."""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS, HONEST_FIX

FIXTURES = Path(__file__).parent / "fixtures"

# Pinned: identical on Windows and Linux because content, identities and dates are fixed.
HONEST_FIX_BASE_SHA = "fe755e41c8d49ca8e2f60e44cd6eeb6e3ab93acc"
HONEST_FIX_HEAD_SHA = "44c5e145df93b6051f6a2fb2e795ceef189e9c0d"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_builds_are_byte_for_byte_reproducible(tmp_path: Path) -> None:
    first = build_repo(HONEST_FIX, tmp_path / "a" / "repo")
    second = build_repo(HONEST_FIX, tmp_path / "b" / "repo")
    assert first.base_sha == second.base_sha
    assert first.head_shas == second.head_shas


def test_commit_shas_are_platform_independent(tmp_path: Path) -> None:
    built = build_repo(HONEST_FIX, tmp_path / "repo")
    assert built.base_sha == HONEST_FIX_BASE_SHA
    assert built.head_shas == {"fix/parse-date-utc": HONEST_FIX_HEAD_SHA}


def test_files_are_committed_with_lf_line_endings(tmp_path: Path) -> None:
    built = build_repo(HONEST_FIX, tmp_path / "repo")
    blob = git(built.path, "cat-file", "-p", f"{built.base_sha}:pkg/dates.py")
    assert "\r" not in blob


def test_head_changes_only_the_declared_files(tmp_path: Path) -> None:
    built = build_repo(HONEST_FIX, tmp_path / "repo")
    head = built.head_shas["fix/parse-date-utc"]
    changed = git(built.path, "diff", "--name-only", built.base_sha, head).splitlines()
    assert changed == ["pkg/dates.py"]
    assert git(built.path, "status", "--porcelain") == ""


@pytest.mark.parametrize(("ref", "expected_returncode"), [("main", 1), ("fix/parse-date-utc", 0)])
def test_honest_fix_tests_fail_on_base_and_pass_on_head(
    tmp_path: Path, ref: str, expected_returncode: int
) -> None:
    # The fixture is our own synthetic code, so running it here is safe.
    built = build_repo(HONEST_FIX, tmp_path / "repo")
    git(built.path, "checkout", "-q", ref)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=built.path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == expected_returncode, completed.stdout


@pytest.mark.parametrize("name", sorted(ALL_SPECS))
def test_every_spec_has_an_expectation_file(name: str) -> None:
    expectation = tomllib.loads((FIXTURES / f"{name}.toml").read_text(encoding="utf-8"))
    assert expectation["fixture"]["name"] == name
    assert expectation["fixture"]["head"] in ALL_SPECS[name].heads
    assert expectation["expected"]["status"] in {"VERIFIED", "FLAGGED", "UNVERIFIABLE"}
