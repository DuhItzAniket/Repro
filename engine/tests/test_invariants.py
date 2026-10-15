"""Declared invariants (F02): each one's pass, fail and not-evaluated cases, from evidence.

Roadmap F02: "passing and failing fixture per invariant": through ``repro run``, the
``invariants-pass`` fixture passes them, and ``api-break``, ``new-dep`` and ``forbidden-path``
each fail theirs (``test_run_stage.py``). Here the rules are tested on their own.
"""

import pytest

from repro.policy import Invariant
from repro.policy import invariants as rules
from repro_events import models

RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"
EV1, EV2 = "ev_01JABCDEFGHJKMNPQRSTVWXYZ1", "ev_01JABCDEFGHJKMNPQRSTVWXYZ2"


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("migrations/**", "migrations/0001_initial.py", True),
        ("migrations/**", "migrations/deep/x.sql", True),
        ("migrations/**", "app/migrations/x.py", False),
        ("**/migrations/**", "app/migrations/x.py", True),
        (".github/**", ".github/workflows/ci.yml", True),
        ("./.github/**", ".github/workflows/ci.yml", True),
        ("*.lock", "uv.lock", True),
        ("*.lock", "sub/uv.lock", False),
        ("**/*.lock", "sub/uv.lock", True),
        ("setup.py", "setup.py", True),
        ("setup.py", "tools/setup.py", False),
        ("docs/?.md", "docs/a.md", True),
        ("docs/?.md", "docs/ab.md", False),
        ("a[b].txt", "a[b].txt", True),  # brackets are literal, not a character class
        # A pattern that matches a directory forbids everything under it.
        ("migrations", "migrations/0001_initial.sql", True),
        ("migrations/", "migrations/deep/x.sql", True),
        ("migrations/", "migrations", False),  # a file: "/" asks for a directory
        ("migrations", "migrations", True),
        ("migrations/*", "migrations/deep/x.sql", True),
        ("**/migrations", "app/migrations/x.py", True),
        ("docs/*.md", "docs/sub/a.md", False),
        ("*.lock", "uv.lock/x", True),  # a directory with that name
    ],
)
def test_path_patterns(pattern: str, path: str, expected: bool) -> None:
    assert rules.matches(pattern, path) is expected


def test_dotted_paths() -> None:
    assert rules.dotted("pkg.mod:Box.lid#0") == "pkg.mod.Box.lid"
    assert rules.dotted("pkg:<module>#0") == "pkg"


def checked(result: rules.InvariantResult) -> rules.InvariantResult:
    record = result.evidence(RUN_ID)
    record["seq"] = 1
    models.Evidence.model_validate(record)
    payload = result.payload(record["id"])
    models.InvariantResultPayload.model_validate(payload)
    assert payload["evidence_ids"][0] == record["id"]
    return result


def test_public_api_stable() -> None:
    invariant = Invariant("public_api_stable", {"except": ["pkg.experimental.*"]})
    breaks = [
        ("pkg.core:greet#0", "parameter_removed", EV1),
        ("pkg.experimental:trial#0", "object_removed", EV2),
    ]
    failed = checked(rules.public_api_stable(invariant, breaks))
    assert (failed.result, failed.cites) == ("fail", (EV1,))
    assert (
        failed.message == "1 breaking changes of the public API: pkg.core.greet (parameter_removed)"
    )
    passed = checked(rules.public_api_stable(invariant, breaks[1:]))
    assert (passed.result, passed.message) == (
        "pass",
        "no breaking change of the public API (1 excepted)",
    )
    assert checked(rules.public_api_stable(invariant, None)).result == "not_evaluated"
    assert checked(rules.public_api_stable(invariant, [], unread=["pkg"])).result == "not_evaluated"
    # A break counts even when another package could not be read.
    assert rules.public_api_stable(invariant, breaks, unread=["other"]).result == "fail"


def test_no_new_dependencies() -> None:
    invariant = Invariant("no_new_dependencies", {"allow": ["types-*"]})
    changes = [
        ("six", "added", "declared", EV1),
        ("types-requests", "added", "lockfile", EV2),
        ("certifi", "added", "installed", EV2),  # pulled in, not declared: not this invariant's
        ("attrs", "upgraded", "lockfile", EV2),
    ]
    failed = checked(rules.no_new_dependencies(invariant, changes))
    assert (failed.result, failed.cites, failed.message) == (
        "fail",
        (EV1,),
        "new dependencies: six",
    )
    assert checked(rules.no_new_dependencies(invariant, changes[1:])).result == "pass"
    assert checked(rules.no_new_dependencies(invariant, None)).result == "not_evaluated"
    # A side's declared dependencies not read: what it adds there would go unseen.
    unread = checked(rules.no_new_dependencies(invariant, changes[1:], unread=["head"]))
    assert (unread.result, unread.message) == (
        "not_evaluated",
        "the dependencies declared on head could not be read statically",
    )
    assert rules.no_new_dependencies(invariant, changes, unread=["head"]).result == "fail"


def test_forbidden_paths() -> None:
    invariant = Invariant("forbidden_paths", {"paths": ["migrations/**", ".github/**"]})
    failed = checked(rules.forbidden_paths(invariant, ["app/x.py", "migrations/0002.py"]))
    assert (failed.result, failed.details) == ("fail", {"paths": ["migrations/0002.py"]})
    passed = checked(rules.forbidden_paths(invariant, ["app/x.py"]))
    assert (passed.result, passed.message) == (
        "pass",
        "no forbidden path touched (1 files changed)",
    )
    assert checked(rules.forbidden_paths(invariant, None)).result == "not_evaluated"


def test_an_invariant_not_yet_evaluated_says_so() -> None:
    result = checked(rules.not_yet(Invariant("no_network"), "F03"))
    assert (result.result, result.status, result.message) == (
        "not_evaluated",
        "warn",
        "evaluated from F03 on",
    )
