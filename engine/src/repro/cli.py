"""The ``repro`` command line.

``doctor``, ``run``, ``replay``, ``serve`` and ``export``.

``run``, ``replay`` and ``serve`` serve the cockpit on a loopback port: ``run`` streams its run
live from the same process, ``replay`` shows a stored run or an event log from the start, after
assembling its card again from the log and checking it against the one the run published
(F05). ``export`` writes that card as Markdown or canonical JSON, or for other tools as an
in-toto attestation, SARIF or JUnit XML (H04).

Global options override the environment and the configuration file (``repro.config``). Logs go
to stderr; a command's output goes to stdout.
"""

import html
import json
import os
import re
import socket
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from repro import __version__
from repro.config import CONFIG_ENV, Settings, SettingsError, load_settings
from repro.doctor import Check, Machine, check_cockpit, diagnose
from repro.logs import adopt, configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import FastAPI

    from repro.bus import EventBus
    from repro.card import Regenerated
    from repro.gitops import Git
    from repro.orchestrator import Job, Orchestrator, RunHandle, RunResult
    from repro.pipeline import Change

#: The API's port: a project choice (C04).
DEFAULT_PORT = 8780
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
#: How long ``run`` waits for a cancelled run to wind down after Ctrl+C.
STOP_WAIT_S = 30.0
_RUN_ID = re.compile(r"^run_[0-9A-HJKMNP-TV-Z]{26}$")

HostOption = Annotated[str, typer.Option("--host", help="Loopback address to listen on.")]
PortOption = Annotated[int, typer.Option("--port", min=1, max=65535, help="Port.")]
OpenOption = Annotated[bool, typer.Option("--open", help="Open the cockpit in the browser.")]
AllowOriginOption = Annotated[
    list[str] | None,
    typer.Option(
        "--allow-origin",
        help="Another origin whose pages may open the event stream (a dev server). Repeatable.",
    ),
]

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
    from repro.api.ui import find_ui  # noqa: PLC0415

    report = diagnose(
        data_dir=settings.data_dir,
        run_root=settings.run_root,
        version=__version__,
        machine=Machine(),
        extra=extra,
        sandbox=settings.sandbox,
        cockpit=check_cockpit(find_ui(settings.ui_dir)),
    )
    typer.echo(report.to_json() if as_json else report.to_text())
    if not report.ok:
        raise typer.Exit(1)


def _bind(host: str, port: int) -> socket.socket:
    """The listening socket, open before anything starts, so a busy port fails at once."""
    if host not in LOOPBACK:
        typer.echo(
            f"repro: {host} is not a loopback address. The cockpit listens on 127.0.0.1 or ::1 "
            "only: its token would cross the network in clear text (THREAT_MODEL T13).",
            err=True,
        )
        raise typer.Exit(2)
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform != "win32":  # on Windows, SO_REUSEADDR would let another process share it
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        # Listening from now on: a browser opened as soon as the URL is printed waits in the
        # backlog until the server accepts, instead of being refused.
        sock.listen()
    except OSError as exc:
        sock.close()
        typer.echo(f"repro: cannot listen on {host}:{port}: {exc.strerror or exc}", err=True)
        raise typer.Exit(2) from None
    return sock


