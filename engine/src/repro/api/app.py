"""The engine's HTTP API: read-only REST and the event stream (ARCHITECTURE §11).

Local-only by default (THREAT_MODEL T13, T16):
- every request must name a local host (``Host``), which defeats DNS rebinding: a page whose
  domain is re-pointed at 127.0.0.1 still sends its own domain as the host;
- a WebSocket handshake that carries an ``Origin`` must come from an allow-listed origin, which
  defeats cross-site WebSocket hijacking by a page in the user's browser. OWASP: "Validate the
  ``Origin`` header on every handshake", with "an explicit allowlist of trusted origins"
  (https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html).
  Clients that are not browsers send no ``Origin``; they are other local processes (T13, whose
  per-session token arrives in H03).

Nothing here changes state. With ``ui_dir``, the built cockpit is served at ``/`` (C08); with
``replay_log``, one event log file is served at ``/replay.jsonl`` for the cockpit to replay.
"""

import re
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from repro import __version__
from repro.api.stream import BAD_REQUEST, parse_after, stream_run
from repro.bus import EventBus
from repro.store import ArtifactError, StoreError, StoreReader, safe_relative_path
from repro.store.artifacts import sha256_of

LOCAL_HOSTS: Final = ("127.0.0.1", "localhost", "::1", "[::1]")
DEFAULT_MAX_PENDING: Final = 10_000
_RUN_ID = r"^run_[0-9A-HJKMNP-TV-Z]{26}$"
_EVIDENCE_ID = r"^ev_[0-9A-HJKMNP-TV-Z]{26}$"
_SHA256 = r"^[0-9a-f]{64}$"
_FORBIDDEN_ORIGIN: Final = 1008  # policy violation; before accept, the client sees HTTP 403

RunId = Annotated[str, PathParam(pattern=_RUN_ID)]


def create_app(
    database: Path,
    *,
    runs_dir: Path | None = None,
    bus: EventBus | None = None,
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
    allowed_origins: Collection[str] = (),
    max_pending: int = DEFAULT_MAX_PENDING,
    ui_dir: Path | None = None,
    replay_log: Path | None = None,
) -> FastAPI:
    """The API over the store at ``database``; live events come from ``bus``, if given."""
    runs_dir = runs_dir if runs_dir is not None else database.parent / "runs"
    origins = frozenset(origin.rstrip("/").lower() for origin in allowed_origins)
    app = FastAPI(
        title="Repro engine",
        version=__version__,
        docs_url=None,  # no third-party assets: the API is local and read-only
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    def reader() -> StoreReader:
        try:
            return StoreReader(database)
        except StoreError as exc:
            raise HTTPException(503, f"the store is not available: {exc}") from None

    @app.get("/runs")
    def runs(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[dict[str, Any]]:
        with reader() as store:
            return [_run_json(run, store.last_seq(run.id)) for run in store.runs(limit)]

    @app.get("/runs/{run_id}")
    def run(run_id: RunId) -> dict[str, Any]:
        with reader() as store:
            found = store.run(run_id)
            if found is None:
                raise HTTPException(404, "no such run")
            return _run_json(found, store.last_seq(run_id))

    @app.get("/runs/{run_id}/evidence/{evidence_id}")
    def evidence(
        run_id: RunId, evidence_id: Annotated[str, PathParam(pattern=_EVIDENCE_ID)]
    ) -> dict[str, Any]:
        with reader() as store:
            record = store.evidence(evidence_id)
        if record is None or record.get("run_id") != run_id:
            raise HTTPException(404, "no such evidence in this run")
        return record

    @app.get("/runs/{run_id}/artifacts/{sha256}")
    def artifact(run_id: RunId, sha256: Annotated[str, PathParam(pattern=_SHA256)]) -> FileResponse:
        with reader() as store:
            row = store.artifact(run_id, sha256)
        if row is None:
            raise HTTPException(404, "no such artifact in this run")
        try:
            relative = safe_relative_path(row.path)
        except ArtifactError:
            raise HTTPException(500, "the stored artifact path is invalid") from None
        file = runs_dir / run_id / Path(*relative.parts)
        if not file.is_file() or sha256_of(file) != sha256:
            raise HTTPException(410, "the artifact's file is missing or no longer matches")
        return FileResponse(file, media_type=row.media_type, filename=relative.name)

    @app.get("/runs/{run_id}/card")
    def card(run_id: RunId) -> dict[str, Any]:
        with reader() as store:
            if store.run(run_id) is None:
                raise HTTPException(404, "no such run")
            found = store.card(run_id)
        if found is None:
            raise HTTPException(404, "this run has no card yet")
        return found

    @app.websocket("/runs/{run_id}/events")
    async def events(websocket: WebSocket, run_id: str) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin.rstrip("/").lower() not in origins:
            await websocket.close(_FORBIDDEN_ORIGIN)
            return
        after = parse_after(websocket.query_params.get("from"))
        await websocket.accept()
        if after is None or not re.match(_RUN_ID, run_id):
            await websocket.close(BAD_REQUEST, "bad request")
            return
        await stream_run(
            websocket,
            run_id,
            after,
            open_reader=lambda: StoreReader(database),
            bus=bus,
            max_pending=max_pending,
        )

    _add_cockpit(app, ui_dir, replay_log)
    return app


def _add_cockpit(app: FastAPI, ui_dir: Path | None, replay_log: Path | None) -> None:
    """The cockpit's files at ``/`` and a log to replay at ``/replay.jsonl``, when given."""
    if replay_log is not None:
        log_file = replay_log

        @app.get("/replay.jsonl")
        def replay() -> FileResponse:
            return FileResponse(log_file, media_type="application/x-ndjson")

    if ui_dir is not None:  # mounted last: the API's routes take precedence over files
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="cockpit")


def _run_json(run: Any, last_seq: int) -> dict[str, Any]:
    return {
        "id": run.id,
        "repo": run.repo,
        "base": run.base,
        "head": run.head,
        "producer": run.producer,
        "status": run.status,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "last_seq": last_seq,
    }
