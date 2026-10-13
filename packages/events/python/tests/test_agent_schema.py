"""Derived draft-07 schemas are self-contained and accept exactly what the source accepts."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator

from repro_events.agent_schema import DRAFT07, UnsupportedSchemaError, to_draft07
from repro_events.schemas import SchemaSet, default_schema_root, load_schema_set

EXAMPLES = default_schema_root().parent / "examples"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


SOURCES = sorted(
    rel for rel in load_schema_set().documents if rel.startswith(("models/", "payloads/"))
)
D2020 = "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("rel", SOURCES)
def test_derived_schema_is_self_contained_draft07(schema_set: SchemaSet, rel: str) -> None:
    derived = to_draft07(schema_set, rel)
    assert derived["$schema"] == DRAFT07
    assert '"$ref"' not in json.dumps(derived)
    assert '"$defs"' not in json.dumps(derived)
    Draft7Validator.check_schema(derived)


@pytest.mark.parametrize("path", sorted((EXAMPLES / "models").glob("*.json")), ids=lambda p: p.stem)
def test_derived_model_schema_agrees_with_source_on_examples(
    schema_set: SchemaSet, path: Path
) -> None:
    derived = Draft7Validator(to_draft07(schema_set, f"models/{path.stem}.schema.json"))
    cases = load_json(path)
    for value in cases["valid"]:
        assert list(derived.iter_errors(value)) == []
    for case in cases["invalid"]:
        assert not derived.is_valid(case["value"]), case["reason"]


@pytest.mark.parametrize("kind", [info.kind for info in load_schema_set().kinds])
def test_derived_payload_schema_accepts_valid_payloads(schema_set: SchemaSet, kind: str) -> None:
    derived = Draft7Validator(to_draft07(schema_set, f"payloads/{kind}.schema.json"))
    for event in load_json(EXAMPLES / "events" / f"{kind}.json")["valid"]:
        assert list(derived.iter_errors(event["payload"])) == []


def _tiny_schema_set(tmp_path: Path, payload: dict[str, object]) -> SchemaSet:
    (tmp_path / "envelope.schema.json").write_text(json.dumps({"$schema": D2020}), encoding="utf-8")
    (tmp_path / "event.schema.json").write_text(
        json.dumps({"$schema": D2020, "oneOf": []}), encoding="utf-8"
    )
    (tmp_path / "x.schema.json").write_text(
        json.dumps({"$schema": D2020, **payload}), encoding="utf-8"
    )
    return SchemaSet(tmp_path)


def test_keywords_draft07_cannot_express_are_rejected(tmp_path: Path) -> None:
    schemas = _tiny_schema_set(tmp_path, {"type": "array", "prefixItems": [{"type": "integer"}]})
    with pytest.raises(UnsupportedSchemaError, match="prefixItems"):
        to_draft07(schemas, "x.schema.json")


def test_recursive_reference_is_rejected(tmp_path: Path) -> None:
    schemas = _tiny_schema_set(
        tmp_path, {"type": "object", "properties": {"child": {"$ref": "x.schema.json"}}}
    )
    with pytest.raises(UnsupportedSchemaError, match="recursive"):
        to_draft07(schemas, "x.schema.json")


def test_keywords_next_to_ref_are_kept(tmp_path: Path) -> None:
    schemas = _tiny_schema_set(
        tmp_path,
        {"$defs": {"n": {"type": "integer"}}, "$ref": "#/$defs/n", "minimum": 3},
    )
    derived = Draft7Validator(to_draft07(schemas, "x.schema.json"))
    assert derived.is_valid(5)
    assert not derived.is_valid(2)
    assert not derived.is_valid("5")
