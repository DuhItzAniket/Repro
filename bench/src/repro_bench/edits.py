"""Edits as models write them, and the diffs Repro makes of them (J04, J05).

A model is asked for edits, never for a diff: a file, an exact snippet of it and the snippet's
replacement. Each edit must match its file exactly once. The diff is then written here, with
``difflib``, from the files before and after.

Two forms are read:
- structured (``{"path", "find", "replace"}``), for models whose JSON output is reliable;
- search/replace blocks in plain text, for models whose structured output is not reliable
  (J05: Qwen 3.8 on Groq answered a schema with malformed JSON). The blocks are Aider's "diff"
  edit format [aider.chat, "Edit formats", checked 2026-10-18], with the path on a ``FILE:``
  line rather than alone::

      FILE: path/to/file.py
      <<<<<<< SEARCH
      exact lines
      =======
      replacement
      >>>>>>> REPLACE
"""

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from repro.gitops import Git, GitError

_BLOCK: Final = re.compile(
    r"^FILE:[ \t]*(?P<path>\S+)[ \t]*\n<<<<<<< SEARCH\n(?P<find>.*?)\n?=======\n"
    r"(?P<replace>.*?)\n?>>>>>>> REPLACE[ \t]*$",
    re.M | re.S,
)


class EditError(Exception):
    """Edits that cannot be made into a patch; the message says why."""


@dataclass(frozen=True)
class Edit:
    path: str
    find: str
    replace: str

    @classmethod
    def of(cls, given: Mapping[str, object]) -> "Edit":
        return cls(
            str(given["path"]).strip().lstrip("./"), str(given["find"]), str(given["replace"])
        )


def parse_blocks(text: str) -> list[Edit]:
    """The search/replace blocks in a model's answer, in order."""
    found = []
    for block in _BLOCK.finditer(text.replace("\r\n", "\n")):
        find = block["find"]
        replace = block["replace"]
        found.append(Edit(block["path"].strip().lstrip("./"), find + "\n" if find else "",
                          replace + "\n" if replace else ""))  # fmt: skip
    return found


def read(git: Git, commit: str, path: str) -> str | None:
    try:
        return git.run("show", f"{commit}:{path}").decode("utf-8")
    except (GitError, UnicodeDecodeError):
        return None


def apply(git: Git, commit: str, edits: Iterable[Edit]) -> dict[str, str]:
    """The files ``edits`` change, as they are after them, read from ``commit`` (raises
    ``EditError`` when a file does not exist there or a snippet does not occur exactly once).
    An edit with an empty snippet creates its file."""
    after: dict[str, str] = {}
    for edit in edits:
        text = after.get(edit.path)
        if text is None:
            text = read(git, commit, edit.path)
        if text is None:
            if edit.find:
                raise EditError(f"{edit.path} is not a file at {commit[:12]}")
            after[edit.path] = edit.replace
            continue
        count = text.count(edit.find) if edit.find else 0
        if count != 1:
            raise EditError(f"an edit's snippet occurs {count} times in {edit.path}")
        after[edit.path] = text.replace(edit.find, edit.replace, 1)
    return after


def diff(git: Git, base: str, after: Mapping[str, str], also: Sequence[str] = ()) -> str:
    """The diff from ``base`` to ``after``'s files (and ``also``'s, read from ``after`` when
    given there, else unchanged), with git's headers (raises ``EditError`` when empty)."""
    lines: list[str] = []
    for path in sorted(set(after) | set(also)):
        old = read(git, base, path) or ""
        new = after.get(path, old)
        hunk = list(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                         f"a/{path}", f"b/{path}"))  # fmt: skip
        if hunk:
            if not hunk[-1].endswith("\n"):
                hunk[-1] += "\n\\ No newline at end of file\n"
            lines += [f"diff --git a/{path} b/{path}\n", *hunk]
    if not lines:
        raise EditError("the edits change nothing")
    return "".join(lines)
