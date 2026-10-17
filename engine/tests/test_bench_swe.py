"""The SWE-format adapter and the evaluation's input contract (J01).

The contract test plants a canary in every field a system may not see, the instance's ID among
them, and runs Repro on the sealed input: no canary may reach the command line, the pull
request's text, the run's event log or its card.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cli_support import clean_env
from gitrepo import Repo
from repro.config import load_settings
from repro.gitops import Git
from repro.store import StoreReader
from repro_bench import swe

CANARIES = {
    "patch": "CANARY-GOLD-PATCH-7f3a",
    "test_patch": "CANARY-TEST-PATCH-91c2",
    "FAIL_TO_PASS": "CANARY-F2P-55d0",
    "PASS_TO_PASS": "CANARY-P2P-3b8e",
    "hints_text": "CANARY-HINTS-a14f",
    "created_at": "CANARY-CREATED-0c9d",
    "future_field": "CANARY-UNKNOWN-FIELD-e6b1",  # a field a dataset may add later
}
INSTANCE_ID = "CANARY-INSTANCE-ID-4d27"
BASE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def f():\n    return 1\n",
    "tests/test_core.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
}
HEAD = {"pkg/core.py": "def f():\n    return 2\n"}


def record(base: str, **changes: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "instance_id": INSTANCE_ID,
        "repo": "example/pkg",
        "base_commit": base,
        "problem_statement": "f returns the wrong value\n\nIt should return 2.",
        "patch": f"diff --git a/x b/x\n+{CANARIES['patch']}\n",
        "test_patch": f"diff --git a/t b/t\n+{CANARIES['test_patch']}\n",
        "FAIL_TO_PASS": json.dumps([f"tests/test_core.py::{CANARIES['FAIL_TO_PASS']}"]),
        "PASS_TO_PASS": [f"tests/test_core.py::{CANARIES['PASS_TO_PASS']}"],
        "hints_text": CANARIES["hints_text"],
        "created_at": CANARIES["created_at"],
        "future_field": CANARIES["future_field"],
        "docker_image": "swerebench/sweb.eval.x86_64.example_1776_pkg-1:latest",
    }
    return found | changes


@pytest.fixture
def target(tmp_path: Path) -> tuple[Repo, str, str]:
    """A repository with base and head, and the agent's diff between them."""
    repo = Repo(tmp_path / "upstream")
    base = repo.commit(BASE)
    head = repo.commit(HEAD)
    return repo, base, repo.git("diff", base, head) + "\n"


def prediction(diff: str, **changes: Any) -> dict[str, Any]:
    return {"instance_id": INSTANCE_ID, "model_name_or_path": "agent-x", "model_patch": diff} | (
        changes
    )


def leaked(text: str) -> list[str]:
    return [c for c in [*CANARIES.values(), INSTANCE_ID] if c in text]


def test_a_sealed_input_holds_the_allowed_fields_alone() -> None:
    instance = swe.Instance.from_record(record("a" * 40))
    sealed = swe.seal(instance, swe.Prediction.from_record(prediction("diff --git a/y b/y\n")))
    assert set(json.loads(sealed.canonical())) == {"repo", "base_commit", "diff", "claim"}
    assert leaked(sealed.canonical().decode()) == []
    assert leaked(swe.pr_file(sealed)) == []
    # Ground truth is kept apart, for the labelling (J02), and never in a sealed input.
    assert set(instance.truth) == set(swe.WITHHELD)
    assert "truth" not in repr(instance)


def test_the_claim_is_the_problem_statement_and_the_agents_summary() -> None:
    instance = swe.Instance.from_record(record("a" * 40))
    plain = swe.seal(instance, swe.Prediction.from_record(prediction("d")))
    assert plain.claim == "f returns the wrong value\n\nIt should return 2.\n\n" + swe.FIXED_CLAIM
    assert plain.title == "f returns the wrong value"
    summarised = swe.seal(
        instance, swe.Prediction.from_record(prediction("d", summary="Made f return 2."))
    )
    assert summarised.claim.endswith("\n\nMade f return 2.")
    assert summarised.digest != plain.digest


