"""Deselected by the project's ``addopts`` (``-m "not stress"``): Repro keeps that choice."""

import pytest


@pytest.mark.stress
def test_deselected_by_the_project():
    raise AssertionError("a test the project deselects ran")
