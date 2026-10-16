"""Engine settings (ARCHITECTURE §12).

Each setting comes from the first of these that gives it:

1. a command-line flag (``overrides``);
2. an environment variable, ``REPRO_`` plus the setting's name in capitals
   (``REPRO_LOG_LEVEL``); an empty variable counts as unset;
3. the TOML file: ``REPRO_CONFIG`` if set (it must exist), else ``config.toml`` in the data
   directory given by a flag, the variable or the default (it may be missing);
4. the default.

Unknown keys and invalid values are errors naming where they came from, so a typo in a file or
a variable is never silently ignored. Paths must be absolute after ``~`` is expanded.
"""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from repro.paths import (
    CONFIG_FILE_NAME,
    DATA_DIR_NAME,
    DataPaths,
    PathError,
    default_data_dir,
    default_run_root,
)

LogLevel = Literal["debug", "info", "warning", "error"]
LogFormat = Literal["json", "text"]
#: Which sandbox runs target code (ADR-0004): Docker when available, or as asked.
SandboxChoice = Literal["auto", "docker", "process"]
#: Which backend runs the agent stages (G04; ADR-0007, ADR-0016); ``off``: deterministic only.
AgentsChoice = Literal["off", "claude", "groq", "openai"]
#: ``live`` calls the model; ``record`` calls it and writes cassettes; ``replay`` only reads
#: cassettes, and fails without one (G02).
AgentMode = Literal["live", "record", "replay"]

ENV_PREFIX = "REPRO_"
CONFIG_ENV = "REPRO_CONFIG"
MAX_CONCURRENCY = 64


def default_concurrency() -> int:
    """Jobs run at once (C03): up to 4, never more than the machine's CPUs."""
    return max(1, min(4, os.cpu_count() or 1))


class Settings(BaseModel):
    """The engine's resolved settings. Frozen: pass a new one rather than changing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: Path
    run_root: Path
    log_level: LogLevel = "info"
    log_format: LogFormat = "json"
    concurrency: int = Field(default_factory=default_concurrency, ge=1, le=MAX_CONCURRENCY)
    sandbox: SandboxChoice = "auto"
    #: The built cockpit (``pnpm build``'s ``apps/web/dist``); unset: this checkout's, if built.
    ui_dir: Path | None = None
    #: The agent stages' backend; off by default, so no run reaches a model unless asked to.
    agents: AgentsChoice = "off"
    #: The model the agents use; unset: the backend's default (``repro.agents.setup``).
    agent_model: str | None = None
    #: An OpenAI-compatible endpoint's base URL (``agents = "openai"``), and the environment
    #: variable holding its key (unset: the endpoint takes none, as a local server).
    agent_base_url: str | None = None
    agent_api_key_env: str | None = None
    agent_mode: AgentMode = "live"
    #: Where cassettes are read and written (``record`` and ``replay``).
    agent_cassettes: Path | None = None
    #: The most a run's agent calls may cost together, in estimated US dollars.
    agent_budget_usd: float = Field(default=2.0, gt=0)
    #: Whether the probe writer proposes inputs for the probes (G07) when the agents are on.
    agent_probes: bool = True

    @field_validator("log_level", "log_format", "sandbox", "agents", "agent_mode", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("data_dir", "run_root", "ui_dir", "agent_cassettes")
    @classmethod
    def _absolute(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("must be an absolute path")
        return value

    @model_validator(mode="after")
    def _agents_complete(self) -> "Settings":
        if self.agents == "openai" and not (self.agent_base_url and self.agent_model):
            raise ValueError("agents = openai needs agent_base_url and agent_model")
        if self.agent_mode != "live" and self.agent_cassettes is None:
            raise ValueError(f"agent_mode = {self.agent_mode} needs agent_cassettes")
        return self

    @property
    def paths(self) -> DataPaths:
        return DataPaths(self.data_dir, self.run_root)


#: Every setting's name, in declaration order.
SETTING_NAMES: tuple[str, ...] = tuple(Settings.model_fields)


class SettingsError(ValueError):
    """Configuration that cannot be used; the message names its source."""


def env_name(setting: str) -> str:
    return ENV_PREFIX + setting.upper()


def _expand(value: object, home: PurePath | None) -> object:
    """``~`` and ``~/…`` become the user's home, as the injected environment gives it.

    ``~user`` is not expanded: it stays relative and is rejected as such.
    """
    if not isinstance(value, str) or home is None:
        return value
    if value == "~":
        return str(home)
    if value.startswith(("~/", "~\\")):
        return str(home / value[2:])
    return value


def _read_file(path: Path, *, required: bool) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        if required:
            raise SettingsError(f"{CONFIG_ENV}={path}: the file does not exist") from None
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: not valid TOML: {exc}") from None
    except OSError as exc:
        raise SettingsError(f"{path}: cannot be read: {exc.strerror or exc}") from None
    unknown = sorted(set(data) - set(SETTING_NAMES))
    if unknown:
        raise SettingsError(
            f"{path}: unknown setting {', '.join(unknown)} (known: {', '.join(SETTING_NAMES)})"
        )
    return data


_WINDOWS = os.name == "nt"


def _no_home() -> SettingsError:
    return SettingsError(f"cannot find a home directory for the data: set {env_name('data_dir')}")


def _home(env: Mapping[str, str]) -> PurePath | None:
    try:
        return default_data_dir(env, windows=_WINDOWS).parent
    except PathError:
        return None


def _file_layer(
    env: Mapping[str, str], chosen_data_dir: object, home: PurePath | None
) -> tuple[Path, dict[str, object]]:
    """The configuration file's path and contents: given outright, or in the data directory."""
    explicit = env.get(CONFIG_ENV, "")
    if explicit:
        path = Path(str(_expand(explicit, home)))
        return path, _read_file(path, required=True)
    if chosen_data_dir is not None:
        base = Path(str(_expand(chosen_data_dir, home)))
    elif home is not None:
        base = Path(default_data_dir(env, windows=_WINDOWS))
    else:
        raise _no_home()
    path = base / CONFIG_FILE_NAME
    # A relative data directory is rejected below; there is no file to read for it.
    return path, (_read_file(path, required=False) if base.is_absolute() else {})