def _serve(
    settings: Settings,
    sock: socket.socket,
    *,
    page: str,
    allow_origin: list[str] | None,
    bus: "EventBus | None" = None,
    replay_log: Path | None = None,
    open_browser: bool = False,
    started: Callable[[], None] | None = None,
) -> None:
    """Serves the API and the cockpit on ``sock`` until Ctrl+C; ``page`` is the URL to show."""
    # Imported here: the API's dependencies are not needed by the other commands.
    from repro.api import create_app  # noqa: PLC0415
    from repro.api.token import new_token  # noqa: PLC0415
    from repro.api.ui import find_ui  # noqa: PLC0415

    host, port = sock.getsockname()[:2]
    shown = f"[{host}]" if ":" in host else host
    origins = {f"http://{shown}:{port}", f"http://localhost:{port}", *(allow_origin or [])}
    ui = find_ui(settings.ui_dir)
    token = new_token()  # this server's only: the URL below carries it (THREAT_MODEL T13)
    api = create_app(
        settings.paths.database,
        runs_dir=settings.paths.runs,
        bus=bus,
        allowed_origins=origins,
        ui_dir=ui,
        replay_log=replay_log,
        token=token,
    )
    url = f"http://{shown}:{port}{page}#token={token}"
    if ui is None:
        typer.echo(
            "repro: the cockpit is not built (pnpm build) or ui_dir holds no index.html; "
            "serving the API only.",
            err=True,
        )
    log.info("serving", extra={"fields": {"host": host, "port": port}})
    typer.echo(f"repro: cockpit at {url} (Ctrl+C to stop)", err=True)
    if started is not None:
        started()
    opener = (
        _opener(url, settings.paths.data_dir, port) if open_browser and ui is not None else None
    )
    try:
        if opener is not None:
            webbrowser.open(opener.as_uri())
        _run_server(api, sock, settings.log_level)
    finally:
        if opener is not None:
            opener.unlink(missing_ok=True)


