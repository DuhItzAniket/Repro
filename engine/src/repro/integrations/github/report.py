"""A run's card, reported to the pull request it is about (I02).

Three targets, each made or updated, never added again:

- **the check run** ``Repro`` on the head commit: the card's status as its conclusion (VERIFIED
  ``success``, FLAGGED ``failure``, UNVERIFIABLE ``neutral``), the reasons as its summary, the
  Markdown card as its text, and annotations at the changed code a flagged difference or an
  unreached function concerns. The Checks API takes 50 annotations a request; updates add the
  rest [GitHub REST API docs, "Check runs", checked 2026-10-17];
- **the comment**: one, found by a hidden marker among the pull request's comments and written by
  the same identity, so that a marker in someone else's comment is never overwritten; pull
  requests share issues' comment endpoints [GitHub REST API docs, "Issue comments", checked
  2026-10-17];
- **the job summary**, in GitHub Actions: the Markdown card appended to ``GITHUB_STEP_SUMMARY``,
  under the 1 MiB a step may write [GitHub docs, "Workflow commands", checked 2026-10-17].

GitHub documents no maximum length for a comment or a check run's text: the card is cut at a
line under 60,000 characters, with a note that ``repro export`` gives it whole.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from repro.card.markdown import headline, render, why
from repro.integrations.github.api import GitHubApi, GitHubError
from repro.integrations.github.pr import PrUrl

CHECK_NAME: Final = "Repro"
MARKER: Final = "<!-- repro:card -->"
BODY_MAX: Final = 60_000
SUMMARY_MAX_BYTES: Final = 1024 * 1024
ANNOTATIONS_PER_REQUEST: Final = 50
CONCLUSION: Final = {"VERIFIED": "success", "FLAGGED": "failure", "UNVERIFIABLE": "neutral"}
CUT_NOTE: Final = "\n\n*The card is cut here: `repro export {run} --format md` gives it whole.*\n"


@dataclass(frozen=True)
class Target:
    """The pull request a card is reported to, and the commit its check run belongs to."""

    owner: str
    repo: str
    number: int
    head_sha: str

    @property
    def path(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"


def target_of(card: Mapping[str, Any], pr: str | None, api_url: str) -> Target:
    """The pull request the card names, or ``pr``; its head is the run's (raises
    ``GitHubError``)."""
    address = pr or (card.get("pr") or {}).get("url")
    if not address:
        raise GitHubError("the run is not a pull request's: name one with --pr")
    url = PrUrl.parse(address)
    url.check_api(api_url)
    return Target(url.owner, url.repo, url.number, card["conditions"]["head"]["sha"])


def cut(markdown: str, limit: int, run_id: str) -> str:
    """``markdown`` whole, or cut at a line so that it and the note fit ``limit``."""
    if len(markdown) <= limit:
        return markdown
    note = CUT_NOTE.format(run=run_id)
    head = markdown[: limit - len(note)]
    return head[: head.rfind("\n") if "\n" in head else len(head)] + note


def annotations(
    card: Mapping[str, Any], events: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Annotations at the head's lines of the changed code a flagged gap item or an unreached
    changed function concerns; a place with no lines on head (a removed function) has none."""
    places: dict[str, tuple[str, int, int]] = {}
    evidence: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event["kind"] == "symbol.changed" and event["payload"].get("head_lines"):
            first, last = event["payload"]["head_lines"]
            places[event["payload"]["symbol_id"]] = (event["payload"]["file"], first, last)
        elif event["kind"] == "evidence.created":
            evidence[event["payload"]["evidence"]["id"]] = event["payload"]["evidence"]
    found: dict[tuple[str, int, str], dict[str, Any]] = {}

    def add(symbol: str | None, level: str, title: str, message: str) -> None:
        if symbol is None or symbol not in places:
            return
        path, first, last = places[symbol]
        found.setdefault(
            (path, first, title),
            {
                "path": path,
                "start_line": first,
                "end_line": last,
                "annotation_level": level,
                "title": title[:255],
                "message": message[:4000],
            },
        )

    for item in card["gap"]:
        if item["resolution"] != "flagged":
            continue
        for target in evidence.get(item["evidence_id"], {}).get("targets", []):
            add(
                target.get("symbol"), "failure", f"{item['check']}: {item['kind']}", item["summary"]
            )
    for item in card["missing"]:
        if item["reason"] == "no_covering_test":
            for target in item["targets"]:
                add(target.get("symbol"), "warning", "no covering test", item["detail"])
    return list(found.values())


def _output(card: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "title": f"{card['status']}: {headline(card).split(': ', 1)[1].rstrip('.')}",
        "summary": "\n".join([headline(card), "", *why(card)]),
        "text": cut(render(card), BODY_MAX, run_id),
    }


