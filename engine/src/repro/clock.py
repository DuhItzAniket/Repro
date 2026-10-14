"""Timestamps as the event schema writes them: RFC 3339, UTC, milliseconds, a ``Z`` suffix."""

import time
from datetime import UTC, datetime


def utc_timestamp(seconds: float) -> str:
    """``seconds`` since the epoch as ``2026-10-14T09:12:03.512Z``."""
    moment = datetime.fromtimestamp(seconds, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def now_timestamp() -> str:
    """The current time as an event timestamp."""
    return utc_timestamp(time.time())
