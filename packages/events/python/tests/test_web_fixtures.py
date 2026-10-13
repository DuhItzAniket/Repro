"""Cross-language contract: the cockpit's fixture logs (generated in TypeScript by @repro/synth)
pass the Python reference validator, so the UI is built against logs the engine side accepts."""

from pathlib import Path

import pytest

from repro_events.log import normalise_log, read_log, validate_log
from repro_events.schemas import SchemaSet, default_schema_root

FIXTURES = default_schema_root().parents[2] / "apps" / "web" / "fixtures"


@pytest.mark.parametrize("name", ["demo-run.jsonl", "stress-run.jsonl"])
def test_fixture_log_is_valid(schema_set: SchemaSet, name: str) -> None:
    path: Path = FIXTURES / name
    lines, read_issues = read_log(path)
    assert read_issues == []
    issues = validate_log(schema_set, lines)
    assert [str(issue) for issue in issues[:5]] == []  # no errors and no warnings
    # Normalisation (golden-test form) keeps it schema-valid.
    normalised = normalise_log(lines)
    assert all(not schema_set.event_errors(event) for event in normalised[:500])
