"""``repro.yml`` (F01): the schema, the loader's errors, defaults, and head's changes.

Roadmap F01: "invalid configs give actionable errors. Policy weakening in head is flagged." The
``policy-weaken`` fixture runs end to end in ``test_run_stage.py``.
"""

from pathlib import Path

import jsonschema
import pytest

from gitrepo import Repo
from repro.gitops import Git
from repro.policy import DEFAULT, Invariant, Policy, PolicyError, load, weakenings
from repro.policy.loader import MAX_BYTES, schema
from repro.policy.stage import read_policy
from repro_events import models

RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"

PRODUCT_EXAMPLE = b"""invariants:
  - public_api_stable: { except: ["mypkg.experimental.*"] }
  - no_new_dependencies: true
  - no_network: true                       # head tests must not attempt network access
  - perf_budget: { max_regression: 0.20 }  # per selected test, CI-based, vs base
  - forbidden_paths: ["migrations/**", ".github/**"]
claims:
  require_explicit: true                   # PRs with no extractable claim -> UNVERIFIABLE
missing:
  max_uncovered_changed_symbols: 0.25      # above this fraction -> UNVERIFIABLE
"""


def test_the_schema_is_a_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(schema())


def test_products_example_loads() -> None:
    policy = load(PRODUCT_EXAMPLE)
    assert [i.name for i in policy.invariants] == [
        "public_api_stable",
        "no_new_dependencies",
        "no_network",
        "perf_budget",
        "forbidden_paths",
    ]
    assert policy.invariant("public_api_stable") == Invariant(
        "public_api_stable", {"except": ["mypkg.experimental.*"]}
    )
    assert policy.invariant("forbidden_paths") == Invariant(
        "forbidden_paths", {"paths": ["migrations/**", ".github/**"]}
    )
    assert (policy.require_explicit_claims, policy.max_uncovered_changed_symbols) == (True, 0.25)
    assert load(_yaml(policy.document())) == policy  # the document reads back as the policy


def _yaml(document: object) -> bytes:
    import json  # noqa: PLC0415 - JSON is YAML

    return json.dumps(document).encode()


def test_defaults() -> None:
    assert load(b"") == DEFAULT
    assert load(b"# nothing but a comment\n") == DEFAULT
    assert load(b"version: 1\n") == DEFAULT
    assert load(b"invariants:\n  - no_network: false\n").invariants == ()  # switched off


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "invariants:\n  - no_netwrk: true\n",
            "repro.yml:2:5: invariants[0]: unknown key 'no_netwrk' (known: forbidden_paths, "
            "no_network, no_new_dependencies, perf_budget, public_api_stable)",
        ),
        (
            "invariants:\n  - perf_budget: { max_regression: 0 }\n",
            "repro.yml:2:36: invariants[0].perf_budget.max_regression: 0 is less than or equal "
            "to the minimum of 0",
        ),
        (
            "invariants:\n  - perf_budget: {}\n",
            "repro.yml:2:18: invariants[0].perf_budget: 'max_regression' is a required property",
        ),
        (
            "invariants:\n  - forbidden_paths: []\n",
            "repro.yml:2:22: invariants[0].forbidden_paths: [] should be non-empty",
        ),
        (
            "claims:\n  require_explicit: yes please\n",
            "repro.yml:2:21: claims.require_explicit: 'yes please' is not of type 'boolean'",
        ),
        (
            "missing:\n  max_uncovered_changed_symbols: 2\n",
            "repro.yml:2:34: missing.max_uncovered_changed_symbols: 2 is greater than the "
            "maximum of 1",
        ),
        ("version: 2\n", "repro.yml:1:10: version: 1 was expected"),
        ("- a\n- b\n", "repro.yml:1:1: ['a', 'b'] is not of type 'object'"),
        (
            "invariants:\n  - no_network: true\n  - no_network: true\n",
            "repro.yml:3:5: invariants[1]: no_network is listed twice",
        ),
        ("a: &x 1\nb: *x\n", "repro.yml:1:4: anchors and aliases are not allowed"),
        ("claims: {}\nclaims: {}\n", "repro.yml:2:1: duplicate key 'claims'"),
        (
            "invariants: [\n",
            "repro.yml:2:1: while parsing a flow node expected the node content, but found "
            "'<stream end>'",
        ),
        (
            "a: 1\n---\nb: 2\n",
            "repro.yml:2:1: expected a single document in the stream but found another document",
        ),
    ],
    ids=[
        "unknown invariant",
        "threshold",
        "required",
        "empty list",
        "type",
        "maximum",
        "version",
        "not a mapping",
        "twice",
        "alias",
        "duplicate key",
        "syntax",
        "two documents",
    ],
)
def test_actionable_errors(text: str, expected: str) -> None:
    with pytest.raises(PolicyError) as raised:
        load(text.encode())
    assert expected in [str(issue) for issue in raised.value.issues]


