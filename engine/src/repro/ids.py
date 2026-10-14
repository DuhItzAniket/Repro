"""Identifiers: ULIDs with the event schema's prefixes (``run_``, ``evt_``, ``ev_``).

A ULID is 48 bits of milliseconds since the epoch and 80 random bits, written as 26 characters
of Crockford's base 32, so IDs sort by creation time. Within one millisecond this generator
increments the random part instead of drawing a new one, so IDs made by one process are strictly
increasing even when many are made at once.
"""

import os
import threading
import time
from collections.abc import Callable

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_LENGTH = 26
_RANDOM_BITS = 80
_RANDOM_MAX = (1 << _RANDOM_BITS) - 1
_TIME_MAX = (1 << 48) - 1


def encode(value: int) -> str:
    """A 128-bit integer as 26 Crockford base-32 characters."""
    if not 0 <= value < 1 << 128:
        raise ValueError("a ULID is 128 bits")
    chars = []
    for _ in range(ULID_LENGTH):
        chars.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def decode_time_ms(ulid: str) -> int:
    """The millisecond timestamp in a ULID."""
    value = 0
    for char in ulid[:10]:
        value = value * 32 + CROCKFORD.index(char)
    return value


class UlidGenerator:
    """Monotonic ULIDs; thread-safe. ``clock_ms`` and ``random_bits`` are injectable for tests."""

    def __init__(
        self,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        random_bits: Callable[[], int] = lambda: int.from_bytes(os.urandom(10), "big"),
    ) -> None:
        self._clock_ms = clock_ms
        self._random_bits = random_bits
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_random = 0

    def new(self) -> str:
        with self._lock:
            now = self._clock_ms()
            if not 0 <= now <= _TIME_MAX:
                raise ValueError("the clock is outside the ULID range")
            if now <= self._last_ms:
                # The same millisecond, or the clock stepped back: stay after the last ID.
                now = self._last_ms
                if self._last_random == _RANDOM_MAX:
                    now += 1
                    random = self._random_bits() & _RANDOM_MAX
                else:
                    random = self._last_random + 1
            else:
                random = self._random_bits() & _RANDOM_MAX
            self._last_ms, self._last_random = now, random
            return encode((now << _RANDOM_BITS) | random)


_GENERATOR = UlidGenerator()


def new_run_id() -> str:
    return "run_" + _GENERATOR.new()


def new_event_id() -> str:
    return "evt_" + _GENERATOR.new()


def new_evidence_id() -> str:
    return "ev_" + _GENERATOR.new()
