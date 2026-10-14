"""Starts coverage.py's sys.monitoring core before Repro's plugin configures (E01's test of
two tools at once; copied into a snapshot as conftest.py)."""

import json
import os
import sys

import coverage

os.environ["COVERAGE_CORE"] = "sysmon"
COVERAGE = coverage.Coverage(data_file=None)
COVERAGE.start()


def pytest_sessionfinish(session):
    tools = {tool: sys.monitoring.get_tool(tool) for tool in range(6)}
    COVERAGE.stop()
    measured = sorted(os.path.basename(f) for f in COVERAGE.get_data().measured_files())
    with open(os.path.join(os.environ["REPRO_OUT"], "coverage.json"), "w") as handle:
        json.dump({"tools": tools, "measured": measured}, handle)
