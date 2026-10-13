"""Generator guards: unsupported constructs and name collisions fail loudly."""

import json
import shutil
from pathlib import Path

import pytest

from repro_events.codegen import Builder, CodegenError
from repro_events.schemas import SchemaSet, default_schema_root


def copy_schemas(tmp_path: Path) -> Path:
    root = tmp_path / "schema"
    shutil.copytree(default_schema_root(), root)
    return root


def test_two_sources_generating_the_same_type_name_is_an_error(tmp_path: Path) -> None:
    # Regression: common $defs "Verdict" (an enum) and models/verdict (title "Verdict") once
    # collided, and the model silently resolved to the enum.
    root = copy_schemas(tmp_path)
    common = json.loads((root / "common.schema.json").read_text(encoding="utf-8"))
    common["$defs"]["Verdict"] = common["$defs"].pop("VerdictValue")
    (root / "common.schema.json").write_text(json.dumps(common), encoding="utf-8")
    model = (root / "models" / "verdict.schema.json").read_text(encoding="utf-8")
    (root / "models" / "verdict.schema.json").write_text(
        model.replace("$defs/VerdictValue", "$defs/Verdict"), encoding="utf-8"
    )
    with pytest.raises(CodegenError, match="'Verdict' is generated from both"):
        Builder(SchemaSet(root)).build()


def test_unsupported_keyword_is_an_error_not_an_any(tmp_path: Path) -> None:
    root = copy_schemas(tmp_path)
    path = root / "payloads" / "log.line.schema.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["properties"]["message"]["multipleOf"] = 2
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CodegenError, match="multipleOf"):
        Builder(SchemaSet(root)).build()
