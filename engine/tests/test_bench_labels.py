"""Human labels (J02): κ, adjudication, audits, the freeze and the annotation page."""

import json
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro.agents.backend import AgentResult
from repro.agents.prompts import read_lock, read_prompt
from repro_bench import annotate, difftest, labels
from repro_bench.labels import Label, LabelError
from repro_bench.truth import Oracle, OracleError


def pairs_of(counts: dict[tuple[str, str], int]) -> list[tuple[str, str]]:
    return [pair for pair, n in counts.items() for _ in range(n)]


def test_kappa_matches_the_worked_example() -> None:
    # Wikipedia, "Cohen's kappa", Simple example (checked 2026-10-18): 50 proposals, two
    # readers; 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no: p_o 0.7, p_e 0.5, κ 0.4.
    found = labels.cohen_kappa(
        pairs_of({("Y", "Y"): 20, ("Y", "N"): 5, ("N", "Y"): 10, ("N", "N"): 15}), ("Y", "N")
    )
    assert (found.items, found.observed, found.expected) == (50, 0.7, 0.5)
    assert found.kappa == pytest.approx(0.4)


def test_kappa_is_undefined_not_perfect_when_one_label_is_used_throughout() -> None:
    found = labels.cohen_kappa([("CORRECT", "CORRECT")] * 4)
    assert (found.observed, found.expected, found.kappa) == (1.0, 1.0, None)


def label(item: str, who: str, value: str, defect: str | None = None) -> Label:
    return Label(item, who, value, defect)


def test_agreement_per_source_and_adjudication() -> None:
    first = [label("a@1", "A1", "CORRECT"), label("b@1", "A1", "INCORRECT", "regression"),
             label("c@1", "A1", "UNCERTAIN")]  # fmt: skip
    second = [label("a@1", "A2", "CORRECT"), label("b@1", "A2", "INCORRECT", "edge_case"),
              label("c@1", "A2", "INCORRECT", "other")]  # fmt: skip
    pairs = labels.paired(first, second)
    by = labels.agreement_by_source(pairs, {"a@1": "tier-b", "b@1": "audit", "c@1": "tier-b"})
    assert set(by) == {"all", "audit", "tier-b"}
    assert by["all"].items == 3
    finals, open_items = labels.adjudicate(pairs, {})
    assert [f.item for f in finals] == ["a@1"]
    assert open_items == ["b@1", "c@1"]  # a different defect class is a disagreement too
    resolved = {
        "b@1": {"label": "INCORRECT", "defect": "regression", "agreed_by": ["A2", "A1"]},
        "c@1": {"label": "UNCERTAIN", "note": "the issue is ambiguous", "agreed_by": ["A1", "A2"]},
    }
    finals, open_items = labels.adjudicate(pairs, resolved)
    assert open_items == []
    assert [(f.item, f.label, f.how) for f in finals] == [
        ("a@1", "CORRECT", "agreed"),
        ("b@1", "INCORRECT", "adjudicated"),
        ("c@1", "UNCERTAIN", "adjudicated"),
    ]
    with pytest.raises(LabelError, match="agreed by both"):
        labels.adjudicate(pairs, resolved | {"b@1": resolved["b@1"] | {"agreed_by": ["A1"]}})


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"item": "a@1", "annotator": "Jane", "label": "CORRECT"}, "not a pseudonym"),
        ({"item": "a@1", "annotator": "A1", "label": "PLAUSIBLE"}, "label"),
        ({"item": "a@1", "annotator": "A1", "label": "INCORRECT"}, "needs a defect class"),
        ({"item": "a@1", "annotator": "A1", "label": "CORRECT", "defect": "other"}, "only an"),
    ],
)
def test_a_label_file_that_breaks_the_format_is_refused(
    tmp_path: Path, record: dict[str, Any], message: str
) -> None:
    path = tmp_path / "A1.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(LabelError, match=message):
        labels.read_labels(path)


def test_two_files_from_one_annotator_give_no_agreement() -> None:
    with pytest.raises(LabelError, match="two different annotators"):
        labels.paired([label("a@1", "A1", "CORRECT")], [label("a@1", "A1", "CORRECT")])


def test_audits_are_reproducible_and_fifteen_percent() -> None:
    items = [f"task-{n}@abc" for n in range(40)]
    drawn = labels.audit_sample(items, seed="S2-2026-10")
    assert len(drawn) == 6
    assert drawn == labels.audit_sample(reversed(items), seed="S2-2026-10")
    assert drawn != labels.audit_sample(items, seed="another")
    assert labels.audit_sample(["only@1"], seed="s") == ["only@1"]