def _batches(items: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    size = ANNOTATIONS_PER_REQUEST
    return [list(items[i : i + size]) for i in range(0, len(items), size)] or [[]]


def check_run(
    api: GitHubApi, target: Target, card: Mapping[str, Any], marks: Sequence[dict[str, Any]]
) -> str:
    """Updates the head's ``Repro`` check run, or creates it; what was done, in words."""
    run_id = card["run_id"]
    output = _output(card, run_id)
    first, *rest = _batches(marks)
    body = {
        "name": CHECK_NAME,
        "status": "completed",
        "conclusion": CONCLUSION[card["status"]],
        "external_id": run_id,
        "output": {**output, "annotations": first},
    }
    listed = api.get(f"{target.path}/commits/{target.head_sha}/check-runs?check_name={CHECK_NAME}")
    earlier = sorted(
        (r for r in (listed or {}).get("check_runs", []) if r.get("name") == CHECK_NAME),
        key=lambda r: int(r.get("id", 0)),
    )
    made = None
    if earlier:
        try:
            made = api.request("PATCH", f"{target.path}/check-runs/{earlier[-1]['id']}", body)
        except GitHubError:
            made = None  # another app's check run of that name: this token makes its own
    action = "updated"
    if made is None:
        made = api.request(
            "POST", f"{target.path}/check-runs", {**body, "head_sha": target.head_sha}
        )
        action = "created"
    check_id = (made.data or {}).get("id")
    for batch in rest:  # each update adds its annotations to those already there
        api.request(
            "PATCH",
            f"{target.path}/check-runs/{check_id}",
            {"output": {**output, "annotations": batch}},
        )
    return (
        f"check run {CHECK_NAME}: {action}, {CONCLUSION[card['status']]}, {len(marks)} annotations"
    )


def identity(api: GitHubApi) -> str | None:
    """The token's user, or None for a GitHub App's token (Actions' ``GITHUB_TOKEN`` among
    them), which ``GET /user`` refuses: such a token writes as a bot."""
    try:
        found = api.get("/user")
    except GitHubError:
        return None
    login = found.get("login") if isinstance(found, dict) else None
    return login if isinstance(login, str) else None


def _ours(comment: Mapping[str, Any], me: str | None) -> bool:
    user = comment.get("user") or {}
    return user.get("login") == me if me is not None else user.get("type") == "Bot"


def comment(api: GitHubApi, target: Target, card: Mapping[str, Any]) -> str:
    """Updates Repro's comment on the pull request, or creates it; what was done, in words."""
    body = f"{MARKER}\n" + cut(render(card), BODY_MAX - len(MARKER) - 1, card["run_id"])
    me = identity(api)
    issue = f"{target.path}/issues/{target.number}/comments"
    mine = [
        c
        for c in api.pages(issue)
        if isinstance(c, dict) and MARKER in str(c.get("body", "")) and _ours(c, me)
    ]
    if mine:
        try:
            api.request("PATCH", f"{target.path}/issues/comments/{mine[-1]['id']}", {"body": body})
        except GitHubError:
            pass  # it can no longer be edited: a new one replaces it
        else:
            return "comment: updated"
    api.request("POST", issue, {"body": body})
    return "comment: created"


def job_summary(path: Path, card: Mapping[str, Any]) -> str:
    """Appends the Markdown card to the step's summary file, under its 1 MiB."""
    data = cut(render(card), SUMMARY_MAX_BYTES // 4, card["run_id"])  # 4 bytes a character at most
    with path.open("a", encoding="utf-8") as summary:
        summary.write(data + "\n")
    return "job summary: written"


@dataclass
class Reported:
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def report(
    api: GitHubApi,
    card: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    target: Target,
    *,
    summary: Path | None,
    check: bool = True,
    comment_on: bool = True,
) -> Reported:
    """Each target made or updated; one that fails does not stop the others."""
    found = Reported()
    steps: list[tuple[str, str, Any]] = []
    if check:
        steps.append(
            (
                "the check run",
                "checks: write",
                lambda: check_run(api, target, card, annotations(card, events)),
            )
        )
    if comment_on:
        steps.append(("the comment", "pull-requests: write", lambda: comment(api, target, card)))
    if summary is not None:
        steps.append(("the job summary", "", lambda: job_summary(summary, card)))
    for what, permission, make in steps:
        try:
            found.done.append(make())
        except (GitHubError, OSError) as exc:
            needs = f" (a workflow's token needs {permission})" if permission else ""
            found.failed.append(f"{what}: {exc}{needs}")
    return found
