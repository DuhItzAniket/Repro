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
from pathlib import Path
from typing import Final

#: Shorter "homes" (a root) would swallow every absolute path.
MIN_HOME: Final = 3
_DELIMITER: Final = re.compile(r"<(/?)(untrusted_)", re.IGNORECASE)
_ATTRIBUTE: Final = re.compile(r'[^"<>&\x00-\x1f]*')
#: A relative Windows path to a Python file, as pytest prints a location (``tests\a\b.py:3``).
_WINDOWS_PY_PATH: Final = re.compile(r"(?<![\w\\/:.])(?:[\w.-]+\\)+[\w.-]+\.py(?=[:\s\"')]|$)")


def neutralise(text: str) -> str:
    """``text`` with every delimiter it could use to leave its block written harmlessly."""
    return _DELIMITER.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def _homes() -> list[str]:
    home = str(Path.home())
    if len(home) < MIN_HOME:  # a root "home" would swallow every absolute path
        return []
    forms = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    return sorted(forms, key=len, reverse=True)


def without_home(text: str) -> str:
    """``text`` with the user's home directory, in either separator, written ``~``."""
    for home in _homes():
        text = text.replace(home, "~")
    return text


def portable(text: str) -> str:
    """``text`` as every machine would render it: LF line ends, ``~`` for the home directory,
    ``/`` in pytest's file locations."""
    text = without_home(text.replace("\r\n", "\n").replace("\r", "\n"))
    return _WINDOWS_PY_PATH.sub(lambda m: m.group(0).replace("\\", "/"), text)


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