def test_the_freeze_detects_any_later_change(tmp_path: Path) -> None:
    finals = [labels.Decided("b@1", "INCORRECT", "regression", "adjudicated"),
              labels.Decided("a@1", "CORRECT", None, "agreed")]  # fmt: skip
    path = tmp_path / "labels.jsonl"
    lock = labels.write_finals(path, finals)
    assert lock["items"] == 2
    assert lock["labels"] == {"CORRECT": 1, "INCORRECT": 1}
    labels.check_frozen(path)
    path.write_bytes(path.read_bytes().replace(b"CORRECT", b"UNCERTAIN", 1))
    with pytest.raises(LabelError, match="changed after it was frozen"):
        labels.check_frozen(path)


def test_the_command_reports_kappa_and_refuses_open_disagreements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for who, value in (("A1", "CORRECT"), ("A2", "UNCERTAIN")):
        (tmp_path / f"{who}.jsonl").write_text(
            json.dumps({"item": "a@1", "annotator": who, "label": value}) + "\n"
            + json.dumps({"item": "b@1", "annotator": who, "label": "CORRECT"}) + "\n",
            encoding="utf-8",
        )  # fmt: skip
    files = [str(tmp_path / "A1.jsonl"), str(tmp_path / "A2.jsonl")]
    assert labels.main(["kappa", *files]) == 0
    assert "all: n=2 p_o=0.500" in capsys.readouterr().out
    assert labels.main(["adjudicate", *files, "--out", str(tmp_path / "final.jsonl")]) == 1
    assert "1 disagreements need a resolution" in capsys.readouterr().out


# -- the annotation page --------------------------------------------------------------------------

ITEM = {
    "item": "o__r-1@0123456789ab",
    "repo": "o/r",
    "problem_statement": "Broken </script><script>alert(1)</script> & more",
    "candidate_patch": "diff --git a/x b/x\n+new\n",
    "gold_patch": "diff --git a/x b/x\n+gold\n",
    "test_patch": "",
    "tiers": {"tier_a": "PLAUSIBLE"},
}


def test_the_page_shows_allowed_fields_and_refuses_a_systems_output() -> None:
    with pytest.raises(LabelError, match="may not see"):
        annotate.page([ITEM | {"repro_status": "FLAGGED"}], "A1", "seed")
    with pytest.raises(LabelError, match="not a pseudonym"):
        annotate.page([ITEM], "Jane Doe", "seed")
    page = annotate.page([ITEM], "A1", "seed")
    assert "alert(1)</script>" not in page  # the task's text cannot close the script
    assert "\\u003c/script\\u003e" in page
    assert page.count("<script") == 2


def test_each_annotator_gets_their_own_order() -> None:
    items = [ITEM | {"item": f"t-{n}@abc"} for n in range(12)]

    def order(who: str) -> list[str]:
        page = annotate.page(items, who, "seed")
        batch = json.loads(page.split('id="batch">', 1)[1].split("</script>", 1)[0])
        return [i["item"] for i in batch["items"]]

    assert sorted(order("A1")) == sorted(order("A2"))
    assert order("A1") != order("A2")
    assert order("A1") == order("A1")


# -- written differential tests -------------------------------------------------------------------

TASK = {
    "instance_id": "o__r-1",
    "docker_image": "swerebench/x:latest",
    "base_commit": "a" * 40,
    "patch": "diff --git a/m.py b/m.py\n+gold\n",
    "test_patch": "diff --git a/tests/test_m.py b/tests/test_m.py\n",
    "FAIL_TO_PASS": "[]",
    "PASS_TO_PASS": "[]",
    "install_config": {"test_cmd": "pytest -rA tests/test_m.py", "log_parser": "parse_log_pytest"},
}


def test_the_prompt_is_locked_at_its_version() -> None:
    prompt = read_prompt(difftest.PROMPTS / "difftest.md")
    assert read_lock(difftest.PROMPTS)[prompt.prompt_version] == prompt.sha256
    request = difftest.request(Oracle.from_record(TASK), "issue", "+candidate", "m")
    assert request.prompt_version == "difftest/1"
    assert request.prompt.count("<untrusted_content") == 4


def test_written_tests_become_a_patch_git_applies(tmp_path: Path) -> None:
    source = difftest.module_from(
        AgentResult("ok", {"module": "```python\nimport m\n\ndef test_m():\n    assert m\n```"})
    )
    path = difftest.module_path(Oracle.from_record(TASK))
    assert path == "tests/test_repro_difftest.py"
    repo = Repo(tmp_path / "r")
    repo.commit({"m.py": "x = 1\n"})
    (tmp_path / "t.diff").write_bytes(difftest.as_patch(path, source).encode("utf-8"))
    repo.git("apply", "--cached", str(tmp_path / "t.diff"))
    assert repo.git("show", f":{path}") == source.rstrip("\n")


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (AgentResult("timeout", detail="took too long"), "no tests were written"),
        (AgentResult("ok", {"module": "def test(:\n"}), "not Python"),
        (AgentResult("ok", {"module": "x = 1\n"}), "has no test"),
    ],
)
def test_unusable_tests_are_refused(result: AgentResult, message: str) -> None:
    with pytest.raises(OracleError, match=message):
        difftest.module_from(result)
