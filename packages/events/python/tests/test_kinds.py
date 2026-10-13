"""The kind registry in event.schema.json is complete and consistent with docs and examples."""

import json
import re
from pathlib import Path

from repro_events.schemas import ALL_STAGES, SchemaSet, default_schema_root

EXAMPLES = default_schema_root().parent / "examples"
REPO_ROOT = default_schema_root().parents[2]


def test_kind_names_are_unique(schema_set: SchemaSet) -> None:
    names = [info.kind for info in schema_set.kinds]
    assert len(names) == len(set(names))


def test_every_payload_schema_belongs_to_exactly_one_kind(schema_set: SchemaSet) -> None:
    referenced = sorted(info.payload_schema for info in schema_set.kinds)
    on_disk = sorted(rel for rel in schema_set.documents if rel.startswith("payloads/"))
    assert referenced == on_disk
    for info in schema_set.kinds:
        assert info.payload_schema == f"payloads/{info.kind}.schema.json"


def test_stage_constraints_name_real_stages(schema_set: SchemaSet) -> None:
    for info in schema_set.kinds:
        assert info.stages
        assert set(info.stages) <= set(ALL_STAGES)
        assert info.payload_version >= 1


def test_every_kind_has_an_examples_file_and_no_orphans(schema_set: SchemaSet) -> None:
    expected = {f"{info.kind}.json" for info in schema_set.kinds}
    on_disk = {path.name for path in (EXAMPLES / "events").glob("*.json")}
    assert on_disk == expected


def test_registry_matches_the_kinds_documented_in_architecture(schema_set: SchemaSet) -> None:
    text = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    section = text.split("### 5.2 Kinds (v1)", 1)[1].split("### 5.3", 1)[0]
    table_rows = [line for line in section.splitlines() if line.startswith("|")]
    documented = {
        name for row in table_rows for name in re.findall(r"`([a-z]+(?:\.[a-z_]+)+)`", row)
    }
    assert documented == {info.kind for info in schema_set.kinds}


def test_kind_alone_selects_the_branch(schema_set: SchemaSet) -> None:
    # event_errors relies on this to skip re-checking all 34 oneOf branches per event.
    assert schema_set.kind_discriminates


def test_discrimination_is_detected_structurally(tmp_path: Path) -> None:
    root = default_schema_root()
    for path in root.rglob("*.schema.json"):
        target = tmp_path / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    event_path = tmp_path / "event.schema.json"
    schema = json.loads(event_path.read_text(encoding="utf-8"))
    del schema["oneOf"][1]["properties"]["kind"]
    event_path.write_text(json.dumps(schema), encoding="utf-8")
    assert not SchemaSet(tmp_path).kind_discriminates
