"""Repro's GitHub Action, the parts that decide and run (I03).

``action.yml``, at the repository's root, is thin: it installs Repro from the Action's own
checkout and calls the three steps here, so what it does is tested like the rest of the engine.

- ``plan`` reads the workflow's event: the pull request, whether it comes from a fork, and so
  whether the card may be posted to it. Under ``pull_request`` a fork's pull request gets a
  read-only token; ``pull_request_target`` has a write token in the base repository's context
  even for a fork's [GitHub docs, "Workflow syntax", ``permissions``, checked 2026-10-17]. So
  posting for a fork is the maintainer's choice (``post-on-forks``, which needs
  ``pull_request_target``), never the default: a fork's run still makes its card, for the job's
  summary and an artifact. Signing needs a public repository [actions/attest README, checked
  2026-10-17] and the write token, so only a run that posts is signed.
- ``run`` runs Repro on the pull request and writes what the later steps use: the card as
  canonical JSON (``card.json``, exactly the bytes the card's SHA-256 is of, so a signed
  subject's digest is the card's own), as Markdown, and the in-toto predicate.
- ``report`` puts the card on the pull request (``repro report``), or, when it may not post,
  in the job's summary alone.

Each step writes its outputs to ``GITHUB_OUTPUT`` and says what it decided.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

EVENTS: Final = ("pull_request", "pull_request_target")
_COMPLETED: Final = re.compile(r"\b(run_[0-9A-HJKMNP-TV-Z]{26}) completed\b")
CARD_DIR: Final = "repro-card"


class ActionError(Exception):
    """The Action cannot go on; the message says why."""


@dataclass(frozen=True)
class Plan:
    pr: str
    fork: bool
    post: bool
    attest: bool
    reason: str


def _true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def plan(event_name: str, event: Mapping[str, Any], *, post_on_forks: bool, attest: bool) -> Plan:
    """What to do for this event (raises ``ActionError`` for an event that is not a pull
    request's)."""
    if event_name not in EVENTS:
        raise ActionError(
            f"Repro's Action runs on pull_request or pull_request_target, not {event_name}"
        )
    pr = event.get("pull_request")
    if not isinstance(pr, dict) or not isinstance(pr.get("html_url"), str):
        raise ActionError("the event names no pull request")
    base = (pr.get("base") or {}).get("repo") or {}
    head = (pr.get("head") or {}).get("repo")
    fork = not isinstance(head, dict) or head.get("full_name") != base.get("full_name")
    if not fork:
        post, reason = True, "a pull request from this repository: the card is posted to it"
    elif event_name == "pull_request_target" and post_on_forks:
        post, reason = True, "a fork's pull request, posted to as the workflow opted in"
    else:
        post = False
        reason = (
            "a fork's pull request: the card goes to the job's summary and an artifact, and "
            "nothing is posted (post-on-forks, under pull_request_target, opts in)"
        )
    public = base.get("private") is False
    return Plan(pr["html_url"], fork, post, attest and post and public, reason)


def _outputs(values: Mapping[str, object]) -> None:
    """Appends ``key=value`` lines to ``GITHUB_OUTPUT`` (printed when there is none)."""
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as out:
            out.write(lines)
    else:
        sys.stdout.write(lines)


def _repro(*args: str, capture: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - Repro itself, with the Action's own arguments
        [sys.executable, "-m", "repro", *args], capture_output=capture, check=False
    )


def run(pr: str, out: Path, *, extra: Sequence[str] = ()) -> dict[str, str]:
    """Runs Repro on ``pr`` and writes the card and the predicate into ``out``; their paths."""
    process = subprocess.Popen(  # noqa: S603 - Repro itself
        [sys.executable, "-m", "repro", "run", "--pr", pr, "--no-serve", *extra],
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    said = []
    assert process.stderr is not None  # noqa: S101 - asked for above
    for line in process.stderr:  # shown as it comes: a run takes minutes
        sys.stderr.write(line)
        said.append(line)
    if process.wait() != 0:
        raise ActionError("repro run did not complete; its log above says why")
    found = _COMPLETED.search("".join(said))
    if found is None:
        raise ActionError("repro run named no completed run")
    run_id = found[1]
    out.mkdir(parents=True, exist_ok=True)
    card = _repro("export", run_id, "--format", "json")
    markdown = _repro("export", run_id, "--format", "md")
    statement = _repro("export", run_id, "--format", "in-toto")
    for done in (card, markdown, statement):
        if done.returncode != 0:
            raise ActionError(f"repro export failed: {done.stderr.decode('utf-8', 'replace')}")
    canonical = card.stdout.removesuffix(b"\n")  # the card's own bytes: its digest is the card's
    (out / "card.json").write_bytes(canonical)
    (out / "card.md").write_bytes(markdown.stdout)
    attestation = json.loads(statement.stdout)
    (out / "predicate.json").write_text(json.dumps(attestation["predicate"]), encoding="utf-8")
    return {
        "run-id": run_id,
        "status": json.loads(canonical)["status"],
        "card": str(out / "card.json"),
        "card-md": str(out / "card.md"),
        "predicate": str(out / "predicate.json"),
        "predicate-type": attestation["predicateType"],
    }


def report(run_id: str, *, post: bool) -> int:
    """``repro report``: to the pull request when it may post, else the job's summary alone."""
    only_summary = [] if post else ["--no-check", "--no-comment"]
    return _repro("report", run_id, *only_summary, capture=False).returncode


def main(argv: Sequence[str]) -> int:
    env = os.environ
    try:
        if argv == ["plan"]:
            event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            decided = plan(
                env.get("GITHUB_EVENT_NAME", ""),
                event,
                post_on_forks=_true(env.get("INPUT_POST_ON_FORKS")),
                attest=_true(env.get("INPUT_ATTEST")),
            )
            sys.stderr.write(f"repro action: {decided.reason}\n")
            _outputs(
                {
                    "pr": decided.pr,
                    "fork": str(decided.fork).lower(),
                    "post": str(decided.post).lower(),
                    "attest": str(decided.attest).lower(),
                }
            )
            return 0
        if argv == ["run"]:
            extra = ["--analyse-only"] if _true(env.get("INPUT_ANALYSE_ONLY")) else []
            out = Path(env.get("RUNNER_TEMP", ".")) / CARD_DIR
            _outputs(run(env["REPRO_PR"], out, extra=extra))
            return 0
        if argv == ["report"]:
            return report(env["REPRO_RUN_ID"], post=_true(env.get("REPRO_POST")))
    except (ActionError, KeyError, OSError, ValueError) as exc:
        sys.stderr.write(f"repro action: {exc}\n")
        return 1
    sys.stderr.write("usage: python -m repro.integrations.github.action plan|run|report\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