def _validated(values: dict[str, object], sources: dict[str, str]) -> Settings:
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            name = str(error["loc"][0]) if error["loc"] else "settings"
            source = sources.get(name, name)
            problems.append(f"{source}: {error['msg']} (got {values.get(name)!r})")
        raise SettingsError("; ".join(problems)) from None


def load_settings(
    *,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> Settings:
    """Resolves the settings from flags, the environment, the file and the defaults."""
    env = os.environ if env is None else env
    flags = {key: value for key, value in (overrides or {}).items() if value is not None}
    unknown = sorted(set(flags) - set(SETTING_NAMES))
    if unknown:
        raise SettingsError(f"unknown setting {', '.join(unknown)}")
    from_env = {
        name: env[env_name(name)] for name in SETTING_NAMES if env.get(env_name(name), "") != ""
    }
    home = _home(env)
    config_path, from_file = _file_layer(env, flags.get("data_dir", from_env.get("data_dir")), home)

    # Layer the sources, lowest first, remembering where each value came from.
    values: dict[str, object] = {}
    sources: dict[str, str] = {}
    layers = (
        (from_file, lambda name: f"{config_path} ({name})"),
        (from_env, env_name),
        (flags, lambda name: f"--{name.replace('_', '-')}"),
    )
    for layer, source in layers:
        for name, value in layer.items():
            values[name], sources[name] = value, source(name)
    for name in ("data_dir", "run_root", "ui_dir", "agent_cassettes"):
        if name in values:
            values[name] = _expand(values[name], home)

    if "data_dir" not in values:
        if home is None:
            raise _no_home()
        values["data_dir"], sources["data_dir"] = str(home / DATA_DIR_NAME), "the default"
    if "run_root" not in values:
        data_dir = PurePath(str(values["data_dir"]))
        values["run_root"] = str(default_run_root(env, windows=_WINDOWS, data_dir=data_dir))
        sources["run_root"] = "the default"
    return _validated(values, sources)
