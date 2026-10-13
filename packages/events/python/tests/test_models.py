"""Generated Pydantic models accept and reject exactly what the JSON Schema does, and round-trip."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from repro_events import models
from repro_events.codegen import render_all
from repro_events.schemas import SchemaSet, default_schema_root, load_schema_set

EXAMPLES = default_schema_root().parent / "examples"
KINDS = [info.kind for info in load_schema_set().kinds]
MODEL_CLASSES: dict[str, type[BaseModel]] = {
    "claim": models.Claim,
    "evidence": models.Evidence,
    "verdict": models.Verdict,
    "missing": models.MissingItem,
    "card": models.ReproductionCard,
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def roundtrip(adapter: TypeAdapter[Any], value: Any) -> Any:
    parsed = adapter.validate_python(value)
    return adapter.dump_python(parsed, mode="json", exclude_unset=True, by_alias=True)


@pytest.mark.parametrize("kind", KINDS)
def test_valid_events_parse_to_their_kind_and_round_trip_exactly(kind: str) -> None:
    for event in load_json(EXAMPLES / "events" / f"{kind}.json")["valid"]:
        parsed = models.EVENT_ADAPTER.validate_python(event)
        assert parsed.kind == kind
        assert type(parsed).__name__ == kind.title().replace(".", "").replace("_", "") + "Event"
        assert roundtrip(models.EVENT_ADAPTER, event) == event


@pytest.mark.parametrize("kind", KINDS)
def test_invalid_events_are_rejected_like_the_json_schema_rejects_them(kind: str) -> None:
    for case in load_json(EXAMPLES / "events" / f"{kind}.json")["invalid"]:
        with pytest.raises(ValidationError):
            models.EVENT_ADAPTER.validate_python(case["event"])


def test_envelope_examples() -> None:
    cases = load_json(EXAMPLES / "envelope.json")
    for event in cases["valid"]:
        assert roundtrip(models.EVENT_ADAPTER, event) == event
    for case in cases["invalid"]:
        with pytest.raises(ValidationError):
            models.EVENT_ADAPTER.validate_python(case["event"])


@pytest.mark.parametrize("name", sorted(MODEL_CLASSES))
def test_model_examples_round_trip_and_invalid_are_rejected(name: str) -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(MODEL_CLASSES[name])
    cases = load_json(EXAMPLES / "models" / f"{name}.json")
    for value in cases["valid"]:
        assert roundtrip(adapter, value) == value
    for case in cases["invalid"]:
        with pytest.raises(ValidationError):
            adapter.validate_python(case["value"])


def test_generic_envelope_accepts_any_well_formed_kind() -> None:
    event = load_json(EXAMPLES / "envelope.json")["valid"][0] | {"kind": "future.kind", "pv": 3}
    parsed = models.Envelope.model_validate(event)
    assert parsed.kind == "future.kind"


def test_keyword_field_names_round_trip_through_their_alias() -> None:
    event = load_json(EXAMPLES / "events" / "diff.outcome.json")["valid"][0]
    parsed = models.EVENT_ADAPTER.validate_python(event)
    assert isinstance(parsed, models.DiffOutcomeEvent)
    assert parsed.payload.class_ == "F2P"
    assert roundtrip(models.EVENT_ADAPTER, event)["payload"]["class"] == "F2P"


def test_optional_fields_reject_explicit_null_when_the_schema_does() -> None:
    with pytest.raises(ValidationError, match="must not be null"):
        models.Target.model_validate({"file": None, "symbol": "pkg.dates:parse_date#0"})
    with pytest.raises(ValidationError):
        models.Target.model_validate({})


def test_generated_files_are_up_to_date(schema_set: SchemaSet) -> None:
    package_root = schema_set.root.parent
    for rel, content in render_all(schema_set).items():
        assert (package_root / rel).read_text(encoding="utf-8") == content, (
            f"{rel.as_posix()} is stale; run: uv run repro-events-codegen"
        )
