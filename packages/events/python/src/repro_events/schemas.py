"""Load the Repro JSON Schemas (draft 2020-12) and build validators.

Schema files reference each other with relative paths and carry no ``$id``. Each file is
registered under its ``file://`` URI, so relative references resolve exactly as they do on disk.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

ALL_STAGES: tuple[str, ...] = ("read", "build", "run", "diff", "check", "review", "card")
EVENT_SCHEMA = "event.schema.json"
ENVELOPE_SCHEMA = "envelope.schema.json"


def default_schema_root() -> Path:
    """The schema directory of this source tree (``packages/events/schema``)."""
    return Path(__file__).resolve().parents[3] / "schema"


@dataclass(frozen=True)
class KindInfo:
    """One event kind, as registered in ``event.schema.json``."""

    kind: str
    description: str
    stages: tuple[str, ...]
    payload_version: int
    payload_schema: str  # path relative to the schema root, POSIX separators
    branch_index: int  # index into event.schema.json's oneOf


class SchemaSet:
    """All schema documents under one root, with a shared reference registry."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.documents: dict[str, Any] = {
            path.relative_to(self.root).as_posix(): json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.rglob("*.schema.json"))
        }
        if EVENT_SCHEMA not in self.documents or ENVELOPE_SCHEMA not in self.documents:
            msg = f"{self.root} does not contain {EVENT_SCHEMA} and {ENVELOPE_SCHEMA}"
            raise FileNotFoundError(msg)
        self.registry: Registry[Any] = Registry().with_resources(
            (self.uri(rel), DRAFT202012.create_resource(doc)) for rel, doc in self.documents.items()
        )

    def uri(self, rel: str) -> str:
        """The ``file://`` URI under which a schema document is registered."""
        return (self.root / rel).as_uri()

    def validator(self, rel: str) -> Draft202012Validator:
        """A validator for the schema document at ``rel`` (relative to the root)."""
        return self._validator({"$ref": self.uri(rel)})

    def _validator(self, schema: Mapping[str, Any]) -> Draft202012Validator:
        return Draft202012Validator(
            schema,
            registry=self.registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )

    @cached_property
    def kinds(self) -> tuple[KindInfo, ...]:
        """Event kinds in registry order."""
        infos = []
        for index, branch in enumerate(self.documents[EVENT_SCHEMA]["oneOf"]):
            props = branch["properties"]
            stage = props.get("stage", {})
            if "const" in stage:
                stages: tuple[str, ...] = (stage["const"],)
            elif "enum" in stage:
                stages = tuple(stage["enum"])
            else:
                stages = ALL_STAGES
            infos.append(
                KindInfo(
                    kind=props["kind"]["const"],
                    description=branch["description"],
                    stages=stages,
                    payload_version=props["pv"]["const"],
                    payload_schema=props["payload"]["$ref"],
                    branch_index=index,
                )
            )
        return tuple(infos)

    @cached_property
    def kinds_by_name(self) -> dict[str, KindInfo]:
        return {info.kind: info for info in self.kinds}

    @cached_property
    def event_validator(self) -> Draft202012Validator:
        """Validates a complete event (envelope plus the payload of exactly one kind)."""
        return self.validator(EVENT_SCHEMA)

    def event_errors(self, event: Any) -> list[str]:
        """Human-readable validation errors for one event; empty when valid.

        Envelope errors are reported first. If the envelope is valid and the kind is known,
        the event is checked against that kind's branch so that messages point at the exact
        payload field instead of a generic "not valid under any of the given schemas".
        """
        envelope_errors = _messages(self.validator(ENVELOPE_SCHEMA).iter_errors(event))
        if envelope_errors:
            return envelope_errors
        info = self.kinds_by_name.get(event["kind"])
        if info is None:
            return [f"$.kind: unknown event kind {event['kind']!r}"]
        branch = self._validator(
            {
                "allOf": [
                    {"$ref": self.uri(ENVELOPE_SCHEMA)},
                    {"$ref": f"{self.uri(EVENT_SCHEMA)}#/oneOf/{info.branch_index}"},
                ]
            }
        )
        branch_errors = _messages(branch.iter_errors(event))
        if branch_errors:
            return branch_errors
        # The full schema must agree; a disagreement means the registry itself is inconsistent.
        return _messages(self.event_validator.iter_errors(event))


def load_schema_set(root: Path | None = None) -> SchemaSet:
    """Load the schema set from ``root`` (default: this source tree's schema directory)."""
    return SchemaSet(root if root is not None else default_schema_root())


def _messages(errors: Any) -> list[str]:
    found: list[ValidationError] = sorted(errors, key=lambda e: (e.json_path, e.message))
    return [f"{error.json_path}: {error.message}" for error in found]
