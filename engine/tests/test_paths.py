"""Default data paths per platform, computed from the environment alone (C01)."""

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from repro.paths import (
    RUN_ROOT_BUDGET,
    DataPaths,
    PathError,
    default_data_dir,
    default_run_root,
    short_id,
)

WINDOWS_ENV = {
    "USERPROFILE": r"C:\Users\dev",
    "LOCALAPPDATA": r"C:\Users\dev\AppData\Local",
}


def test_windows_data_dir_is_under_the_user_profile() -> None:
    assert default_data_dir(WINDOWS_ENV, windows=True) == PureWindowsPath(r"C:\Users\dev\.repro")


def test_windows_falls_back_to_homedrive_and_homepath() -> None:
    env = {"HOMEDRIVE": "D:", "HOMEPATH": r"\Users\dev"}
    assert default_data_dir(env, windows=True) == PureWindowsPath(r"D:\Users\dev\.repro")


def test_windows_run_root_is_short_and_under_local_app_data() -> None:
    data_dir = default_data_dir(WINDOWS_ENV, windows=True)
    root = default_run_root(WINDOWS_ENV, windows=True, data_dir=data_dir)
    assert root == PureWindowsPath(r"C:\Users\dev\AppData\Local\repro\r")
    assert len(str(root)) <= RUN_ROOT_BUDGET


def test_windows_run_root_falls_back_to_the_data_dir() -> None:
    env = {"USERPROFILE": r"C:\Users\dev"}
    data_dir = default_data_dir(env, windows=True)
    assert default_run_root(env, windows=True, data_dir=data_dir) == PureWindowsPath(
        r"C:\Users\dev\.repro\r"
    )


def test_posix_paths_are_under_home() -> None:
    env = {"HOME": "/home/dev", "LOCALAPPDATA": "ignored"}
    data_dir = default_data_dir(env, windows=False)
    assert data_dir == PurePosixPath("/home/dev/.repro")
    assert default_run_root(env, windows=False, data_dir=data_dir) == PurePosixPath(
        "/home/dev/.repro/r"
    )


@pytest.mark.parametrize(("env", "windows"), [({}, True), ({"HOMEDRIVE": "C:"}, True), ({}, False)])
def test_a_missing_home_is_an_error(env: dict[str, str], windows: bool) -> None:
    with pytest.raises(PathError):
        default_data_dir(env, windows=windows)


def test_short_id_takes_the_random_end_of_a_ulid() -> None:
    assert short_id("01J9ZQ4R6M3X8T2K5V7N0P1QWE") == "7n0p1qwe"
    assert short_id("run_01J9ZQ4R6M3X8T2K5V7N0P1QWE") == "7n0p1qwe"  # separators are dropped
    assert short_id("01J9ZQ4R6M3X8T2K5V7N0-P1QWE") == "7n0p1qwe"
    with pytest.raises(ValueError, match="too short"):
        short_id("abc")


def test_data_paths_lay_out_the_files() -> None:
    paths = DataPaths(Path("data"), Path("scratch"))
    assert paths.database == Path("data", "repro.db")
    assert paths.runs == Path("data", "runs")
    assert paths.logs == Path("data", "logs")
    assert paths.scratch("01J9ZQ4R6M3X8T2K5V7N0P1QWE") == Path("scratch", "7n0p1qwe")


def test_a_scratch_path_stays_within_the_budget_on_windows() -> None:
    root = default_run_root(
        WINDOWS_ENV, windows=True, data_dir=default_data_dir(WINDOWS_ENV, windows=True)
    )
    scratch = root / short_id("01J9ZQ4R6M3X8T2K5V7N0P1QWE")
    assert len(str(scratch)) <= RUN_ROOT_BUDGET
    assert "\\" in str(scratch)  # a real Windows path, whatever OS runs the test