def _opener(url: str, data_dir: Path, port: int) -> Path:
    """A page only this user can read that sends the browser to ``url`` (THREAT_MODEL T13). The
    browser is started with this file's path, not the URL: a command line can be read by the
    machine's other users (on Linux, ``/proc/<pid>/cmdline``), and the URL holds the token."""
    data_dir.mkdir(parents=True, exist_ok=True)
    page = data_dir / f"open-{port}.html"
    target = html.escape(url, quote=True)
    body = (
        '<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={target}">'
        f'<title>Repro</title><a href="{target}">Open the cockpit</a>\n'
    )
    page.unlink(missing_ok=True)  # created afresh, so the mode below is the file's
    descriptor = os.open(page, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(body)
    return page


def _run_server(api: "FastAPI", sock: socket.socket, log_level: str) -> None:
    """Runs uvicorn on the bound socket until Ctrl+C (tests replace this)."""
    import uvicorn  # noqa: PLC0415

    # No access log: the event stream's request line carries the session token. uvicorn's own
    # lines go through Repro's handler, which redacts it where uvicorn logs a WebSocket (H06).
    adopt("uvicorn")
    config = uvicorn.Config(
        api, log_level=log_level, log_config=None, ws="websockets-sansio", access_log=False
    )
    uvicorn.Server(config).run(sockets=[sock])


def _report(result: "RunResult", database: Path) -> None:
    """The run's last line: how it ended, what it recorded and, once published, its card."""
    from repro.store import StoreReader  # noqa: PLC0415

    counts = ", ".join(f"{count} {name}" for name, count in sorted(result.counts.items()))
    with StoreReader(database) as reader:
        card = reader.card(result.run_id)
    status = f": the card is {card['status']}" if card is not None else ""
    typer.echo(f"repro: {result.run_id} {result.outcome} ({counts}){status}", err=True)


class _Run:
    """One run of ``repro run``: started in the background or run to its end, then reported, and
    what it left (its scratch directory, its containers' volumes) removed as soon as it is over."""

    def __init__(
        self,
        orchestrator: "Orchestrator",
        change: "Change",
        jobs: "Sequence[Job]",
        *,
        run_id: str,
        cleanup: "Callable[[], None]",
        database: Path,
    ) -> None:
        self.orchestrator = orchestrator
        self.database = database
        self.change = change
        self.jobs = jobs
        self.run_id = run_id
        self.cleanup = cleanup
        self.handle: RunHandle | None = None
        self.reporter: threading.Thread | None = None

    def run_to_end(self) -> "RunResult":
        result = self.orchestrator.run(self.change.spec(), self.jobs, run_id=self.run_id)
        _report(result, self.database)
        return result

    def start(self) -> None:
        handle = self.orchestrator.start(self.change.spec(), self.jobs, run_id=self.run_id)
        self.handle = handle

        def finished() -> None:
            _report(handle.wait(), self.database)
            self.cleanup()  # now, not at Ctrl+C: the cockpit needs only the store

        self.reporter = threading.Thread(target=finished, name="repro-run-report", daemon=True)
        self.reporter.start()

    def stop(self) -> None:
        """Cancels the run if it is still going, and waits for it and its report."""
        if self.handle is not None:
            self.handle.cancel()
            try:
                self.handle.wait(STOP_WAIT_S)
            except TimeoutError:
                typer.echo(f"repro run: {self.run_id} did not stop in {STOP_WAIT_S:g} s", err=True)
        if self.reporter is not None:
            self.reporter.join(STOP_WAIT_S)  # it removes the scratch too: one at a time


def _pr_options(
    title: str | None, body: str | None, file: Path | None
) -> tuple[str | None, str | None]:
    """The PR's title and description from the options, or exit 2 saying why not."""
    if file is None:
        return title, body
    if title is not None or body is not None:
        typer.echo("repro run: give --pr-file, or --pr-title and --pr-body, not both", err=True)
        raise typer.Exit(2)
    try:
        first, _, rest = file.read_text(encoding="utf-8").partition("\n")
    except (OSError, UnicodeDecodeError) as exc:
        typer.echo(f"repro run: cannot read {file}: {exc}", err=True)
        raise typer.Exit(2) from None
    return first.strip() or None, rest


def _resolve(repo: Path, base: str, head: str) -> "tuple[Git, Change]":
    """The repository and both commits, or exit 2 saying why not."""
    from repro.gitops import Git, GitError  # noqa: PLC0415
    from repro.pipeline import Change  # noqa: PLC0415

    try:
        git = Git(repo)
    except GitError as exc:  # git itself is missing (H01): a reason, not a traceback
        typer.echo(f"repro run: {exc}", err=True)
        raise typer.Exit(2) from None
    if not git.is_repository():
        typer.echo(f"repro run: {repo} is not a git repository", err=True)
        raise typer.Exit(2)
    try:
        return git, Change.resolve(git, repo, base, head)
    except GitError as exc:
        typer.echo(f"repro run: {exc}", err=True)
        raise typer.Exit(2) from None


def _from_pull_request(
    address: str,
    settings: Settings,
    local: Path | None,
    *,
    given: tuple[str | None, ...],
) -> "tuple[Git, Change, str | None, str | None]":
    """A GitHub pull request read and fetched (I01), or exit 2 saying why not."""
    from repro.integrations.github import GitHubError, ingest  # noqa: PLC0415
    from repro.orchestrator import GitRef  # noqa: PLC0415
    from repro.pipeline import Change  # noqa: PLC0415

    if any(value is not None for value in given):
        typer.echo(
            "repro run: --pr reads the base, head, title and description from GitHub; "
            "leave out --base, --head and --pr-title, --pr-body, --pr-file",
            err=True,
        )
        raise typer.Exit(2)
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        found = ingest(
            address, api_url=settings.github_api_url, mirrors=settings.paths.repos, local=local
        )
    except GitHubError as exc:
        typer.echo(f"repro run: {exc}", err=True)
        raise typer.Exit(2) from None
    pr = found.pr
    source = " from a fork" if pr.fork else ""
    typer.echo(
        f"repro: {pr.repo_full_name}#{pr.number} ({pr.state}{source}): head {pr.head_label} at "
        f"{pr.head_sha[:12]}, against {pr.base_ref} where it branched, {found.base[:12]}",
        err=True,
    )
    change = Change(
        found.git.repo,
        GitRef(pr.base_ref, found.base),
        GitRef(pr.head_label, pr.head_sha),
        repo_name=pr.repo_full_name,
        repo_url=pr.repo_url,
        pr_number=pr.number,
        pr_url=pr.url,
    )
    return found.git, change, pr.title, pr.body


@app.command()
def run(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", help="The target repository.")] = None,
    base: Annotated[str | None, typer.Option("--base", help="The base ref.")] = None,
    head: Annotated[str | None, typer.Option("--head", help="The head ref.")] = None,
    *,
    pr_address: Annotated[
        str | None,
        typer.Option(
            "--pr",
            help="A GitHub pull request's address: its commits, title and description are read "
            "from GitHub (a token from GITHUB_TOKEN or GH_TOKEN, if set).",
        ),
    ] = None,
    serve: Annotated[
        bool, typer.Option("--serve/--no-serve", help="Show the run live in the cockpit.")
    ] = True,
    host: HostOption = "127.0.0.1",
    port: PortOption = DEFAULT_PORT,
    open_browser: OpenOption = False,
    allow_origin: AllowOriginOption = None,
    analyse_only: Annotated[
        bool,
        typer.Option(
            "--analyse-only", help="Only analyse the change: run none of the target's code."
        ),
    ] = False,
    pr_title: Annotated[
        str | None, typer.Option("--pr-title", help="The pull request's title.")
    ] = None,
    pr_body: Annotated[
        str | None, typer.Option("--pr-body", help="The pull request's description.")
    ] = None,
    pr_file: Annotated[
        Path | None,
        typer.Option(
            "--pr-file", help="A UTF-8 file: the pull request's title, then its description."
        ),
    ] = None,
) -> None:
    """Reproduce a change: analyse base and head, run the tests the change can affect on both
    sides, and record what differs.

    Give --repo, --base and --head; or --pr with a GitHub pull request's address, whose head is
    compared with where it left its base branch (their merge base), fetched into Repro's own
    mirror, or found in --repo if given. With agents on (the agents setting), the pull request's
    claims are read from its title and description, or from the commit messages when neither is
    given, and judged against what the run found. With --serve (the default) the cockpit shows
    the run live, and keeps serving after it ends until Ctrl+C. With --no-serve the command waits
    for the run and exits: status 0 if it completed, 1 if it did not.
    """
    pr_title, pr_body = _pr_options(pr_title, pr_body, pr_file)
    settings = _session(ctx).settings()
    from repro.agents.reader import PrText  # noqa: PLC0415
    from repro.agents.setup import agent_setup  # noqa: PLC0415
    from repro.agents.stages import commit_messages  # noqa: PLC0415
    from repro.bus import EventBus  # noqa: PLC0415
    from repro.card.job import StoreCards  # noqa: PLC0415
    from repro.ids import new_run_id  # noqa: PLC0415
    from repro.orchestrator import Orchestrator  # noqa: PLC0415
    from repro.pipeline import pipeline_jobs, remove_work  # noqa: PLC0415
    from repro.sandbox.limits import MIB, Limits  # noqa: PLC0415
    from repro.store import ArtifactStore, StoreWriter  # noqa: PLC0415

    if pr_address is not None:
        git, change, pr_title, pr_body = _from_pull_request(
            pr_address, settings, repo, given=(base, head, pr_title, pr_body)
        )
    elif repo is None or base is None or head is None:
        typer.echo("repro run: give --repo, --base and --head, or --pr", err=True)
        raise typer.Exit(2)
    else:
        git, change = _resolve(repo, base, head)
    sock = _bind(host, port) if serve else None
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    work = settings.paths.scratch(run_id)
    agents = agent_setup(settings, work)
    pr = None
    if agents is not None:
        commits = [] if pr_body else commit_messages(git, change.base.sha, change.head.sha)
        pr = PrText.of(title=pr_title, description=pr_body, commits=commits)
    change = replace(change, pr_title=pr_title, deterministic_only=agents is None)
    writer = StoreWriter(settings.paths.database).start()
    orchestrator = Orchestrator(EventBus(writer), concurrency=settings.concurrency)
    jobs, state = pipeline_jobs(
        git,
        change,
        work,
        backend=settings.sandbox,
        cache=settings.paths.data_dir,
        analyse_only=analyse_only,
        artifacts=ArtifactStore(settings.paths.runs, writer),
        cards=StoreCards(settings.paths.database, writer),
        agents=agents,
        pr=pr,
        limits=Limits(
            timeout_s=settings.test_timeout_s, memory_bytes=settings.memory_limit_mb * MIB
        ),
        docker_runtime=settings.docker_runtime,
        env_image=settings.sandbox_image,
    )
    cleaned = threading.Lock()

    def cleanup() -> None:
        with cleaned:
            state.close()
            remove_work(work)

    job_run = _Run(
        orchestrator, change, jobs, run_id=run_id, cleanup=cleanup, database=settings.paths.database
    )
    try:
        if sock is None:
            if job_run.run_to_end().outcome != "completed":
                raise typer.Exit(1)
            return
        _serve(
            settings,
            sock,
            page=f"/?run={run_id}",
            allow_origin=allow_origin,
            bus=orchestrator.bus,
            open_browser=open_browser,
            started=job_run.start,
        )
    finally:
        job_run.stop()
        writer.close()
        cleanup()


@app.command()
def replay(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="A run ID or an event log (.jsonl).")],
    *,
    host: HostOption = "127.0.0.1",
    port: PortOption = DEFAULT_PORT,
    open_browser: OpenOption = False,
    allow_origin: AllowOriginOption = None,
) -> None:
    """Replay a recorded run in the cockpit from the start, exactly as it happened.

    The run's card is first assembled again from its log and checked against the one the run
    published; a difference is reported (``repro export`` refuses such a card), and the log is
    shown as it is.
    """
    settings = _session(ctx).settings()
    events = _events_of(settings, source, "replay")
    if events:
        found = _regenerated(events, "replay", strict=False)
        same = ", identical to the published card" if found.identical else ""
        typer.echo(
            f"card: {found.card['status']}, assembled again from the log{same} "
            f"(SHA-256 {found.sha256})"
        )
    if _RUN_ID.match(source):
        sock = _bind(host, port)
        _serve(settings, sock, page=f"/?run={source}&replay", allow_origin=allow_origin,
               open_browser=open_browser)  # fmt: skip
        return
    path = Path(source)
    sock = _bind(host, port)
    _serve(settings, sock, page="/?log=/replay.jsonl", allow_origin=allow_origin,
           replay_log=path.resolve(), open_browser=open_browser)  # fmt: skip


