"""Each repository file's dotted module name, from the file list alone (nothing is imported).

A directory holding an ``__init__.py`` is a regular package (Python language reference, §5.2.1),
so a file's name walks up through such directories, and the first directory that is not one is
its import root: pytest's default ``prepend`` import mode finds a test file's root the same way.
So ``engine/src/repro/api/stream.py`` is ``repro.api.stream``, and a ``tests/test_api.py`` with
no ``tests/__init__.py`` is ``test_api``.

Two files that would share a name (``scripts/util.py`` and ``tools/util.py``, on either side)
are named by their whole path instead (``scripts.util``), on both sides, so a file's name does
not change because another file appeared. A file with no unique dotted name of identifiers
(``my-tool.py``, a top-level ``__init__.py``, ``pkg.py`` beside ``pkg/__init__.py``) has none.
"""

from collections import Counter
from collections.abc import Collection, Sequence


def _dotted(parts: Sequence[str]) -> str | None:
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _from_root(path: str, files: Collection[str]) -> str | None:
    parts = path[: -len(".py")].split("/")
    root = len(parts) - 1
    while root > 0 and "/".join(parts[:root]) + "/__init__.py" in files:
        root -= 1
    return _dotted(parts[root:])


def module_names(
    base_files: Collection[str], head_files: Collection[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """The module name of each nameable ``.py`` file on base and on head."""
    sides = [
        {path: _from_root(path, files) for path in files if path.endswith(".py")}
        for files in (base_files, head_files)
    ]
    shared = {
        name
        for side in sides
        for name, count in Counter(side.values()).items()
        if name is not None and count > 1
    }
    named: list[dict[str, str]] = []
    for side in sides:
        final = {
            path: _dotted(path[: -len(".py")].split("/")) if name in shared else name
            for path, name in side.items()
        }
        counts = Counter(final.values())
        named.append(
            {path: name for path, name in final.items() if name is not None and counts[name] == 1}
        )
    return named[0], named[1]
