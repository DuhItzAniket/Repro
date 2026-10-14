"""Where Repro keeps its data (ARCHITECTURE §11, §14).

Two roots, both overridable in the settings:

- the **data directory**, ``~/.repro`` (``%USERPROFILE%\\.repro`` on Windows): the database
  ``repro.db``, run artifacts under ``runs/<run_id>``, logs and ``config.toml``;
- the **run root**, where runs keep scratch snapshots and worktrees of the target repository:
  ``%LOCALAPPDATA%\\repro\\r`` on Windows and ``<data dir>/r`` elsewhere. Each run gets
  ``<run root>/<8 characters of its ID>``. Windows paths are limited to 260 characters unless
  long paths are enabled, and a target repository's own paths come on top, so the root is kept
  short.

The defaults are computed purely from an environment mapping, as Windows or POSIX paths, so
both flavours are tested on any OS. Nothing here touches the filesystem.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

#: Characters a run root may take before ``repro doctor`` warns. A project choice: it leaves 180
#: of Windows' 260 for the paths inside a target repository when long paths are not enabled.
RUN_ROOT_BUDGET = 80

#: Characters of a run ID used for its scratch directory: the end of a ULID, which is random.
SHORT_ID_LENGTH = 8

DATA_DIR_NAME = ".repro"
CONFIG_FILE_NAME = "config.toml"


class PathError(ValueError):
    """The environment does not say where the user's home is."""


def _home(env: Mapping[str, str], windows: bool) -> PurePath:
    """The user's home, by the rules ``os.path.expanduser`` uses on each platform."""
    if windows:
        profile = env.get("USERPROFILE")
        if profile:
            return PureWindowsPath(profile)
        drive, path = env.get("HOMEDRIVE"), env.get("HOMEPATH")
        if drive and path:
            return PureWindowsPath(drive + path)
        raise PathError("neither USERPROFILE nor HOMEDRIVE and HOMEPATH is set")
    home = env.get("HOME")
    if not home:
        raise PathError("HOME is not set")
    return PurePosixPath(home)


def default_data_dir(env: Mapping[str, str], *, windows: bool) -> PurePath:
    """``~/.repro``, from the environment, as a Windows or POSIX path."""
    return _home(env, windows) / DATA_DIR_NAME


def default_run_root(env: Mapping[str, str], *, windows: bool, data_dir: PurePath) -> PurePath:
    """Where runs keep scratch copies: short, under ``%LOCALAPPDATA%`` on Windows."""
    if windows:
        local = env.get("LOCALAPPDATA")
        if local:
            return PureWindowsPath(local) / "repro" / "r"
    return data_dir / "r"


def short_id(run_id: str) -> str:
    """The run's scratch directory name: the last characters of its ID, lowercase."""
    cleaned = "".join(ch for ch in run_id if ch.isalnum())
    if len(cleaned) < SHORT_ID_LENGTH:
        raise ValueError(f"run ID too short for a scratch directory: {run_id!r}")
    return cleaned[-SHORT_ID_LENGTH:].lower()


@dataclass(frozen=True, slots=True)
class DataPaths:
    """The files and directories under the two roots."""

    data_dir: Path
    run_root: Path

    @property
    def database(self) -> Path:
        return self.data_dir / "repro.db"

    @property
    def runs(self) -> Path:
        """Per-run artifacts (C02): ``runs/<run_id>``."""
        return self.data_dir / "runs"

    @property
    def logs(self) -> Path:
        return self.data_dir / "logs"

    def scratch(self, run_id: str) -> Path:
        """A run's scratch directory under the run root."""
        return self.run_root / short_id(run_id)