@app.command()
def serve(
    ctx: typer.Context,
    host: HostOption = "127.0.0.1",
    port: PortOption = DEFAULT_PORT,
    allow_origin: AllowOriginOption = None,
    open_browser: OpenOption = False,
) -> None:
    """Serve the cockpit, the read-only API and the event stream on this machine."""
    settings = _session(ctx).settings()
    sock = _bind(host, port)
    _serve(settings, sock, page="/", allow_origin=allow_origin, open_browser=open_browser)


def _events_of(settings: Settings, source: str, command: str) -> list[dict[str, Any]]:
    """A run's events: from the store for a run ID, else from a log file, validated."""
    if _RUN_ID.match(source):
        from repro.store import StoreError, StoreReader  # noqa: PLC0415

        try:
            with StoreReader(settings.paths.database) as reader:
                if reader.run(source) is None:
                    typer.echo(f"repro {command}: no run {source} in the store", err=True)
                    raise typer.Exit(2)
                return [json.loads(stored.body) for stored in reader.iter_events(source)]
        except StoreError as exc:
            typer.echo(f"repro {command}: the store is not available: {exc}", err=True)
            raise typer.Exit(2) from None
    path = Path(source)
    if not path.is_file():
        typer.echo(f"repro {command}: {source} is neither a run ID nor an event log file", err=True)
        raise typer.Exit(2)
    from repro_events.log import read_log, validate_log  # noqa: PLC0415
    from repro_events.schemas import load_schema_set  # noqa: PLC0415

    lines, issues = read_log(path)
    issues += validate_log(load_schema_set(), lines) if lines else []
    errors = [issue for issue in issues if issue.severity == "error"]
    for issue in errors[:20]:
        typer.echo(f"repro {command}: {path.name}: {issue}", err=True)
    if errors:
        typer.echo(f"repro {command}: {len(errors)} problems; the log is not used", err=True)
        raise typer.Exit(1)
    return [line.event for line in lines]


