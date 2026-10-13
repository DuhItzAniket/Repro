"""Hygiene rules for every schema document."""

from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from repro_events.agent_schema import UNSUPPORTED_KEYWORDS
from repro_events.schemas import SchemaSet, load_schema_set

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
DOCUMENTS = sorted(load_schema_set().documents)


def walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


@pytest.mark.parametrize("rel", DOCUMENTS)
def test_document_is_a_valid_2020_12_schema(schema_set: SchemaSet, rel: str) -> None:
    doc = schema_set.documents[rel]
    assert doc.get("$schema") == DRAFT_2020_12
    Draft202012Validator.check_schema(doc)


@pytest.mark.parametrize("rel", DOCUMENTS)
def test_document_has_no_id_so_relative_refs_resolve_from_disk(
    schema_set: SchemaSet, rel: str
) -> None:
    assert "$id" not in schema_set.documents[rel]


@pytest.mark.parametrize("rel", DOCUMENTS)
def test_document_avoids_keywords_that_codegen_and_draft07_cannot_express(
    schema_set: SchemaSet, rel: str
) -> None:
    used = {key for node in walk(schema_set.documents[rel]) for key in node}
    assert not used & UNSUPPORTED_KEYWORDS


@pytest.mark.parametrize("rel", DOCUMENTS)
def test_every_ref_resolves(schema_set: SchemaSet, rel: str) -> None:
    resolver = schema_set.registry.resolver(base_uri=schema_set.uri(rel))
    for node in walk(schema_set.documents[rel]):
        ref = node.get("$ref")
        if isinstance(ref, str):
            resolver.lookup(ref)  # raises if unresolvable


@pytest.mark.parametrize("rel", [r for r in DOCUMENTS if r.startswith(("payloads/", "models/"))])
def test_payloads_and_models_are_closed_objects_with_a_title(
    schema_set: SchemaSet, rel: str
) -> None:
    doc = schema_set.documents[rel]
    assert doc["type"] == "object"
    assert doc["additionalProperties"] is False
    assert doc["title"]
    assert set(doc["required"]) <= set(doc["properties"])
