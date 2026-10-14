from work import RECORDS, SMALL, fib, normalise_record


def test_a_warm_up():
    """Runs first: the process's first traced calls pay one-off costs (imports, first
    instrumentation) that the measured tests below should not carry."""
    assert fib(10) == 55
    assert normalise_record(RECORDS[0])["name"] == "item0"
    assert SMALL[0](1) == 1


def test_fib():
    assert fib(28) == 317811


def test_records():
    assert len([normalise_record(record) for record in RECORDS]) == len(RECORDS)


def test_small_functions():
    total = 0
    for _ in range(50_000):
        for small in SMALL:
            total += small(1)
    assert total == 50_000 * sum(k + 1 for k in range(20))
