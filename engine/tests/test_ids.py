"""ULIDs with the schema's prefixes, and event timestamps (C02)."""

import re
import threading

import pytest

from repro.clock import now_timestamp, utc_timestamp
from repro.ids import (
    CROCKFORD,
    UlidGenerator,
    decode_time_ms,
    encode,
    new_event_id,
    new_evidence_id,
    new_run_id,
)

ULID = "[0-9A-HJKMNP-TV-Z]{26}"  # the schema's pattern (common.schema.json)


def test_ids_match_the_schema_patterns() -> None:
    assert re.fullmatch(f"run_{ULID}", new_run_id())
    assert re.fullmatch(f"evt_{ULID}", new_event_id())
    assert re.fullmatch(f"ev_{ULID}", new_evidence_id())


def test_encoding_is_crockford_base32_of_128_bits() -> None:
    assert encode(0) == "0" * 26
    assert encode((1 << 128) - 1) == "7" + "Z" * 25
    assert set(encode(123456789 << 80)) <= set(CROCKFORD)
    with pytest.raises(ValueError, match="128 bits"):
        encode(1 << 128)


def test_the_time_is_in_the_first_ten_characters() -> None:
    generator = UlidGenerator(clock_ms=lambda: 1_760_000_000_123, random_bits=lambda: 0)
    assert decode_time_ms(generator.new()) == 1_760_000_000_123


def test_ids_increase_within_a_millisecond_and_when_the_clock_steps_back() -> None:
    times = iter([1000, 1000, 1000, 999, 1001])
    generator = UlidGenerator(clock_ms=lambda: next(times), random_bits=lambda: 5)
    ids = [generator.new() for _ in range(5)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 5
    assert [decode_time_ms(i) for i in ids] == [1000, 1000, 1000, 1000, 1001]


def test_a_full_random_part_moves_to_the_next_millisecond() -> None:
    generator = UlidGenerator(clock_ms=lambda: 1000, random_bits=lambda: (1 << 80) - 1)
    first, second = generator.new(), generator.new()
    assert (decode_time_ms(first), decode_time_ms(second)) == (1000, 1001)
    assert first < second


def test_ids_are_unique_across_threads() -> None:
    generator = UlidGenerator()
    found: list[str] = []
    lock = threading.Lock()

    def work() -> None:
        ids = [generator.new() for _ in range(2_000)]
        assert ids == sorted(ids)
        with lock:
            found.extend(ids)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(found)) == 16_000


def test_timestamps_are_rfc3339_utc_with_milliseconds() -> None:
    assert utc_timestamp(0) == "1970-01-01T00:00:00.000Z"
    assert utc_timestamp(1_760_000_000.1239) == "2025-10-09T08:53:20.123Z"
    pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z"
    assert re.fullmatch(pattern, now_timestamp())  # the schema's Timestamp pattern
