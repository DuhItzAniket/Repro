"""The ``repro`` command line.

``doctor`` and ``serve`` work. ``run``, ``replay`` and ``export`` take the options their phases
need and exit with status 2, naming the phase that brings them: nothing pretends to work.

Global options override the environment and the configuration file (``repro.config``). Logs go
to stderr; a command's output goes to stdout.
"""

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from repro import __version__
from repro.config import CONFIG_ENV, Settings, SettingsError, load_settings
from repro.doctor import Check, Machine, diagnose
from repro.logs import configure_logging, get_logger

#: Exit status of a command that is not available yet.
NOT_YET = 2
#: The API's port: a project choice (C04).
DEFAULT_PORT = 8780
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

log = get_logger("cli")

app = typer.Typer(
    name="repro",
    help="Reproduce agent-written changes base-vs-head and verify their claims.",
    no_args_is_help=True,
    add_completion=False,
)


class LogLevelOption(StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class LogFormatOption(StrEnum):
    json = "json"
    text = "text"


class ExportFormat(StrEnum):
    md = "md"
    json = "json"
    in_toto = "in-toto"
    sarif = "sarif"
    junit = "junit"


@dataclass(slots=True)
class Session:
    """What the global options asked for; settings are resolved when a command needs them."""

    config: Path | None = None
    overrides: dict[str, object] = field(default_factory=dict)
    _settings: Settings | None = None

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.config is not None:
            env[CONFIG_ENV] = str(self.config)
        return env

    def settings(self) -> Settings:
        """The resolved settings, or exit 2 with the configuration error on stderr."""
        if self._settings is None:
            try:
                self._settings = load_settings(env=self.environment(), overrides=self.overrides)
            except SettingsError as exc:
                typer.echo(f"repro: configuration error: {exc}", err=True)
                raise typer.Exit(2) from None
            configure_logging(self._settings.log_level, self._settings.log_format)
        return self._settings


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"repro {__version__}")
        raise typer.Exit()


def _session(ctx: typer.Context) -> Session:
    session = ctx.obj
    if not isinstance(session, Session):  # invoked without the callback (not via `repro`)
        session = Session()
        ctx.obj = session
    return session


def _not_yet(command: str, arrives: str, **request: object) -> NoReturn:
    log.debug("not available yet", extra={"fields": {"command": command, **request}})
    typer.echo(f"repro {command}: not available yet; it arrives in {arrives}.", err=True)
    raise typer.Exit(NOT_YET)


@app.callback()
def main(
    ctx: typer.Context,
    *,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help=f"Configuration file (default: ${CONFIG_ENV}, else config.toml in the data "
            "directory).",
            dir_okay=False,
        ),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", help="Where Repro keeps its database and artifacts."),
    ] = None,
    log_level: Annotated[
        LogLevelOption | None, typer.Option("--log-level", help="Log level (stderr).")
    ] = None,
    log_format: Annotated[
        LogFormatOption | None,
        typer.Option("--log-format", help="Log format: JSON lines or text (stderr)."),
    ] = None,
) -> None:
    """Reproduce agent-written changes base-vs-head and verify their claims."""
    overrides: dict[str, object] = {}
    if data_dir is not None:
        overrides["data_dir"] = str(data_dir)
    if log_level is not None:
        overrides["log_level"] = log_level.value
    if log_format is not None:
        overrides["log_format"] = log_format.value
    ctx.obj = Session(config=config, overrides=overrides)


@app.command()
def doctor(
    ctx: typer.Context,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print one machine-readable JSON report.")
    ] = False,
) -> None:
    """Check that this machine can run Repro: Python, git, uv, Docker and the data paths."""
    session = _session(ctx)
    extra: list[Check] = []
    try:
        settings = load_settings(env=session.environment(), overrides=session.overrides)
    except SettingsError as exc:
        # Doctor still runs, on the defaults, and reports the configuration as the problem.
        extra.append(
            Check("config", "fail", str(exc), hint="Fix the setting it names", required=True)
        )
        try:
            settings = load_settings(
                env={k: v for k, v in os.environ.items() if not k.startswith("REPRO_")}
            )
        except SettingsError as fallback:
            typer.echo(f"repro: configuration error: {fallback}", err=True)
            raise typer.Exit(2) from None
    configure_logging(settings.log_level, settings.log_format)
    report = diagnose(
        data_dir=settings.data_dir,
        run_root=settings.run_root,
        version=__version__,
        machine=Machine(),
        extra=extra,
    )
    typer.echo(report.to_json() if as_json else report.to_text())
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def run(
    ctx: typer.Context,
    repo: Annotated[Path, typer.Option("--repo", help="The target repository.")],
    base: Annotated[str, typer.Option("--base", help="The base ref.")],
    head: Annotated[str, typer.Option("--head", help="The head ref.")],
) -> None:
    """Reproduce a change: run base and head, and record what each side does."""
    _session(ctx).settings()
    _not_yet(
        "run",
        "C08 (end to end, on the orchestrator from C03)",
        repo=str(repo),
        base=base,
        head=head,
    )


@app.command()
def replay(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="A run ID or an event log (.jsonl).")],
) -> None:
    """Replay a recorded run in the cockpit, exactly as it happened."""
    _session(ctx).settings()
    _not_yet("replay", "C08 (live UI wiring)", source=source)


@app.command()
def serve(
    ctx: typer.Context,
    host: Annotated[str, typer.Option("--host", help="Loopback address to listen on.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port.")] = DEFAULT_PORT,
    allow_origin: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-origin",
            help="Another origin whose pages may open the event stream (a dev server). Repeatable.",
        ),
    ] = None,
) -> None:
    """Serve the read-only API and the event stream on this machine (the cockpit arrives in C08)."""
    settings = _session(ctx).settings()
    if host not in LOOPBACK:
        typer.echo(
            f"repro serve: {host} is not a loopback address. Until the per-session token "
            "arrives (H03), the API listens on 127.0.0.1 or ::1 only.",
            err=True,
        )
        raise typer.Exit(2)
    # Imported here: the API's dependencies are not needed by the other commands.
    import uvicorn  # noqa: PLC0415

    from repro.api import create_app  # noqa: PLC0415

    shown = f"[{host}]" if ":" in host else host
    origins = {f"http://{shown}:{port}", f"http://localhost:{port}", *(allow_origin or [])}
    api = create_app(settings.paths.database, runs_dir=settings.paths.runs, allowed_origins=origins)
    log.info("serving", extra={"fields": {"host": host, "port": port}})
    typer.echo(f"repro: serving http://{shown}:{port} (read-only; Ctrl+C to stop)", err=True)
    uvicorn.run(api, host=host, port=port, log_level=settings.log_level, ws="websockets-sansio")


@app.command()
def export(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(metavar="RUN", help="The run to export.")],
    output_format: Annotated[
        ExportFormat, typer.Option("--format", help="The card format.")
    ] = ExportFormat.md,
) -> None:
    """Export a run's Reproduction Card."""
    _session(ctx).settings()
    _not_yet("export", "F05 (the card) and H04 (exporters)", run=run_id, format=output_format.value)
