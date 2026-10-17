"""Fixture repositories that make a run fail in one catalogued way each (H01).

Each head breaks something the way a real change can, so that ``repro run`` meets the failure
for real: a test module that no longer imports, a function that hangs, one that exhausts its
memory, a build that cannot work offline. ``test_failures.py`` runs them end to end and holds
each run to its entry in ``docs/FAILURES.md``.
"""

from fixtures.repo_builder import RepoSpec

_PYPROJECT = '[project]\nname = "{name}"\nversion = "0.1.0"\n'

_TOTAL = '''"""Totals."""


def total(items):
    return sum(items)
'''

_TEST_TOTAL = """from calc.core import total


def test_total():
    assert total([1, 2]) == 3
"""

# Head renames total() and leaves the test that imports it: on head the module cannot be
# collected, so its test is gone from head's run.
BROKEN_IMPORT = RepoSpec(
    name="broken-import",
    description="A test module that no longer imports on head.",
    base={
        "pyproject.toml": _PYPROJECT.format(name="calc-fixture"),
        "calc/__init__.py": "",
        "calc/core.py": _TOTAL,
        "tests/test_core.py": _TEST_TOTAL,
    },
    heads={"rename/total": {"calc/core.py": _TOTAL.replace("def total(", "def sum_items(")}},
    pr_description={"rename/total": "Rename total() to sum_items()"},
)

_WAIT = '''"""Waiting."""

import time


def ready():
    return "ready"


def wait():
    return "done"
'''

_TEST_WAIT = """from slow.core import ready, wait


def test_a_ready():
    assert ready() == "ready"


def test_b_wait():
    assert wait() == "done"
"""

# Head makes wait() hang: the head run reports the first test, then runs into its limit before
# the second reports, so one selected test has no outcome on head.
SLOW_HEAD = RepoSpec(
    name="slow-head",
    description="A change that makes a test hang on head.",
    base={
        "pyproject.toml": _PYPROJECT.format(name="slow-fixture"),
        "slow/__init__.py": "",
        "slow/core.py": _WAIT,
        "tests/test_core.py": _TEST_WAIT,
    },
    heads={
        "change/wait": {
            "slow/core.py": _WAIT.replace('    return "ready"', '    return "ready" + ""').replace(
                '    return "done"', '    time.sleep(3600)\n    return "done"'
            )
        }
    },
    pr_description={"change/wait": "Make wait() wait"},
)

_BUFFER = '''"""Buffers."""


def buffer(size):
    return bytearray(size)
'''

_TEST_BUFFER = """from mem.core import buffer


def test_buffer():
    assert len(buffer(10)) == 10
"""

# Head allocates far more than any sandbox limit allows: the allocation is refused, and the
# test fails on head with MemoryError.
MEMORY_HOG = RepoSpec(
    name="memory-hog",
    description="A change that exhausts the sandbox's memory on head.",
    base={
        "pyproject.toml": _PYPROJECT.format(name="mem-fixture"),
        "mem/__init__.py": "",
        "mem/core.py": _BUFFER,
        "tests/test_core.py": _TEST_BUFFER,
    },
    heads={
        "change/buffer": {
            "mem/core.py": _BUFFER.replace(
                "    return bytearray(size)",
                "    reserve = bytearray(64 * 2**30)\n    return bytearray(size) or reserve",
            )
        }
    },
    pr_description={"change/buffer": "Reserve a buffer"},
)

# Head's build needs a backend that is not on the package index: its own install fails.
BROKEN_BUILD = RepoSpec(
    name="broken-build",
    description="A change whose project cannot be built offline.",
    base={
        "pyproject.toml": _PYPROJECT.format(name="build-fixture"),
        "build_fixture/__init__.py": "",
        "build_fixture/core.py": _TOTAL,
        "tests/test_core.py": _TEST_TOTAL.replace("calc.core", "build_fixture.core"),
    },
    heads={
        "change/backend": {
            "pyproject.toml": _PYPROJECT.format(name="build-fixture")
            + '\n[build-system]\nrequires = ["repro-fixture-no-such-backend==1.0"]\n'
            'build-backend = "repro_fixture_no_such_backend"\n'
        }
    },
    pr_description={"change/backend": "Use our own build backend"},
)

# The suite cannot start on either side: its conftest.py imports a plugin the environment does
# not have. Head changes no code, so no test is selected, and every run Repro makes ends before
# it reports a test (H06: such a change was VERIFIED, as when no container could load Repro's
# own pytest plugin).
SUITE_CANNOT_START = RepoSpec(
    name="suite-cannot-start",
    description="A test suite that cannot start on either side; the change touches no code.",
    base={
        "pyproject.toml": _PYPROJECT.format(name="calc-fixture"),
        "README.md": "Totals.\n",
        "calc/__init__.py": "",
        "calc/core.py": _TOTAL,
        "tests/conftest.py": "import repro_fixture_no_such_plugin  # noqa: F401\n",
        "tests/test_core.py": _TEST_TOTAL,
    },
    heads={"docs/readme": {"README.md": "Totals of numbers.\n"}},
    pr_description={"docs/readme": "Say what is totalled"},
)

FAILURE_SPECS = {
    spec.name: spec
    for spec in (BROKEN_IMPORT, SLOW_HEAD, MEMORY_HOG, BROKEN_BUILD, SUITE_CANNOT_START)
}
