"""Starts coverage.py's sys.monitoring core before Repro's plugin configures (E01's test of
two tools at once; copied into a snapshot as conftest.py)."""

import os

import coverage

os.environ["COVERAGE_CORE"] = "sysmon"
COVERAGE = coverage.Coverage(data_file=None)
COVERAGE.start()


def pytest_sessionfinish(session):
    COVERAGE.stop()
    measured = COVERAGE.get_data().measured_files()
    with open(os.path.join(os.environ["REPRO_OUT"], "coverage-files.txt"), "w") as handle:
        handle.write("\n".join(sorted(os.path.basename(f) for f in measured)))
