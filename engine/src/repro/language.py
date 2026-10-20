"""The language of a change's target (K08): which pipeline ``repro run`` gives it.

Python's marks at the repository's root are the files its provisioning reads (D03):
``pyproject.toml``, ``setup.py``, ``setup.cfg`` and requirement files. JavaScript's is a
``package.json``. A root with both is taken as Python's, whose pipeline is the complete one;
``repro run --language javascript`` chooses the other. Head's root is read, then base's (a
change can add a project's files, or remove them). A root with neither is Python's: its
pipeline then records what it could not read.
"""

from typing import Final, Literal, get_args

from repro.gitops import Git

Language = Literal["python", "javascript"]
LANGUAGES: Final = get_args(Language)
#: Python's marks; any ``requirements*.txt`` or ``*requirements.txt`` is one too.
PYTHON: Final = frozenset({"pyproject.toml", "setup.py", "setup.cfg"})
JAVASCRIPT: Final = "package.json"


def root_files(git: Git, commit: str) -> set[str]:
    """The names at the root of ``commit``'s tree."""
    listed = git.run("ls-tree", "-z", "--name-only", commit)
    return {name.decode("utf-8", "surrogateescape") for name in listed.split(b"\0") if name}


def _python(names: set[str]) -> bool:
    return bool(names & PYTHON) or any(
        name.endswith(".txt") and "requirements" in name for name in names
    )


def detect(git: Git, base: str, head: str) -> Language:
    """The target's language, from its root files on head, else on base."""
    for commit in (head, base):
        names = root_files(git, commit)
        if _python(names):
            return "python"
        if JAVASCRIPT in names:
            return "javascript"
    return "python"
