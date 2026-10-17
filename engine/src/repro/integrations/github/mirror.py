"""The commits a pull request compares, fetched into a mirror of Repro's own (I01).

The mirror is a bare repository under Repro's data directory (``repos/<host>/<owner>/<repo>.git``),
never the user's clone: fetching into it would add refs and objects nobody asked for. From the
base repository it fetches the base branch and ``refs/pull/<n>/head``, the read-only ref GitHub
keeps there for every pull request, from a fork too [GitHub docs, "Checking out pull requests
locally", checked 2026-10-17].

With a token, git authenticates as ``actions/checkout`` does: an ``AUTHORIZATION: basic`` header
of ``x-access-token:<token>``, for that host only [actions/checkout, ``src/git-auth-helper.ts``,
checked 2026-10-17]. It is set through ``GIT_CONFIG_COUNT`` and its pairs, which git reads from
the environment, so the token is on no command line [git-config, ENVIRONMENT, checked
2026-10-17].
"""

import base64
import urllib.parse
from pathlib import Path
from typing import Final

from repro.gitops import Git, GitError
from repro.integrations.github.api import GitHubError, is_loopback
from repro.integrations.github.pr import PrUrl, PullRequest

FETCH_TIMEOUT_S: Final = 1800.0  # a large repository's first fetch


class _Authenticated(Git):
    """Git with an ``extraheader`` for one origin, from the environment."""

    def __init__(self, repo: Path, origin: str | None, token: str | None) -> None:
        super().__init__(repo, timeout_s=FETCH_TIMEOUT_S)
        self.origin = origin
        self.token = token

    def environment(self) -> dict[str, str]:
        env = super().environment()
        if self.origin and self.token:
            credential = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
            env |= {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"http.{self.origin}/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credential}",
            }
        return env


def mirror_path(root: Path, url: PrUrl) -> Path:
    return root / url.host.replace(":", "_") / url.owner / f"{url.repo}.git"


def _origin(clone_url: str, api_url: str) -> str | None:
    """The origin the token may go to, or None for a local test remote; refuses the rest."""
    parts = urllib.parse.urlsplit(clone_url)
    if parts.scheme == "https":
        return f"https://{parts.netloc}"
    if is_loopback(api_url) and parts.scheme in {"file", "http"}:
        return None  # a test's remote, behind a loopback API: no token goes to it
    raise GitHubError(f"GitHub gave a clone URL Repro does not fetch from: {clone_url[:100]!r}")


def fetch(pr: PullRequest, url: PrUrl, root: Path, *, api_url: str, token: str | None) -> Git:
    """The mirror, holding the pull request's base branch and head (raises ``GitHubError``)."""
    path = mirror_path(root, url)
    path.mkdir(parents=True, exist_ok=True)
    git = _Authenticated(path, _origin(pr.clone_url, api_url), token)
    head_ref = f"refs/repro/pull/{pr.number}/head"
    try:
        if not (path / "HEAD").is_file():
            git.run("init", "--bare", "--quiet")
        git.run(
            "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--end-of-options",
            pr.clone_url,
            f"+refs/heads/{pr.base_ref}:refs/repro/base/{pr.base_ref}",
            f"+refs/pull/{pr.number}/head:{head_ref}",
        )  # fmt: skip
    except GitError as exc:
        raise GitHubError(f"fetching {url.full_name}'s pull request failed: {exc}") from None
    for sha, what in ((pr.head_sha, "head"), (pr.base_sha, "base")):
        if not has_commit(git, sha):
            raise GitHubError(
                f"the pull request's {what} commit {sha[:12]} is not in what GitHub served: it "
                "may have been updated while it was read; run again"
            )
    return git


def has_commit(git: Git, sha: str) -> bool:
    try:
        git.run("cat-file", "-e", "--end-of-options", f"{sha}^{{commit}}")
    except GitError:
        return False
    return True


def merge_base(git: Git, pr: PullRequest) -> str:
    """Where the pull request's branch left its base: what GitHub's "Files changed" compares."""
    try:
        return git.text("merge-base", "--end-of-options", pr.base_sha, pr.head_sha)
    except GitError:
        raise GitHubError(
            f"the pull request's base {pr.base_sha[:12]} and head {pr.head_sha[:12]} share no "
            "history"
        ) from None
