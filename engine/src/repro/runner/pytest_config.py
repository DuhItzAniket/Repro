"""What the project's own pytest configuration selects, kept when Repro runs its tests (H02).

Repro runs pytest with ``-o addopts=``: a project's ``addopts`` can turn on coverage, parallel
workers, ``--lf`` or ``-x``, which would change what a run reports or make it slower. But
``addopts`` also says which tests the project runs at all. click's, for one, has
``-m 'not stress'``, which leaves out 31,000 high-iteration stress tests (measured on click
f67c2bb, 2026-10-17: with it, pytest reports "2014 passed, 102 skipped, 31000 deselected, 1
xfailed" in about 6 s; without it, Repro collected 33,117 tests and base's run did not finish
in 900 s). Running the tests a project deselects is slower and judges the change on tests its
authors do not run.

So the options of ``addopts`` that decide which tests run, and how they are collected, are
kept, and only those:
- selection: ``-m``, ``-k``, ``--ignore``, ``--ignore-glob``, ``--deselect``;
- collection: ``--import-mode``, ``--doctest-modules``, ``--doctest-glob``, ``-p no:<plugin>``;
- strictness: ``--strict-markers``, ``--strict-config``, ``-W``, ``--pythonwarnings``.

Everything else is dropped. The configuration file is the one pytest would use, found in its
order:
- ``pytest.ini`` or ``.pytest.ini``;
- ``pyproject.toml`` with ``[tool.pytest]`` or ``[tool.pytest.ini_options]``;
- ``tox.ini`` with ``[pytest]``;
- ``setup.cfg`` with ``[tool:pytest]``.

It is read as data; nothing of the project runs.
"""

import configparser
import shlex
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

#: Options kept with their value (``--name value``, ``--name=value``, ``-xvalue``).
WITH_VALUE: Final = frozenset(
    {"-m", "-k", "--ignore", "--ignore-glob", "--deselect", "--import-mode", "-W",
     "--pythonwarnings", "--doctest-glob", "-p"}
)  # fmt: skip
#: Options kept alone.
FLAGS: Final = frozenset({"--doctest-modules", "--strict-markers", "--strict-config"})
_SHORT: Final = ("-m", "-k", "-W", "-p")


def _ini(path: Path, section: str) -> Any:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None
    if not parser.has_section(section):
        return None
    return parser.get(section, "addopts", fallback="")


def addopts(root: Path) -> list[str]:
    """The ``addopts`` of the configuration file pytest would use in ``root``, split; none if
    there is none or it cannot be read."""
    for name in ("pytest.ini", ".pytest.ini"):
        if (root / name).is_file():
            return _split(_ini(root / name, "pytest"))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            tool = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {})
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            tool = {}
        pytest = tool.get("pytest") if isinstance(tool, dict) else None
        if isinstance(pytest, dict):
            native = {k: v for k, v in pytest.items() if k != "ini_options"}
            found = native.get("addopts") if native else None
            if found is None and isinstance(pytest.get("ini_options"), dict):
                found = pytest["ini_options"].get("addopts")
            if native or "ini_options" in pytest:
                return _split(found)
    for name, section in (("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        if (root / name).is_file():
            found = _ini(root / name, section)
            if found is not None:
                return _split(found)
    return []


def _split(value: Any) -> list[str]:
    if isinstance(value, list):  # pytest's native TOML: already one argument an item
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    try:
        return shlex.split(value, posix=True)
    except ValueError:  # an unclosed quote: pytest would refuse it too
        return []


def _wanted(option: str, value: str) -> bool:
    """Of ``-p``, only disabling a plugin is kept: the project's own plugins load anyway."""
    return option != "-p" or value.startswith("no:")


def kept(options: Sequence[str]) -> list[str]:
    """The options of ``options`` that select or collect tests (see the module), each with its
    value, in their order."""
    found: list[str] = []
    index = 0
    while index < len(options):
        option = options[index]
        name, equals, attached = option.partition("=")
        if option in FLAGS:
            found.append(option)
        elif name in WITH_VALUE and equals:  # --name=value
            if _wanted(name, attached):
                found.append(option)
        elif option in WITH_VALUE and index + 1 < len(options):  # --name value
            if _wanted(option, options[index + 1]):
                found += [option, options[index + 1]]
            index += 1
        elif option[:2] in _SHORT and option[2:] and _wanted(option[:2], option[2:]):  # -mvalue
            found.append(option)
        index += 1
    return found


def selection(root: Path) -> list[str]:
    """What Repro adds to its own pytest options for the project at ``root``."""
    return kept(addopts(root))
