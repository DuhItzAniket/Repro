"""Removing credentials from event content before it is stored (ARCHITECTURE §5.3).

Payloads must never carry environment variables, API keys or tokens; this is the defence in
depth behind that rule. Only formats with a documented, distinctive shape are matched, so code
and test output are not mangled by guesses:

- GitHub tokens: ``ghp_`` (personal, classic), ``github_pat_`` (fine-grained), ``gho_`` (OAuth),
  ``ghu_``, ``ghs_`` and ``ghr_`` (GitHub Apps) [https://docs.github.com/en/authentication/
  keeping-your-account-and-data-secure/about-authentication-to-github, checked 2026-10-14];
- AWS access key IDs: ``AKIA`` (access keys) and ``ASIA`` (temporary keys)
  [https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html, checked
  2026-10-14];
- PEM-encoded private keys: the ``-----BEGIN … PRIVATE KEY-----`` block (RFC 7468);
- ``Bearer`` credentials, as sent in an ``Authorization`` header (RFC 6750 §2.1).
"""

import re
from typing import Any, Final

REDACTED: Final = "[redacted]"

_PATTERNS: Final = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_.-]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16,}\b"),
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
)


def scrub_text(text: str) -> str:
    """``text`` with every recognised credential replaced by ``[redacted]``."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub(value: Any) -> Any:
    """A copy of ``value`` with credentials removed from every string, at any depth."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value
