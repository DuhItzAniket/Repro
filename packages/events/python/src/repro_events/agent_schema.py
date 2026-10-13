"""Derive draft-07, ``$ref``-free schemas for LLM structured output.

The Claude Agent SDK validates structured output against JSON Schema draft-07 and rejects
schemas that declare a newer draft (research/04 §1.5, ADR-0007). Repro's source schemas are
draft 2020-12 with cross-file references, so agent-facing schemas are derived from them: every
``$ref`` is inlined, and 2020-12 bookkeeping keywords are dropped. Keywords that draft-07 cannot
express are rejected rather than silently dropped, because dropping a constraint would let an
agent produce output that the source schema forbids.
"""

from typing import TYPE_CHECKING, Any

from repro_events.schemas import SchemaSet

if TYPE_CHECKING:
    # referencing does not re-export Resolver publicly; it is only needed for annotations.
    from referencing._core import Resolver

DRAFT07 = "http://json-schema.org/draft-07/schema#"

# Keywords with no draft-07 equivalent. Their presence is an error, never silently dropped.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "prefixItems",
        "$dynamicRef",
        "$dynamicAnchor",
        "$anchor",
        "$recursiveRef",
        "$recursiveAnchor",
        "$vocabulary",
        "unevaluatedProperties",
        "unevaluatedItems",
        "dependentRequired",
        "dependentSchemas",
        "minContains",
        "maxContains",
    }
)
# Bookkeeping keywords that carry no constraint once references are inlined.
DROPPED_KEYWORDS = frozenset({"$schema", "$id", "$defs", "$comment"})
MAX_DEPTH = 64


class UnsupportedSchemaError(ValueError):
    """The schema cannot be expressed faithfully as a self-contained draft-07 schema."""


def to_draft07(schema_set: SchemaSet, rel: str) -> dict[str, Any]:
    """A self-contained draft-07 equivalent of the schema document at ``rel``."""
    resolved = schema_set.registry.resolver().lookup(schema_set.uri(rel))
    body = _inline(resolved.contents, resolved.resolver, depth=0)
    if not isinstance(body, dict):
        msg = f"{rel} is not a schema object"
        raise UnsupportedSchemaError(msg)
    return {"$schema": DRAFT07, **body}


def _inline(node: Any, resolver: "Resolver[Any]", depth: int) -> Any:
    if depth > MAX_DEPTH:
        msg = "schema nesting exceeds the limit (recursive $ref?)"
        raise UnsupportedSchemaError(msg)
    if isinstance(node, list):
        return [_inline(item, resolver, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node
    unsupported = UNSUPPORTED_KEYWORDS.intersection(node)
    if unsupported:
        msg = f"draft-07 cannot express keyword(s): {', '.join(sorted(unsupported))}"
        raise UnsupportedSchemaError(msg)
    siblings = {
        key: _inline(value, resolver, depth + 1)
        for key, value in node.items()
        if key != "$ref" and key not in DROPPED_KEYWORDS
    }
    if "$ref" not in node:
        return siblings
    target = resolver.lookup(node["$ref"])
    inlined = _inline(target.contents, target.resolver, depth + 1)
    # In 2020-12, keywords next to $ref apply in addition to the referenced schema.
    return {"allOf": [inlined, siblings]} if siblings else inlined
