"""Structured logs for the engine's internals (ARCHITECTURE §14).

Logs go to stderr, so stdout stays free for a command's own output (``repro doctor --json``).
The default format is one JSON object per line::

    {
        "ts": "2026-10-14T09:12:03.512Z",
        "level": "info",
        "logger": "repro.doctor",
        "msg": "checked",
        "check": "git",
        "status": "ok",
    }

``ts`` is UTC with milliseconds. Extra fields come from ``extra={"fields": {...}}``. A field whose
name looks like a credential (token, secret, password, authorization, API key) is replaced by
``"[redacted]"``, at any depth, so a careless call cannot leak one. Every other string, the
message and an error's text included, goes through the events' scrubbing (``repro.scrub``,
H03): credentials of a recognised shape are redacted and the home directory is written ``~``.
So is a credential in a URL's query string (``?token=…``, H06): the web server logs the path of
each WebSocket it accepts, query included. The web server's own logger goes through the same
handler (``adopt``), so its lines have the same format and the same scrubbing.
What a user should see about a run is not a log line: it is a ``log.line`` event in the run's
event log.
"""

import json
import logging
import re
import sys
from collections.abc import Mapping
from typing import IO, Any, Final

from repro.clock import utc_timestamp
from repro.config import LogFormat, LogLevel
from repro.scrub import scrub_text

LOGGER_NAME: Final = "repro"
REDACTED: Final = "[redacted]"
_SECRET = re.compile(r"token|secret|passw(or)?d|authori[sz]ation|api[_-]?key|credential", re.I)
#: A query parameter whose name looks like a credential, and its value.
_QUERY_SECRET = re.compile(
    r"([?&][\w.-]*(?:token|secret|passw(?:or)?d|api[_-]?key|credential)[\w.-]*=)[^&\s\"'#]+",
    re.I,
)
_LEVELS: Final[dict[LogLevel, int]] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def redact(value: object) -> object:
    """``value`` with every credential-like field replaced, in mappings and lists at any depth."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _SECRET.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def clean(text: str) -> str:
    """``text`` as a log may show it: query-string credentials and recognised ones redacted, the
    home directory written ``~``."""
    return scrub_text(_QUERY_SECRET.sub(rf"\1{REDACTED}", text))


def _fields(record: logging.LogRecord) -> dict[str, object]:
    fields = getattr(record, "fields", None)
    if not isinstance(fields, Mapping):
        return {}
    cleaned = redact(fields)
    return dict(cleaned) if isinstance(cleaned, Mapping) else {}


class JsonFormatter(logging.Formatter):
    """One JSON object per record, on one line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": utc_timestamp(record.created),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": clean(record.getMessage()),
        }
        for key, value in _fields(record).items():
            if key not in entry:
                entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            error = record.exc_info[1]
            entry["error"] = {
                "type": record.exc_info[0].__name__,
                "message": clean(str(error)),
                "traceback": clean(self.formatException(record.exc_info)),
            }
        return json.dumps(entry, ensure_ascii=True, default=str, separators=(",", ":"))


class TextFormatter(logging.Formatter):
    """For people: time, level, logger, message and ``key=value`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        fields = " ".join(f"{key}={value}" for key, value in _fields(record).items())
        line = f"{utc_timestamp(record.created)} {record.levelname.lower():<7} {record.name}: "
        line += clean(record.getMessage()) + (f" {fields}" if fields else "")
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + clean(self.formatException(record.exc_info))
        return line


def configure_logging(
    level: LogLevel = "info", log_format: LogFormat = "json", stream: IO[str] | None = None
) -> logging.Logger:
    """Points the ``repro`` logger at ``stream`` (stderr) in the chosen format. Idempotent."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    handler.setFormatter(JsonFormatter() if log_format == "json" else TextFormatter())
    logger.addHandler(handler)
    logger.setLevel(_LEVELS[level])
    logger.propagate = False
    return logger


def adopt(name: str) -> None:
    """Sends a library's logger (``uvicorn``) to the ``repro`` logger's handler, at its level:
    one format, and the same scrubbing, for every line Repro prints."""
    ours = logging.getLogger(LOGGER_NAME)
    theirs = logging.getLogger(name)
    theirs.handlers = list(ours.handlers)
    theirs.setLevel(ours.level)
    theirs.propagate = False


def get_logger(name: str) -> logging.Logger:
    """A logger under ``repro`` (``get_logger("doctor")`` → ``repro.doctor``)."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
