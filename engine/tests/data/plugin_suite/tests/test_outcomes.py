"""One test per outcome the plugin reports, in each phase a test can end."""

import pytest


def test_passes():
    assert 1 + 1 == 2


def test_fails():
    assert 1 + 1 == 3, "arithmetic is off"


@pytest.mark.skip(reason="skipped by a marker")
def test_skipped_by_marker():
    raise AssertionError("never runs")


def test_skips_itself():
    pytest.skip("skipped from inside")


@pytest.mark.xfail(reason="known bug")
def test_xfails():
    raise ValueError("the known bug")


@pytest.mark.xfail(reason="known bug, fixed meanwhile")
def test_xpasses():
    assert True


@pytest.mark.xfail(reason="must fail", strict=True)
def test_strict_xpass_fails():
    assert True


@pytest.fixture
def broken_setup():
    raise RuntimeError("the fixture's setup broke")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("the fixture's teardown broke")


def test_setup_error(broken_setup):
    raise AssertionError("never runs")


def test_teardown_error(broken_teardown):
    assert True


def test_failure_outranks_teardown_error(broken_teardown):
    raise AssertionError("the call failed first")


@pytest.mark.parametrize("value", [1, 2])
def test_parametrized(value):
    assert value == 1
