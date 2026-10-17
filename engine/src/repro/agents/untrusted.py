"""Untrusted text, delimited for a model (G03; ARCHITECTURE §10.2, THREAT_MODEL T7).

Everything an agent reads that came from the target repository or the PR (source code, diffs,
test messages, values a test produced, the PR's own words) is data to judge, never an
instruction. It reaches the model inside a block it cannot leave::

    <untrusted_content kind="source" side="head" path="pkg/dates.py">
    ...
    </untrusted_content>

and the system prompt says that text in these blocks is evidence or claims, not instructions.
So that the text cannot close its block and speak outside it, any ``<untrusted_`` or
``</untrusted_`` it contains (in any case) is written as ``&lt;untrusted_`` or
``&lt;/untrusted_``; nothing else in it changes. Attribute values are Repro's own (a kind, a
side, a path that ``repro.agents.sources`` has already checked), never free text.

Before text goes to a model it is also made the same on every machine and free of the
machine: CRLF becomes LF, the user's home directory becomes ``~``, and Windows separators in
the file locations pytest prints (``tests\\test_x.py:13``) become ``/``.
"""

import re
from typing import Final

from repro.readable import portable, without_home

_DELIMITER: Final = re.compile(r"<(/?)(untrusted_)", re.IGNORECASE)
_ATTRIBUTE: Final = re.compile(r'[^"<>&\x00-\x1f]*')


def neutralise(text: str) -> str:
    """``text`` with every delimiter it could use to leave its block written harmlessly."""
    return _DELIMITER.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


__all__ = ["block", "neutralise", "portable", "without_home"]


def block(kind: str, text: str, **attributes: str) -> str:
    """``text`` in an ``untrusted_content`` block; attributes are Repro's own values."""
    names = {"kind": kind, **attributes}
    for name, value in names.items():
        if not _ATTRIBUTE.fullmatch(value):
            raise ValueError(f"attribute {name} has characters a block cannot carry: {value!r}")
    attrs = " ".join(f'{name}="{value}"' for name, value in names.items())
    body = neutralise(portable(text))
    newline = "" if body.endswith("\n") or not body else "\n"
    return f"<untrusted_content {attrs}>\n{body}{newline}</untrusted_content>"