def _regenerated(events: list[dict[str, Any]], command: str, *, strict: bool) -> "Regenerated":
    """The card, assembled again from the log. One that differs from the card the run
    published is reported; with ``strict``, the command then exits 1."""
    from repro.card import regenerate  # noqa: PLC0415

    try:
        found = regenerate(events)
    except ValueError as exc:
        typer.echo(f"repro {command}: no card can be assembled: {exc}", err=True)
        raise typer.Exit(1) from None
    if found.published_sha256 is None:
        typer.echo(
            f"repro {command}: the log holds no card.published (the run ended before its card "
            "stage); this card is assembled from the whole log",
            err=True,
        )
    elif not found.identical:
        typer.echo(
            f"repro {command}: the card assembled from the log ({found.sha256}) differs from the "
            f"one the run published ({found.published_sha256})",
            err=True,
        )
        if strict:
            raise typer.Exit(1)
    return found


@app.command()
def export(
    ctx: typer.Context,
    source: Annotated[
        str, typer.Argument(metavar="RUN", help="A run ID or an event log (.jsonl).")
    ],
    output_format: Annotated[
        ExportFormat, typer.Option("--format", help="The card format.")
    ] = ExportFormat.md,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write to this file, not stdout.")
    ] = None,
) -> None:
    """Export a run's Reproduction Card, assembled again from the run's log.

    The card is checked against the one the run published: if they differ, nothing is written
    and the exit status is 1. Markdown (md), canonical JSON (json), an unsigned in-toto
    attestation (in-toto), SARIF 2.1.0 (sarif) or JUnit XML (junit).
    """
    settings = _session(ctx).settings()
    from repro.card import canonical, render  # noqa: PLC0415
    from repro.card.exports import attestation, junit, sarif  # noqa: PLC0415

    events = _events_of(settings, source, "export")
    found = _regenerated(events, "export", strict=True)
    evidence = {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in events
        if e["kind"] == "evidence.created"
    }
    if output_format is ExportFormat.md:
        data = render(found.card).encode("utf-8")
    elif output_format is ExportFormat.json:
        data = canonical(found.card) + b"\n"
    elif output_format is ExportFormat.in_toto:
        data = json.dumps(attestation(found.card, evidence), indent=2).encode("utf-8") + b"\n"
    elif output_format is ExportFormat.sarif:
        data = json.dumps(sarif(found.card, evidence), indent=2).encode("utf-8") + b"\n"
    else:
        data = junit(found.card)
    if output is not None:
        output.write_bytes(data)
        typer.echo(f"wrote {output} ({found.card['status']}, card SHA-256 {found.sha256})")
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


