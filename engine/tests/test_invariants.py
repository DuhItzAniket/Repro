"""Declared invariants (F02, F03): each one's pass, fail and not-evaluated cases, from evidence.

Roadmap F02 / F03: "passing and failing fixture per invariant": through ``repro run``, the
``invariants-pass`` fixture passes them all, and ``api-break``, ``new-dep``, ``forbidden-path``,
``net-call`` and ``perf-regress`` each fail theirs (``test_run_stage.py``). Here the rules are
tested on their own.
"""

import pytest

from repro.policy import Invariant
from repro.policy import invariants as rules
from repro.sandbox.detect import leaves_host
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


@pytest.mark.parametrize(
    ("event", "detail", "leaves"),
    [
        ("socket.connect", "192.0.2.1:80", True),
        ("socket.connect", "127.0.0.1:52011", False),  # asyncio's self-pipe on Windows
        ("socket.connect", "::1:8080", False),
        ("socket.connect", "::ffff:127.0.0.1:80", False),
        ("socket.connect", "0.0.0.0:80", False),
        ("socket.connect", "/run/app/app.sock", False),  # a Unix socket
        ("socket.getaddrinfo", "example.com:443", True),
        ("socket.getaddrinfo", "localhost:8000", False),
        ("socket.getaddrinfo", "None:0", False),  # a passive lookup, to bind
        ("socket.gethostbyname", "example.com", True),
        ("socket.gethostbyname", "localhost", False),
        ("socket.sendto", "8.8.8.8:53", True),
    ],
)
def test_what_reaches_past_this_machine(event: str, detail: str, leaves: bool) -> None:
    assert leaves_host(event, detail) is leaves


def test_no_network() -> None:
    invariant = Invariant("no_network")
    local = rules.Attempt("socket.connect", "127.0.0.1:52011", EV1)
    out = rules.Attempt("socket.connect", "192.0.2.1:80", EV2)
    failed = checked(rules.no_network(invariant, [local, out], network="enforced"))
    assert (failed.result, failed.cites, failed.message) == (
        "fail",
        (EV2,),
        "head's tests attempted the network: 192.0.2.1:80",
    )
    assert failed.details == {"attempts": ["192.0.2.1:80"], "network": "enforced"}
    enforced = checked(rules.no_network(invariant, [local], network="enforced"))
    assert (enforced.result, enforced.details) == ("pass", {"network": "enforced"})
    detected = checked(rules.no_network(invariant, [], network="detected-only"))
    assert (detected.result, detected.details) == ("pass", {"network": "detected-only"})
    assert "detected only" in detected.message
    missing = rules.network_not_enforced()
    models.MissingRecordedPayload.model_validate(missing)
    assert missing["missing"]["reason"] == "network_not_enforced"
    assert checked(rules.no_network(invariant, None, network=None)).result == "not_evaluated"
    cut = rules.no_network(invariant, [], network="detected-only", complete=False)
    assert checked(cut).result == "not_evaluated"
    # An attempt seen counts even when other records were lost.
    assert rules.no_network(invariant, [out], network="enforced", complete=False).result == "fail"


def test_no_network_where_attempts_are_not_seen() -> None:
    """K08, K11: a Node process is not seen by Repro's detection. In the process sandbox the
    invariant is not evaluated; in a container it passes on the enforcement alone, and says
    so."""
    invariant = Invariant("no_network")
    why = "a Node process does not load the hook"
    l2 = checked(rules.no_network(invariant, [], network="detected-only", unseen=why))
    assert (l2.result, l2.message) == ("not_evaluated", why)
    l3 = checked(rules.no_network(invariant, [], network="enforced", undetected=why))
    assert l3.result == "pass"
    assert l3.message == (
        "nothing head's tests did reached the network: the sandbox had none (enforced); their "
        f"attempts are not seen ({why})"
    )
    assert l3.details == {"network": "enforced", "undetected": why}
    # Where the network is not enforced, "not seen" leaves nothing to rest a pass on.
    blind = rules.no_network(invariant, [], network="detected-only", undetected=why)
    assert checked(blind).result == "not_evaluated"
    # Head's tests did not run: nothing to rest it on either.
    assert rules.no_network(invariant, None, network="enforced", undetected=why).result == (
        "not_evaluated"
    )


def timed(test: str, verdict: str, ratio: float, low: float, high: float) -> rules.Timed:
    return rules.Timed(test, verdict, ratio, low, high, EV1 if verdict == "regression" else EV2)


def test_perf_budget() -> None:
    invariant = Invariant("perf_budget", {"max_regression": 0.2})
    steady = timed("t::steady", "no_change", 1.02, 0.97, 1.08)
    slower = timed("t::slower", "regression", 1.15, 1.11, 1.19)  # a regression, within budget
    over = timed("t::over", "regression", 3.4, 3.1, 3.7)
    failed = checked(rules.perf_budget(invariant, [steady, slower, over], ["t::fast"]))
    assert (failed.result, failed.cites) == ("fail", (EV1,))
    assert failed.message == (
        "1 tests slower than base past the budget (+20%): t::over (x3.40, 95% CI from x3.10)"
    )
    passed = checked(rules.perf_budget(invariant, [steady, slower], ["t::fast"]))
    assert (passed.result, passed.message) == (
        "pass",
        "2 timed tests within the budget (+20%); 1 too fast to time",
    )
    # Past the budget by its interval, but not a regression past this machine's noise.
    noisy = timed("t::noisy", "no_change", 1.3, 1.25, 1.36)
    unclear = checked(rules.perf_budget(invariant, [steady, noisy]))
    assert (unclear.result, unclear.details) == ("not_evaluated", {"unclear": ["t::noisy"]})
    assert checked(rules.perf_budget(invariant, None)).result == "not_evaluated"
    none = checked(rules.perf_budget(invariant, [], ["t::fast"]))
    assert (none.result, none.message) == (
        "not_evaluated",
        "no selected test could be timed (1 too fast to time)",
    )
