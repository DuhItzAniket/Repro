"""A run's status inputs read from its events alone (F04): what a replay would read."""

from typing import Any

from repro.policy.gap import inputs_from_events
from repro.policy.loader import DEFAULT
from repro.policy.status import decide

RUN = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"
EV = [f"ev_01JABCDEFGHJKMNPQRSTVWXY{i:02d}" for i in range(10)]


def event(kind: str, payload: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"kind": kind, "payload": payload, "status": "ok", "stage": "diff", "target": None,
            **fields}  # fmt: skip


def evidence(evidence_id: str, kind: str, data: dict[str, Any], **fields: Any) -> dict[str, Any]:
    record = {"id": evidence_id, "type": kind, "data": data, "stability": "stable",
              "origin": "introduced", **fields}  # fmt: skip
    return event("evidence.created", {"evidence": record})


def policy(document: dict[str, Any] | None = None, *, valid: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "found": True,
        "valid": valid,
        "policy": document if valid else None,
        "issues": [],
    }
    return evidence(EV[9], "policy", data)


def base_log() -> list[dict[str, Any]]:
    """A run of one changed function, its test selected and passing on both sides."""
    test = "tests/test_a.py::test_f"
    return [
        policy(DEFAULT.document()),
        event(
            "blast.computed",
            {
                "changed": ["pkg.a:f#0", "tests.test_a:test_f#0"],
                "affected": [],
                "module_level_changes": [],
            },
        ),
        event("env.provisioned", {"side": "base"}),
        event("env.provisioned", {"side": "head"}),
        event("test.selected", {"reasons": ["blast_radius"]}, target={"test": test}),
        evidence(EV[0], "test_outcome", {"class": "P2P"}, origin="n/a"),
        event("diff.outcome", {"evidence_id": EV[0]}, target={"test": test}),
        event("stage.finished", {"duration_ms": 1}, stage="diff"),
    ]


def test_a_clean_run_is_verified() -> None:
    inputs = inputs_from_events(base_log())
    assert inputs.changed == ("pkg.a:f#0",)  # the test function is test code
    assert (inputs.selected, inputs.ran, inputs.gap, inputs.claims) == (1, 1, (), None)
    assert decide(inputs).status == "VERIFIED"


def test_a_difference_a_supported_claim_cites_is_explained() -> None:
    log = [
        *base_log(),
        evidence(EV[1], "behaviour_diff", {"change": "result_changed"}),
        event("diff.behaviour", {"evidence_id": EV[1]}, status="warn"),
    ]
    (item,) = inputs_from_events(log).gap
    assert (item.check, item.kind, item.resolution) == (
        "diff.behaviour",
        "result_changed",
        "flagged",
    )
    claim = {"id": "c1", "text": "x", "kind": "fix", "targets": [], "source": "pr_title"}
    verdict = {"claim_id": "c1", "verdict": "supported", "cited_evidence": [EV[1]], "quotes": [],
               "rationale": "r", "model": "m", "agreement": None}  # fmt: skip
    reviewed = [
        *log,
        event("stage.started", {"index": 0}, stage="read"),
        event("claim.extracted", {"claim": claim}, stage="read"),
        event("verdict.issued", {"verdict": verdict}, stage="review"),
    ]
    inputs = inputs_from_events(reviewed)
    assert inputs.gap[0].explained_by == ("c1",)
    assert inputs.claims == ("c1",)
    assert decide(inputs).status == "VERIFIED"


def test_head_editing_the_policy_is_a_gap_item() -> None:
    log = [*base_log(), evidence(EV[2], "policy_change", {"change": "modified"})]
    (item,) = inputs_from_events(log).gap
    assert (item.check, item.resolution) == ("policy_change", "flagged")


def test_missing_items_leave_symbols_unverified() -> None:
    noise = {"reason": "unstable_observation", "targets": [{"symbol": "pkg.a:f#0"}],
             "detail": "d", "resolution": None}  # fmt: skip
    inputs = inputs_from_events([*base_log(), event("missing.recorded", {"missing": noise})])
    assert inputs.unverified == {"pkg.a:f#0"}
    assert decide(inputs).status == "UNVERIFIABLE"
    # About no symbol in particular: every changed symbol.
    whole: dict[str, Any] = {
        "reason": "trace_unavailable",
        "targets": [],
        "detail": "d",
        "resolution": None,
    }
    inputs = inputs_from_events([*base_log(), event("missing.recorded", {"missing": whole})])
    assert inputs.unverified == {"pkg.a:f#0"}


def test_the_policy_in_force_decides_the_thresholds() -> None:
    document = DEFAULT.document()
    document["missing"]["max_uncovered_changed_symbols"] = 1.0
    noise = {"reason": "unstable_observation", "targets": [{"symbol": "pkg.a:f#0"}],
             "detail": "d", "resolution": None}  # fmt: skip
    log = [*base_log()[1:], policy(document), event("missing.recorded", {"missing": noise})]
    assert decide(inputs_from_events(log)).status == "VERIFIED"  # 100 % allowed


def test_what_the_log_does_not_show_was_not_checked() -> None:
    log = base_log()
    assert inputs_from_events(log[1:]).policy_valid is False  # no policy evidence
    assert inputs_from_events([*log[1:], policy(valid=False)]).policy_valid is False
    without_blast = [e for e in log if e["kind"] != "blast.computed"]
    assert decide(inputs_from_events(without_blast)).reasons[0].rule == "not_analysed"
    skipped = [*log, event("stage.finished", {"duration_ms": 1}, stage="check", status="warn")]
    assert inputs_from_events(skipped).incomplete_stages == ("check",)
    one_side = [e for e in log if e["payload"].get("side") != "head"]
    assert decide(inputs_from_events(one_side)).reasons[0].rule == "environment_failed"
    # H06: a test run that did not finish, whatever was selected.
    detail = "base: the A run ended early"
    died: dict[str, Any] = {
        "reason": "run_incomplete",
        "targets": [],
        "detail": detail,
        "resolution": None,
    }
    unfinished = inputs_from_events([*log, event("missing.recorded", {"missing": died})])
    assert unfinished.unfinished == (detail,)
    assert decide(unfinished).reasons[0].rule == "tests_not_run"
