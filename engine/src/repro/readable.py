"""Text a person reads on a card: free of the machine, and short (H01).

What fails in a run is reported in words a user can act on, and a card may be shared, so the
text it carries is made the same on every machine first:
- CRLF becomes LF;
- the user's home directory becomes ``~``;
- Windows separators in the file locations pytest prints (``tests\\test_x.py:13``) become
  ``/``.

An error is reported by its type and the first line of its message, never a traceback. A
traceback is reported by the line that names its error.
"""

import re
from pathlib import Path
from typing import Final

#: Shorter "homes" (a root) would swallow every absolute path.
MIN_HOME: Final = 3
#: A relative Windows path to a Python file, as pytest prints a location (``tests\a\b.py:3``).
_WINDOWS_PY_PATH: Final = re.compile(r"(?<![\w\\/:.])(?:[\w.-]+\\)+[\w.-]+\.py(?=[:\s\"')]|$)")
#: The line of a traceback that names its error: ``E   ImportError: ...`` or ``ValueError: ...``.
_ERROR_LINE: Final = re.compile(r"^(?:E\s+)?((?:[\w.]+\.)?\w*(?:Error|Exception|Exit)\b.*)$")
REASON_MAX: Final = 300


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


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def reason(error: BaseException, limit: int = REASON_MAX) -> str:
    """``Type: the first line of its message``, portable and at most ``limit`` characters."""
    lines = [line.strip() for line in portable(str(error)).split("\n") if line.strip()]
    name = type(error).__name__
    return _cut(f"{name}: {lines[0]}" if lines else name, limit)


def error_line(traceback: str, limit: int = REASON_MAX) -> str:
    """The line of ``traceback`` that names its error (the last such line), portable and at
    most ``limit`` characters; its last non-empty line if none does."""
    lines = [line.strip() for line in portable(traceback).split("\n") if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        found = _ERROR_LINE.match(line)
        if found:
            return _cut(found.group(1), limit)
    return _cut(lines[-1], limit)
