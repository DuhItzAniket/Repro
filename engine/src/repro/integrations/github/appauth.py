"""A GitHub App's credentials, and the tokens it acts with (I04, ADR-0019).

The App's files live in Repro's data directory, under ``github-app/``:

- ``app.json``: what identifies it (its ID, client ID, slug, name and page, the account it
  belongs to, its webhook URL). Nothing secret;
- ``private-key.pem`` and ``webhook-secret``: written by ``repro app register`` straight from
  GitHub's answer. On POSIX they are created readable by their owner alone (mode 0600); on
  Windows they inherit the user's profile's permissions. Repro never prints, logs or passes
  them on.

The App proves itself with a JWT signed with RS256: ``iat`` 60 seconds in the past for clock
drift, ``exp`` at most 10 minutes ahead, ``iss`` the client ID, which GitHub recommends. It acts
on a repository with an installation token from ``POST /app/installations/{id}/access_tokens``,
which expires after an hour and can be limited to some repositories and permissions
[docs.github.com, "Generating a JSON Web Token (JWT) for a GitHub App" and "Generating an
installation access token for a GitHub App", read on 2026-10-21]. Repro asks for one
repository and the four permissions a run needs, each time.
"""

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import jwt

from repro.integrations.github.api import GitHubApi, GitHubError

APP_DIR: Final = "github-app"
#: What a run needs: its check run, its comment and the pull request, the code, and who asked.
PERMISSIONS: Final[Mapping[str, str]] = {
    "checks": "write",
    "pull_requests": "write",
    "contents": "read",
    "metadata": "read",
}
#: ``iat`` this far back, for clock drift; ``exp`` this far ahead, under GitHub's 10 minutes.
JWT_BACK_S: Final = 60
JWT_AHEAD_S: Final = 540


class AppError(Exception):
    """The App's files are missing or unusable; the message says what to do."""


@dataclass(frozen=True)
class AppIdentity:
    id: int
    client_id: str
    slug: str
    name: str
    html_url: str
    owner: str
    webhook_url: str

    @property
    def bot_login(self) -> str:
        """The login its comments are written under."""
        return f"{self.slug}[bot]"


@dataclass(frozen=True)
class AppFiles:
    root: Path

    @classmethod
    def under(cls, data_dir: Path) -> "AppFiles":
        return cls(data_dir / APP_DIR)

    @property
    def identity(self) -> Path:
        return self.root / "app.json"

    @property
    def private_key(self) -> Path:
        return self.root / "private-key.pem"

    @property
    def webhook_secret(self) -> Path:
        return self.root / "webhook-secret"

    @property
    def deliveries(self) -> Path:
        return self.root / "deliveries.db"

    def exists(self) -> bool:
        return self.identity.exists()


def _private(path: Path, data: bytes) -> None:
    """``data`` into a new file readable by its owner alone (POSIX), replacing ``path``."""
    path.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(data)


def save(files: AppFiles, identity: AppIdentity, pem: str, secret: str) -> None:
    files.root.mkdir(parents=True, exist_ok=True)
    _private(files.private_key, pem.encode("utf-8"))
    _private(files.webhook_secret, secret.encode("utf-8"))
    files.identity.write_text(json.dumps(asdict(identity), indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Credentials:
    identity: AppIdentity
    private_key: bytes
    webhook_secret: bytes

    def __repr__(self) -> str:  # never the key or the secret, in a traceback or a log
        return f"Credentials({self.identity.slug!r})"


def load(files: AppFiles) -> Credentials:
    if not files.exists():
        raise AppError(f"no GitHub App is registered in {files.root}: run `repro app register`")
    try:
        found = json.loads(files.identity.read_text(encoding="utf-8"))
        identity = AppIdentity(**{key: found[key] for key in AppIdentity.__dataclass_fields__})
        key = files.private_key.read_bytes()
        secret = files.webhook_secret.read_bytes().strip()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AppError(f"the GitHub App's files in {files.root} cannot be read: {exc}") from None
    if not key or not secret:
        raise AppError(f"the GitHub App's key or secret in {files.root} is empty")
    return Credentials(identity, key, secret)


def app_jwt(credentials: Credentials, now: Callable[[], float] = time.time) -> str:
    """The App's own token: a JWT, signed with its private key, valid for nine minutes."""
    at = int(now())
    claims = {
        "iat": at - JWT_BACK_S,
        "exp": at + JWT_AHEAD_S,
        "iss": credentials.identity.client_id,
    }
    try:
        return jwt.encode(claims, credentials.private_key, algorithm="RS256")
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise AppError(f"the GitHub App's private key cannot sign: {exc}") from None


def as_app(credentials: Credentials, api_url: str) -> GitHubApi:
    return GitHubApi(
        base_url=api_url,
        token=app_jwt(credentials),
        token_source="the App's JWT",  # noqa: S106 - where the token came from, for messages
    )


def installation_api(
    credentials: Credentials, api_url: str, installation: int, repository: str
) -> GitHubApi:
    """The API as the installation, on ``repository`` (its name, without the owner) alone, with
    ``PERMISSIONS``: a token for an hour."""
    body: dict[str, Any] = {"repositories": [repository], "permissions": dict(PERMISSIONS)}
    answer = as_app(credentials, api_url).request(
        "POST", f"/app/installations/{installation}/access_tokens", body
    )
    token = (answer.data or {}).get("token") if isinstance(answer.data, dict) else None
    if not isinstance(token, str) or not token:
        raise GitHubError(f"GitHub gave installation {installation} no token")
    return GitHubApi(
        base_url=api_url,
        token=token,
        token_source="the App's installation token",  # noqa: S106 - a description, for messages
    )
