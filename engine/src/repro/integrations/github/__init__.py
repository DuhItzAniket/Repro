"""GitHub (Stage I). A pull request read from its URL (I01): ``ingest`` gives the repository
holding its commits, the pull request as the API describes it, and the commit to compare its head
with, the merge base of its base and head.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from repro.gitops import Git
from repro.integrations.github.api import (
    API_VERSION,
    DEFAULT_API_URL,
    TOKEN_VARIABLES,
    GitHubApi,
    GitHubError,
)
from repro.integrations.github.mirror import fetch, has_commit, merge_base, mirror_path
from repro.integrations.github.pr import PrUrl, PullRequest, read_pr

__all__ = [
    "API_VERSION",
    "DEFAULT_API_URL",
    "TOKEN_VARIABLES",
    "GitHubApi",
    "GitHubError",
    "Ingested",
    "PrUrl",
    "PullRequest",
    "ingest",
    "mirror_path",
]


@dataclass(frozen=True)
class Ingested:
    git: Git
    pr: PullRequest
    #: The merge base of the pull request's base and head: what its head is compared with.
    base: str


def ingest(
    address: str,
    *,
    api_url: str,
    mirrors: Path,
    local: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Ingested:
    """The pull request at ``address``, ready to run (raises ``GitHubError``).

    Its commits come from Repro's mirror under ``mirrors``, fetched now; or, with ``local``, from
    that clone as it is: Repro fetches nothing into a user's repository.
    """
    url = PrUrl.parse(address)
    url.check_api(api_url)
    api = GitHubApi.from_environment(api_url, env)
    pr = read_pr(api, url)
    if local is None:
        git = fetch(pr, url, mirrors, api_url=api.base_url, token=api.token)
    else:
        git = Git(local)
        if not git.is_repository():
            raise GitHubError(f"{local} is not a git repository")
        if not all(has_commit(git, sha) for sha in (pr.base_sha, pr.head_sha)):
            raise GitHubError(
                f"{local} does not hold the pull request's commits; fetch them into it with "
                f"`git fetch {pr.clone_url} {pr.base_ref} pull/{pr.number}/head`, or leave out "
                "--repo and Repro fetches them into its own mirror"
            )
    return Ingested(git, pr, merge_base(git, pr))
