"""Structured logs: JSON lines in UTC, credentials redacted, stdout left alone (C01)."""

import io
import json
import logging
import os
import re
from pathlib import Path

import pytest

from repro.logs import REDACTED, adopt, configure_logging, get_logger, redact


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_one_json_object_per_line_with_utc_milliseconds(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    get_logger("doctor").info("checked", extra={"fields": {"check": "git", "status": "ok"}})
    get_logger("cli").info("second")
    first, second = lines(stream)
    assert first["level"] == "info"
    assert first["logger"] == "repro.doctor"
    assert first["msg"] == "checked"
    assert (first["check"], first["status"]) == ("git", "ok")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", str(first["ts"]))
    assert second["msg"] == "second"


def test_the_level_filters(stream: io.StringIO) -> None:
    configure_logging("warning", "json", stream)
    log = get_logger("x")
    log.info("hidden")
    log.warning("shown")
    assert [entry["msg"] for entry in lines(stream)] == ["shown"]


def test_credentials_are_redacted_at_any_depth(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    get_logger("api").info(
        "request",
        extra={
            "fields": {
                "url": "http://127.0.0.1/runs",
                "Authorization": "Bearer abc",
                "headers": {"x-api-key": "k", "accept": "json"},
                "attempts": [{"token": "t"}],
            }
        },
    )
    (entry,) = lines(stream)
    assert entry["Authorization"] == REDACTED
    assert entry["headers"] == {"x-api-key": REDACTED, "accept": "json"}
    assert entry["attempts"] == [{"token": REDACTED}]
    assert entry["url"] == "http://127.0.0.1/runs"
    assert "Bearer abc" not in stream.getvalue()


def test_redact_leaves_ordinary_values() -> None:
    assert redact({"password_hint": "x"}) == {"password_hint": REDACTED}
    assert redact({"count": 3, "items": (1, 2)}) == {"count": 3, "items": [1, 2]}
    assert redact("plain") == "plain"


def test_credentials_and_the_home_directory_leave_no_trace_in_text(
    stream: io.StringIO,
) -> None:
    """H03: a credential-shaped value or the home directory in a message, a field's value or an
    error is scrubbed as events are, whatever the field is called."""
    token = "gh" + "p_" + "a1B2" * 9  # built here: a literal would trip the repository scan
    home = str(Path.home())
    for log_format in ("json", "text"):
        configure_logging("info", log_format, stream)
        try:
            raise RuntimeError(f"failed with {token} in {home}{os.sep}project")
        except RuntimeError:
            get_logger("x").exception(
                f"pushing with {token}",
                extra={"fields": {"remote": f"https://{token}@example.invalid/r.git"}},
            )
        get_logger("x").info("wrote", extra={"fields": {"path": f"{home}{os.sep}out.txt"}})
        written = stream.getvalue()
        assert token not in written
        assert home not in written
        assert home.replace("\\", "/") not in written
        assert REDACTED in written
        assert "~" in written
        stream.seek(0)
        stream.truncate()


def test_fields_cannot_overwrite_the_envelope(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    get_logger("x").info("real", extra={"fields": {"msg": "forged", "level": "error"}})
    (entry,) = lines(stream)
    assert (entry["msg"], entry["level"]) == ("real", "info")


def test_exceptions_are_structured(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("x").exception("failed")
    (entry,) = lines(stream)
    error = entry["error"]
    assert isinstance(error, dict)
    assert (error["type"], error["message"]) == ("RuntimeError", "boom")
    assert "Traceback" in error["traceback"]


def test_text_format_is_for_people(stream: io.StringIO) -> None:
    configure_logging("info", "text", stream)
    get_logger("doctor").info("checked", extra={"fields": {"check": "git", "token": "t"}})
    line = stream.getvalue().strip()
    assert line.endswith("info    repro.doctor: checked check=git token=[redacted]")


def test_configuring_twice_does_not_duplicate_lines(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    configure_logging("info", "json", stream)
    get_logger("x").info("once")
    assert len(lines(stream)) == 1
    assert logging.getLogger("repro").propagate is False


def test_non_ascii_is_escaped_so_any_console_can_take_it(stream: io.StringIO) -> None:
    configure_logging("info", "json", stream)
    get_logger("x").info("café → ok")
    assert stream.getvalue().isascii()
    assert lines(stream)[0]["msg"] == "café → ok"


def test_a_credential_in_a_query_string_is_redacted(stream: io.StringIO) -> None:
    """H06: uvicorn logs each WebSocket it accepts with its query, the session token in it."""
    configure_logging("info", "json", stream)
    adopt("uvicorn")
    try:
        accepted = '%s - "WebSocket %s" [accepted]'
        path = "/runs/run_1/events?from=0&token=k3y-Value_x"
        logging.getLogger("uvicorn.error").info(accepted, "127.0.0.1:5", path)
    finally:
        uvicorn = logging.getLogger("uvicorn")
        uvicorn.handlers, uvicorn.propagate = [], True
    (line,) = lines(stream)
    assert line["logger"] == "uvicorn.error"  # one format for every line
    redacted = f"/runs/run_1/events?from=0&token={REDACTED}"
    assert line["msg"] == f'127.0.0.1:5 - "WebSocket {redacted}" [accepted]'
    assert "k3y" not in stream.getvalue()
