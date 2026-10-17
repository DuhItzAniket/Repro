"""A pull request, from its URL to what a run compares (I01).

``PrUrl`` parses the address a person copies from the browser. ``read_pr`` reads the pull request
from the REST API (``GET /repos/{owner}/{repo}/pulls/{pull_number}``): its base and head (ref and
commit), its title and description, and where its commits can be fetched from, the base
repository [GitHub REST API docs, "Get a pull request", checked 2026-10-17]. What the API says is
checked before anything uses it: a commit is 40 hex digits, a ref is a ref.
"""

import re
from dataclasses import dataclass
from typing import Any, Final

from repro.integrations.github.api import DEFAULT_API_URL, GitHubApi, GitHubError

_URL: Final = re.compile(
    r"^https://(?P<host>[A-Za-z0-9.-]+(?::\d+)?)/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9._-]{1,100})/pull/(?P<number>[1-9][0-9]{0,9})(?:[/?#].*)?$"
)
_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
#: A branch name as git allows it, kept to what a refspec can carry safely.
_REF: Final = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/+-]{1,250}(?<![./])$")
TITLE_MAX: Final = 500  # the schema's run.started pr.title
GITHUB_COM: Final = "github.com"


@dataclass(frozen=True)
class PrUrl:
    """``https://<host>/<owner>/<repo>/pull/<number>``, a tab's path or query allowed after it."""

    host: str
    owner: str
    repo: str
    number: int

    @classmethod
    def parse(cls, url: str) -> "PrUrl":
        found = _URL.match(url.strip())
        if found is None:
            raise GitHubError(
                f"{url!r} is not a pull request's address "
                "(https://github.com/<owner>/<repo>/pull/<number>)"
            )
        repo = found["repo"].removesuffix(".git")
        if repo in {".", ".."}:
            raise GitHubError(f"{url!r} names no repository")
        return cls(found["host"].lower(), found["owner"], repo, int(found["number"]))

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    def check_api(self, api_url: str) -> None:
        """A pull request on another host needs that host's API, set in ``github_api_url``."""
        if self.host != GITHUB_COM and api_url.rstrip("/") == DEFAULT_API_URL:
            raise GitHubError(
                f"{self.host} is not github.com: set github_api_url to its API "
                f"(https://{self.host}/api/v3 on GitHub Enterprise Server)"
            )


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str  # the page, html_url
    title: str
    body: str
    state: str
    draft: bool
    repo_full_name: str  # the base repository
    repo_url: str  # its page
    clone_url: str  # where its commits are fetched from
    base_ref: str
    base_sha: str
    head_label: str  # owner:branch, as GitHub shows a fork's head
    head_sha: str
    fork: bool


def _field(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            raise GitHubError(f"GitHub's answer has no {'.'.join(path)}")
        data = data[key]
    return data


def _text(data: Any, *path: str) -> str:
    value = _field(data, *path)
    if not isinstance(value, str):
        raise GitHubError(f"GitHub's answer has no {'.'.join(path)}")
    return value


def _sha(data: Any, *path: str) -> str:
    value = _text(data, *path)
    if not _SHA.match(value):
        raise GitHubError(f"GitHub's {'.'.join(path)} is not a commit: {value[:60]!r}")
    return value


def read_pr(api: GitHubApi, url: PrUrl) -> PullRequest:
    """The pull request at ``url``, read from ``api`` (raises ``GitHubError``)."""
    data = api.get(f"/repos/{url.owner}/{url.repo}/pulls/{url.number}")
    base_ref = _text(data, "base", "ref")
    if not _REF.match(base_ref):
        raise GitHubError(f"the base branch's name is not one Repro can fetch: {base_ref[:60]!r}")
    head_repo = _field(data, "head").get("repo") if isinstance(data.get("head"), dict) else None
    base_repo = _text(data, "base", "repo", "full_name")
    head_full = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    body = data.get("body")
    return PullRequest(
        number=url.number,
        url=_text(data, "html_url"),
        title=_text(data, "title")[:TITLE_MAX],
        body=body if isinstance(body, str) else "",
        state=_text(data, "state"),
        draft=data.get("draft") is True,
        repo_full_name=base_repo,
        repo_url=_text(data, "base", "repo", "html_url"),
        clone_url=_text(data, "base", "repo", "clone_url"),
        base_ref=base_ref,
        base_sha=_sha(data, "base", "sha"),
        head_label=_text(data, "head", "label")[:200],
        head_sha=_sha(data, "head", "sha"),
        fork=head_full != base_repo,  # a deleted fork has no head repository at all
    )