@pytest.mark.parametrize(
    ("given", "message"),
    [
        (prediction("d", instance_id="other-1"), "is not a prediction for"),
        (prediction("  \n"), "patch is empty"),
    ],
)
def test_a_prediction_that_does_not_fit_is_refused(given: dict[str, Any], message: str) -> None:
    instance = swe.Instance.from_record(record("a" * 40))
    with pytest.raises(swe.ContractError, match=message):
        swe.seal(instance, swe.Prediction.from_record(given))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"base_commit": "main"}, "base_commit is not a commit"),
        ({"repo": "../../etc"}, "repo"),
        ({"problem_statement": ""}, "needs problem_statement"),
    ],
)
def test_an_instance_that_breaks_the_contract_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(swe.ContractError, match=message):
        swe.Instance.from_record(record("a" * 40, **changes))


def test_a_sealed_file_that_was_changed_or_widened_is_refused() -> None:
    instance = swe.Instance.from_record(record("a" * 40))
    made = swe.Prediction.from_record(prediction("diff"))
    row = swe.Task(INSTANCE_ID, "agent-x", made.patch_sha256, swe.seal(instance, made)).row()
    assert swe.Task.from_row(row).input == swe.seal(instance, made)
    changed = row | {"input": row["input"] | {"diff": "other"}}
    with pytest.raises(swe.ContractError, match="was changed"):
        swe.Task.from_row(changed)
    widened = row | {"input": row["input"] | {"hints_text": "x"}}
    with pytest.raises(swe.ContractError, match="has exactly"):
        swe.Task.from_row(widened)


def test_the_head_is_the_base_with_the_diff_and_nothing_is_checked_out(
    tmp_path: Path, target: tuple[Repo, str, str]
) -> None:
    repo, base, diff = target
    mirror = tmp_path / "mirrors" / "example" / "pkg.git"
    git = swe.fetch_base(mirror, "example/pkg", base, source=str(repo.path))
    head = swe.head_commit(git, swe.Sealed("example/pkg", base, diff, "claim"))
    assert git.text("rev-parse", f"{head}^") == base
    assert git.run("show", f"{head}:pkg/core.py") == b"def f():\n    return 2\n"
    assert git.text("rev-parse", "--is-bare-repository") == "true"
    assert not (mirror / "pkg").exists()
    # The same input makes the same commit: fixed identity and dates.
    assert swe.head_commit(git, swe.Sealed("example/pkg", base, diff, "claim")) == head
    with pytest.raises(swe.ContractError, match="does not apply"):
        swe.head_commit(git, swe.Sealed("example/pkg", base, diff.replace("1", "7"), "claim"))


def test_a_base_commit_the_remote_does_not_have_is_named(
    tmp_path: Path, target: tuple[Repo, str, str]
) -> None:
    repo, _, _ = target
    with pytest.raises(swe.ContractError, match="fetching"):
        swe.fetch_base(tmp_path / "m.git", "example/pkg", "b" * 40, source=str(repo.path))


