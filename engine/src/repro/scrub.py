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

Every string is also made encodable (H02). A file name Python decoded with surrogate escapes
(an undecodable byte becomes a lone surrogate such as ``\\udcff``) cannot be stored or sent as
UTF-8 JSON; each such character is written as its escape instead, as text (in a target, whose
paths allow no backslash, as U+FFFD, the replacement character), so that a target's odd file
name is shown rather than failing the job that reports it. Observed on click f67c2bb: a test
writes a file whose name holds such a byte.
"""

import re
from typing import Any, Final

REDACTED: Final = "[redacted]"
#: The code points of lone surrogates, which UTF-8 cannot encode.
_SURROGATES: Final = range(0xD800, 0xE000)

_PATTERNS: Final = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_.-]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16,}\b"),
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
)


def encodable(text: str, *, escape: bool = True) -> str:
    """``text`` with any character UTF-8 cannot encode (a lone surrogate) written as its
    escape, ``\\udcff``, or with ``escape`` false as U+FFFD."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        if escape:
            return text.encode("utf-8", "backslashreplace").decode("utf-8")
        return "".join("\ufffd" if ord(c) in _SURROGATES else c for c in text)
    return text


def scrub_text(text: str, *, escape: bool = True) -> str:
    """``text`` encodable, with every recognised credential replaced by ``[redacted]``."""
    text = encodable(text, escape=escape)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub(value: Any, *, escape: bool = True) -> Any:
    """A copy of ``value`` with credentials removed from every string, at any depth; with
    ``escape`` false (a target's paths), unencodable characters become U+FFFD."""
    if isinstance(value, str):
        return scrub_text(value, escape=escape)
    if isinstance(value, dict):
        return {
            encodable(key, escape=escape) if isinstance(key, str) else key: scrub(
                item, escape=escape
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item, escape=escape) for item in value]
    return value
