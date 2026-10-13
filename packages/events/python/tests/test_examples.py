"""Every kind and model has valid examples that pass and invalid examples that fail."""

import json
from pathlib import Path
from typing import Any

import pytest

from repro_events.schemas import SchemaSet, default_schema_root, load_schema_set

EXAMPLES = default_schema_root().parent / "examples"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


KINDS = [info.kind for info in load_schema_set().kinds]
MODEL_FILES = sorted((EXAMPLES / "models").glob("*.json"))


def _cases(path: Path) -> dict[str, Any]:
    cases: dict[str, Any] = load_json(path)
    assert cases["valid"], f"{path.name} has no valid example"
    assert cases["invalid"], f"{path.name} has no invalid example"
    for case in cases["invalid"]:
        assert case["reason"].strip(), f"{path.name}: invalid example without a reason"
    return cases


@pytest.mark.parametrize("kind", KINDS)
def test_valid_event_examples_pass(schema_set: SchemaSet, kind: str) -> None:
    for event in _cases(EXAMPLES / "events" / f"{kind}.json")["valid"]:
        assert event["kind"] == kind
        assert schema_set.event_errors(event) == []
        assert list(schema_set.event_validator.iter_errors(event)) == []


@pytest.mark.parametrize("kind", KINDS)
def test_invalid_event_examples_fail(schema_set: SchemaSet, kind: str) -> None:
    for case in _cases(EXAMPLES / "events" / f"{kind}.json")["invalid"]:
        assert schema_set.event_errors(case["event"]), case["reason"]
        assert not schema_set.event_validator.is_valid(case["event"]), case["reason"]


def test_envelope_examples(schema_set: SchemaSet) -> None:
    cases = _cases(EXAMPLES / "envelope.json")
    for event in cases["valid"]:
        assert schema_set.event_errors(event) == []
    for case in cases["invalid"]:
        assert schema_set.event_errors(case["event"]), case["reason"]
        assert not schema_set.event_validator.is_valid(case["event"]), case["reason"]


def test_every_model_schema_has_examples(schema_set: SchemaSet) -> None:
    with_examples = {path.stem for path in MODEL_FILES}
    # artifact is exercised through evidence examples
    models = {
        rel.split("/")[1].removesuffix(".schema.json")
        for rel in schema_set.documents
        if rel.startswith("models/")
    }
    assert models - with_examples == {"artifact"}


@pytest.mark.parametrize("path", MODEL_FILES, ids=lambda p: p.stem)
def test_model_examples(schema_set: SchemaSet, path: Path) -> None:
    validator = schema_set.validator(f"models/{path.stem}.schema.json")
    cases = _cases(path)
    for value in cases["valid"]:
        assert list(validator.iter_errors(value)) == []
    for case in cases["invalid"]:
        assert not validator.is_valid(case["value"]), case["reason"]


def test_unknown_kind_is_reported_precisely(schema_set: SchemaSet) -> None:
    event = load_json(EXAMPLES / "envelope.json")["valid"][0] | {"kind": "test.exploded"}
    assert schema_set.event_errors(event) == ["$.kind: unknown event kind 'test.exploded'"]


def test_payload_errors_point_at_the_field(schema_set: SchemaSet) -> None:
    event = load_json(EXAMPLES / "events" / "test.finished.json")["valid"][0]
    event = event | {"payload": event["payload"] | {"outcome": "exploded"}}
    errors = schema_set.event_errors(event)
    assert any(error.startswith("$.payload.outcome") for error in errors), errors
