"""Fails to collect: the rest of the suite must still run."""

import a_module_that_does_not_exist  # noqa: F401


def test_never_collected():
    pass