def test_no_withheld_field_reaches_repro(tmp_path: Path, target: tuple[Repo, str, str]) -> None:
    repo, base, diff = target
    (tmp_path / "instances.jsonl").write_text(json.dumps(record(base)) + "\n", encoding="utf-8")
    (tmp_path / "predictions.jsonl").write_text(
        json.dumps(prediction(diff)) + "\n", encoding="utf-8"
    )
    sealed_dir = tmp_path / "sealed"
    argv = ["seal", "--instances", str(tmp_path / "instances.jsonl"), "--predictions",
            str(tmp_path / "predictions.jsonl"), "--dataset", "example/swe", "--split", "test",
            "--revision", "c" * 40, "--out", str(sealed_dir)]  # fmt: skip
    assert swe.main(argv) == 0
    sealed_text = (sealed_dir / "sealed.jsonl").read_text(encoding="utf-8")
    assert leaked(sealed_text) == [INSTANCE_ID]  # the row's key, for results; never sent on
    (task,) = [swe.Task.from_row(json.loads(line)) for line in sealed_text.splitlines()]

    env = clean_env(tmp_path, REPRO_SANDBOX="process", REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    outcome = swe.run_task(
        task, tmp_path / "mirrors", tmp_path / "cards", env=env, extra=["--analyse-only"],
        source=str(repo.path),
    )  # fmt: skip
    assert outcome.run_id is not None, outcome.status
    assert outcome.input_sha256 == task.input.digest
    assert swe.repro_argv(task.input, Path("m"), "h" * 40, Path("pr.txt"))
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [event.body for event in reader.events(run.id, 0, 100_000)]
    started = json.loads(events[0])
    assert started["kind"] == "run.started"
    assert started["payload"]["pr"]["title"] == task.input.title  # the claim's title reached it
    card = (tmp_path / "cards" / f"{outcome.run_id}.json").read_text(encoding="utf-8")
    assert leaked("\n".join(events)) == []
    assert leaked(card) == []
    assert json.loads(card)["status"] == outcome.status


def test_the_manifest_pins_what_ran(tmp_path: Path) -> None:
    instance = swe.Instance.from_record(record("a" * 40))
    made = swe.Prediction.from_record(prediction("diff"))
    pinned_image = "swerebench/sweb.eval.x86_64.example_1776_pkg-1@sha256:" + "0" * 64
    kept = swe.entry(instance, made, dataset="d", split="s", revision="r", image=pinned_image)
    swe.write_manifest(tmp_path / "manifest.jsonl", [kept])
    assert swe.read_manifest(tmp_path / "manifest.jsonl") == [kept]
    with pytest.raises(swe.ContractError, match="not pinned by digest"):
        swe.entry(instance, made, dataset="d", split="s", revision="r", image=instance.image)
    (tmp_path / "bad.jsonl").write_text(
        json.dumps(json.loads(json.dumps(kept.__dict__)) | {"label": "PLAUSIBLE"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(swe.ContractError, match="label"):
        swe.read_manifest(tmp_path / "bad.jsonl")


@pytest.mark.parametrize(
    ("image", "name"),
    [
        ("swerebench/sweb.eval.x86_64.a-1:latest", "swerebench/sweb.eval.x86_64.a-1"),
        ("docker.io/library/python:3.13", "python"),
        ("localhost:5000/team/img:v1", "localhost:5000/team/img"),
        ("ghcr.io/o/i@sha256:" + "1" * 64, "ghcr.io/o/i"),
    ],
)
def test_an_image_reference_is_named_as_docker_records_it(image: str, name: str) -> None:
    assert swe.repository(image) == name


def test_an_image_is_pinned_by_the_digest_docker_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = "sha256:" + "2" * 64
    recorded = ["other/image@sha256:" + "3" * 64, f"swerebench/a-1@{digest}"]

    def fake_run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv[1:3] == ["image", "inspect"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(recorded).encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert swe.pinned("swerebench/a-1:latest") == f"swerebench/a-1@{digest}"
    assert swe.pinned(f"swerebench/a-1@{digest}") == f"swerebench/a-1@{digest}"
    with pytest.raises(swe.ContractError, match="another digest"):
        swe.pinned("swerebench/a-1@sha256:" + "4" * 64)
    recorded.pop()
    with pytest.raises(swe.ContractError, match="no registry digest"):
        swe.pinned("swerebench/a-1:latest")


def test_the_mirror_is_reused(tmp_path: Path, target: tuple[Repo, str, str]) -> None:
    repo, base, _ = target
    mirror = tmp_path / "m.git"
    swe.fetch_base(mirror, "example/pkg", base, source=str(repo.path))
    # The second call fetches nothing: an unreachable source would fail if it tried.
    again = swe.fetch_base(mirror, "example/pkg", base, source=str(tmp_path / "gone"))
    assert isinstance(again, Git)
