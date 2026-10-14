"""Engine settings: precedence, validation and error messages that name their source (C01)."""

from pathlib import Path

import pytest

from repro.config import CONFIG_ENV, SETTING_NAMES, Settings, SettingsError, load_settings


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def environment(home: Path, **variables: str) -> dict[str, str]:
    """A clean environment whose home is ``home`` (both platforms' variables)."""
    return {"HOME": str(home), "USERPROFILE": str(home), **variables}


def write_config(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_put_the_data_under_home(home: Path) -> None:
    settings = load_settings(env=environment(home))
    assert settings.data_dir == home / ".repro"
    assert settings.log_level == "info"
    assert settings.log_format == "json"
    assert settings.sandbox == "auto"
    assert 1 <= settings.concurrency <= 4
    assert settings.paths.database == home / ".repro" / "repro.db"


def test_the_file_in_the_data_dir_is_read(home: Path) -> None:
    write_config(home / ".repro", 'log_level = "debug"\nconcurrency = 3\n')
    settings = load_settings(env=environment(home))
    assert (settings.log_level, settings.concurrency) == ("debug", 3)


def test_precedence_is_flag_then_environment_then_file_then_default(home: Path) -> None:
    write_config(home / ".repro", 'log_level = "debug"\nlog_format = "text"\nconcurrency = 3\n')
    env = environment(home, REPRO_LOG_LEVEL="warning", REPRO_LOG_FORMAT="json")
    settings = load_settings(env=env, overrides={"log_level": "error"})
    assert settings.log_level == "error"  # the flag beats the variable and the file
    assert settings.log_format == "json"  # the variable beats the file
    assert settings.concurrency == 3  # the file beats the default
    assert settings.sandbox == "auto"  # the default


def test_an_empty_variable_counts_as_unset(home: Path) -> None:
    settings = load_settings(env=environment(home, REPRO_LOG_LEVEL=""))
    assert settings.log_level == "info"


def test_values_are_case_insensitive(home: Path) -> None:
    settings = load_settings(env=environment(home, REPRO_SANDBOX="Docker", REPRO_LOG_LEVEL="INFO"))
    assert (settings.sandbox, settings.log_level) == ("docker", "info")


def test_repro_config_names_the_file_and_it_must_exist(home: Path, tmp_path: Path) -> None:
    path = write_config(tmp_path / "elsewhere", 'sandbox = "process"\n')
    settings = load_settings(env=environment(home, **{CONFIG_ENV: str(path)}))
    assert settings.sandbox == "process"
    missing = tmp_path / "missing.toml"
    with pytest.raises(
        SettingsError, match=r"REPRO_CONFIG=.*missing\.toml: the file does not exist"
    ):
        load_settings(env=environment(home, **{CONFIG_ENV: str(missing)}))


def test_a_data_dir_from_the_environment_moves_the_file_too(home: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_config(data, "concurrency = 2\n")
    settings = load_settings(env=environment(home, REPRO_DATA_DIR=str(data)))
    assert (settings.data_dir, settings.concurrency) == (data, 2)
    # No LOCALAPPDATA in this environment, so the run root follows the data directory.
    assert settings.run_root == data / "r"


def test_tilde_expands_to_the_injected_home(home: Path) -> None:
    settings = load_settings(env=environment(home, REPRO_DATA_DIR="~/somewhere"))
    assert settings.data_dir == home / "somewhere"


def test_an_unknown_key_in_the_file_is_an_error_naming_it(home: Path) -> None:
    path = write_config(home / ".repro", 'log_levle = "debug"\n')
    with pytest.raises(SettingsError) as raised:
        load_settings(env=environment(home))
    message = str(raised.value)
    assert str(path) in message
    assert "log_levle" in message
    for name in SETTING_NAMES:
        assert name in message  # the known names, to fix the typo


def test_an_invalid_value_names_its_source(home: Path) -> None:
    with pytest.raises(SettingsError, match=r"REPRO_CONCURRENCY: .*'many'"):
        load_settings(env=environment(home, REPRO_CONCURRENCY="many"))
    write_config(home / ".repro", "concurrency = 0\n")
    with pytest.raises(SettingsError, match=r"config\.toml \(concurrency\): .*greater than"):
        load_settings(env=environment(home))
    with pytest.raises(SettingsError, match=r"--sandbox: "):
        load_settings(env=environment(home), overrides={"sandbox": "vm"})


def test_relative_paths_are_rejected(home: Path) -> None:
    with pytest.raises(SettingsError, match=r"REPRO_RUN_ROOT: .*absolute"):
        load_settings(env=environment(home, REPRO_RUN_ROOT="relative/dir"))
    with pytest.raises(SettingsError, match=r"REPRO_UI_DIR: .*absolute"):
        load_settings(env=environment(home, REPRO_UI_DIR="apps/web/dist"))


def test_the_cockpit_directory_is_unset_by_default_and_expands_home(home: Path) -> None:
    assert load_settings(env=environment(home)).ui_dir is None
    settings = load_settings(env=environment(home, REPRO_UI_DIR="~/cockpit"))
    assert settings.ui_dir == home / "cockpit"


def test_malformed_toml_is_an_error_naming_the_file(home: Path) -> None:
    path = write_config(home / ".repro", "log_level = \n")
    with pytest.raises(SettingsError, match="not valid TOML") as raised:
        load_settings(env=environment(home))
    assert str(path) in str(raised.value)


def test_unknown_overrides_are_rejected(home: Path) -> None:
    with pytest.raises(SettingsError, match="unknown setting colour"):
        load_settings(env=environment(home), overrides={"colour": "blue"})


def test_without_a_home_the_data_dir_must_be_set(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="REPRO_DATA_DIR"):
        load_settings(env={})
    settings = load_settings(env={"REPRO_DATA_DIR": str(tmp_path)})
    assert settings.data_dir == tmp_path


def test_settings_are_frozen(home: Path) -> None:
    settings = load_settings(env=environment(home))
    with pytest.raises(ValueError, match="frozen"):
        settings.log_level = "debug"
    assert isinstance(settings, Settings)
