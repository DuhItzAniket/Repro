"""The policy of a run (F01): ``repro.yml`` read from the base commit, and what head did to it.

- No ``repro.yml`` on base: the defaults (no invariant enabled).
- An invalid one: no policy at all, and an ``unsupported_project`` item listing every issue
  with its line, so the file can be fixed from it; the invariants are then not evaluated.
- Head adds, removes or edits the file: ``policy_change`` evidence saying how (and how it
  weakens base's policy, if it does). Head's policy is never applied.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from repro import __version__
from repro.gitops import Git, read_blobs, regular_files
from repro.ids import new_evidence_id
from repro.policy.loader import DEFAULT, FILE, Policy, PolicyError, PolicyIssue, load, weakenings

Change = Literal["added", "removed", "modified"]


def file_at(git: Git, commit: str, path: str = FILE) -> bytes | None:
    """``path``'s bytes at ``commit`` (None if it has no such regular file)."""
    blob = regular_files(git, commit).get(path)
    return read_blobs(git, [blob]).get(blob) if blob is not None else None


@dataclass(frozen=True, slots=True)
class PolicyChange:
    """What head did to ``repro.yml``."""

    change: Change
    weakened: tuple[str, ...]
    head_issues: tuple[PolicyIssue, ...] = ()
    base: dict[str, Any] | None = None
    head: dict[str, Any] | None = None

    def summary(self) -> str:
        verb = {"added": "adds", "removed": "removes", "modified": "edits"}[self.change]
        text = f"head {verb} {FILE}; the policy is read from base"
        if self.weakened:
            text += f"; it would weaken it: {'; '.join(self.weakened)}"
        if self.head_issues:
            text += f"; head's file is not valid ({len(self.head_issues)} issues)"
        return text[:1000]

    def evidence(self, run_id: str) -> dict[str, Any]:
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "policy_change",
            "targets": [{"file": FILE}],
            "summary": self.summary(),
            "data": {
                "change": self.change,
                "weakened": list(self.weakened),
                "head_issues": [str(issue) for issue in self.head_issues][:50],
                "base": self.base,
                "head": self.head,
            },
            "artifacts": [],
            "stability": "stable",
            "origin": "introduced",
            "produced_by": {"component": "repro.policy", "version": __version__},
        }


@dataclass
class PolicyRead:
    """The run's policy (None: base's file is invalid), its issues, and head's change."""

    policy: Policy | None
    issues: tuple[PolicyIssue, ...] = ()
    found: bool = False  # base has a repro.yml
    change: PolicyChange | None = None
    head_policy: Policy | None = field(default=None, repr=False)

    def missing(self) -> list[dict[str, Any]]:
        if self.policy is not None:
            return []
        listed = "; ".join(str(issue) for issue in self.issues[:10])
        more = len(self.issues) - 10
        detail = f"{FILE} on base is not valid, so no invariant is evaluated: {listed}" + (
            f"; and {more} more" if more > 0 else ""
        )
        return [
            {
                "missing": {
                    "reason": "unsupported_project",
                    "targets": [{"file": FILE}],
                    "detail": detail[:1000],
                    "resolution": f"Fix {FILE} on the base branch (each issue names its line)",
                }
            }
        ]


def read_policy(git: Git, base: str, head: str) -> PolicyRead:
    """Base's policy and head's change to it."""
    before, after = file_at(git, base), file_at(git, head)
    read = _load(before)
    if before == after:
        return read
    if after is None:
        change: Change = "removed"
    else:
        change = "added" if before is None else "modified"
    head_read = _load(after)
    weakened: list[str] = []
    if read.policy is not None and change == "removed":
        weakened = weakenings(read.policy, DEFAULT)
    elif read.policy is not None and head_read.policy is not None:
        weakened = weakenings(read.policy, head_read.policy)
    read.change = PolicyChange(
        change,
        tuple(weakened),
        head_read.issues,
        read.policy.document() if read.policy is not None and before is not None else None,
        head_read.policy.document() if head_read.policy is not None and after is not None else None,
    )
    read.head_policy = head_read.policy
    return read


def _load(data: bytes | None) -> PolicyRead:
    if data is None:
        return PolicyRead(DEFAULT)
    try:
        return PolicyRead(load(data), found=True)
    except PolicyError as exc:
        return PolicyRead(None, exc.issues, found=True)