def test_every_issue_at_once() -> None:
    with pytest.raises(PolicyError) as raised:
        load(b"invariants:\n  - no_netwrk: true\nclaims:\n  require_explicit: 1\nextra: 1\n")
    assert [(i.line, i.path) for i in raised.value.issues] == [
        (1, ""),  # the unknown top-level key: the document
        (4, "claims.require_explicit"),
        (2, "invariants[0]"),
    ]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"x" * (MAX_BYTES + 1), f"larger than {MAX_BYTES} bytes"),
        (b"claims: \xff\n", "not UTF-8"),
        (b"[" * 5000 + b"]" * 5000, None),  # deep: refused, whatever the parser says
    ],
    ids=["size", "encoding", "depth"],
)
def test_untrusted_input_is_bounded(data: bytes, message: str | None) -> None:
    with pytest.raises(PolicyError) as raised:
        load(data)
    if message is not None:
        assert message in str(raised.value)


BASE = Policy(
    (
        Invariant("public_api_stable", {"except": ["a.*"]}),
        Invariant("no_new_dependencies", {}),
        Invariant("no_network", {}),
        Invariant("perf_budget", {"max_regression": 0.2}),
        Invariant("forbidden_paths", {"paths": ["migrations/**", ".github/**"]}),
    ),
    require_explicit_claims=True,
    max_uncovered_changed_symbols=0.25,
)


def test_weakenings() -> None:
    head = Policy(
        (
            Invariant("public_api_stable", {"except": ["a.*", "b.*"]}),
            Invariant("no_new_dependencies", {"allow": ["six"]}),
            Invariant("perf_budget", {"max_regression": 0.5}),
            Invariant("forbidden_paths", {"paths": ["migrations/**"]}),
        ),
        require_explicit_claims=False,
        max_uncovered_changed_symbols=0.5,
    )
    assert weakenings(BASE, head) == [
        "public_api_stable: except gains b.*",
        "no_new_dependencies: allow gains six",
        "no_network removed",
        "perf_budget: max_regression raised from 0.2 to 0.5",
        "forbidden_paths: no longer forbids .github/**",
        "claims.require_explicit turned off",
        "missing.max_uncovered_changed_symbols raised from 0.25 to 0.5",
    ]


def test_a_stricter_policy_is_no_weakening() -> None:
    head = Policy(
        (
            *BASE.invariants[:3],
            Invariant("perf_budget", {"max_regression": 0.1}),
            Invariant("forbidden_paths", {"paths": ["migrations/**", ".github/**", "docs/**"]}),
        ),
        require_explicit_claims=True,
        max_uncovered_changed_symbols=0.1,
    )
    assert weakenings(BASE, head) == []
    assert weakenings(BASE, BASE) == []


def commits(tmp_path: Path, base: str | None, head: str | None) -> tuple[Git, str, str]:
    repo = Repo(tmp_path / "repo")
    files: dict[str, str | None] = {"pkg/__init__.py": ""}
    first = repo.commit({**files, **({"repro.yml": base} if base is not None else {})})
    second = repo.commit({"repro.yml": head})
    return Git(repo.path), first, second


def test_no_file_on_either_side(tmp_path: Path) -> None:
    git, base, head = commits(tmp_path, None, None)
    read = read_policy(git, base, head)
    assert (read.policy, read.found, read.change, read.missing()) == (DEFAULT, False, None, [])


def test_head_removes_the_policy(tmp_path: Path) -> None:
    git, base, head = commits(tmp_path, "invariants:\n  - no_network: true\n", None)
    read = read_policy(git, base, head)
    assert read.policy is not None
    assert [i.name for i in read.policy.invariants] == ["no_network"]  # base's is in force
    assert read.change is not None
    assert (read.change.change, read.change.weakened) == ("removed", ("no_network removed",))
    record = read.change.evidence(RUN_ID)
    record["seq"] = 1
    models.Evidence.model_validate(record)
    assert "head removes repro.yml" in record["summary"]


def test_head_adds_an_invalid_policy(tmp_path: Path) -> None:
    git, base, head = commits(tmp_path, None, "invariants: nope\n")
    read = read_policy(git, base, head)
    assert read.policy == DEFAULT
    assert read.change is not None
    assert read.change.change == "added"
    assert read.change.weakened == ()
    assert [str(i) for i in read.change.head_issues] == [
        "repro.yml:1:13: invariants: 'nope' is not of type 'array'"
    ]


def test_an_invalid_base_policy_is_no_policy(tmp_path: Path) -> None:
    git, base, head = commits(tmp_path, "invariants:\n  - perf_budget: {}\n", None)
    read = read_policy(git, base, head)
    assert read.policy is None
    (item,) = read.missing()
    models.MissingRecordedPayload.model_validate(item)
    assert "repro.yml:2:18: invariants[0].perf_budget" in item["missing"]["detail"]
