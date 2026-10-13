"""Fixture repository specs. Expected outcomes live next to them as ``<name>.toml``.

Only ``honest-fix`` exists so far (A07 scaffold). The other fixtures in TEST_STRATEGY §3 are
added by the phases that need them.
"""

from fixtures.repo_builder import RepoSpec

_DATES_BUGGY = '''"""Date helpers."""

from datetime import datetime


def parse_date(text: str) -> datetime:
    """Parse an ISO-8601 timestamp."""
    return datetime.fromisoformat(text).replace(tzinfo=None)
'''

_DATES_FIXED = '''"""Date helpers."""

from datetime import UTC, datetime


def parse_date(text: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalise it to UTC (naive input is taken as UTC)."""
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
'''

_DATES_TESTS = """from datetime import UTC

from pkg.dates import parse_date


def test_parse_date_with_timezone():
    value = parse_date("2026-03-29T02:30:00+01:00")
    assert value.tzinfo is not None
    assert (value.hour, value.minute) == (1, 30)


def test_parse_date_naive_input_is_utc():
    assert parse_date("2026-01-01T00:00:00").tzinfo == UTC
"""

HONEST_FIX = RepoSpec(
    name="honest-fix",
    description="Bug fix that does exactly what its description claims.",
    base={
        "pyproject.toml": '[project]\nname = "dates-fixture"\nversion = "0.1.0"\n',
        "pkg/__init__.py": "",
        "pkg/dates.py": _DATES_BUGGY,
        "tests/test_dates.py": _DATES_TESTS,
    },
    heads={"fix/parse-date-utc": {"pkg/dates.py": _DATES_FIXED}},
    pr_description={
        "fix/parse-date-utc": (
            "Fix parse_date dropping the UTC offset\n\n"
            "parse_date now returns timezone-aware datetimes normalised to UTC; naive input is "
            "interpreted as UTC. No other behaviour changes."
        )
    },
)

ALL_SPECS = {spec.name: spec for spec in (HONEST_FIX,)}