@app.command()
def report(
    ctx: typer.Context,
    source: Annotated[
        str, typer.Argument(metavar="RUN", help="A run ID or an event log (.jsonl).")
    ],
    *,
    pr_address: Annotated[
        str | None,
        typer.Option("--pr", help="The pull request to report to; by default, the run's own."),
    ] = None,
    check: Annotated[
        bool, typer.Option("--check/--no-check", help="Make or update the check run.")
    ] = True,
    comment: Annotated[
        bool, typer.Option("--comment/--no-comment", help="Make or update the comment.")
    ] = True,
) -> None:
    """Report a run's Reproduction Card to its GitHub pull request (I02).

    The card, checked against the run's log as `repro export` checks it, becomes the check run
    "Repro" on the head commit, one comment on the pull request, and, in GitHub Actions, the
    job's summary; a rerun updates them. It runs none of the target's code. A token comes from
    GITHUB_TOKEN or GH_TOKEN. Exit status 1 if a target could not be made, 2 if nothing could
    be reported.
    """
    settings = _session(ctx).settings()
    from repro.integrations.github import GitHubApi, GitHubError  # noqa: PLC0415
    from repro.integrations.github.report import report as reported  # noqa: PLC0415
    from repro.integrations.github.report import target_of  # noqa: PLC0415

    events = _events_of(settings, source, "report")
    found = _regenerated(events, "report", strict=True)
    try:
        target = target_of(found.card, pr_address, settings.github_api_url)
    except GitHubError as exc:
        typer.echo(f"repro report: {exc}", err=True)
        raise typer.Exit(2) from None
    api = GitHubApi.from_environment(settings.github_api_url)
    summary = os.environ.get("GITHUB_STEP_SUMMARY") or None
    result = reported(
        api,
        found.card,
        events,
        target,
        summary=Path(summary) if summary else None,
        check=check,
        comment_on=comment,
    )
    where = f"{target.owner}/{target.repo}#{target.number}"
    for line in result.done:
        typer.echo(f"repro report: {where}: {line}")
    for line in result.failed:
        typer.echo(f"repro report: {where}: could not update {line}", err=True)
    if result.failed:
        raise typer.Exit(1)
