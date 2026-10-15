"""Repro's probe runner (E06): calls a change's functions with generated inputs, in the sandbox.

Usage: ``python -m repro_probe <spec.json> <out.jsonl>``, with the side's interpreter; the
sandbox puts this directory first on ``PYTHONPATH``. The spec names, for each function, its
module, its name and its inputs (``{"args": [...], "kwargs": {...}}``, JSON values the engine
generated); the import roots (relative to the working directory) go first on ``sys.path``.

Each call is one line of ``out.jsonl``, written and flushed as it ends, so a run cut short by
its timeout keeps every call before it: the outcome (``return`` or ``raise``), the result's
digests (``repro_encode``; for an exception, the exception's), its type and a preview. A
function that cannot be imported is one line with ``error``.

Before each call ``random`` is seeded from ``REPRO_SEED``, the function's and the input's
positions, so a probe's draws do not depend on the calls before it; with ``REPRO_NET_GUARD=1``
the plugin's network guard applies, as it does to the tests.

The standard library only (with this directory's modules), Python 3.12 to 3.15.
"""

import importlib
import json
import os
import random
import sys
from typing import Any

from repro_encode import digest, digests, preview, type_name

PREVIEW = 512


def _record(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
    handle.flush()


def main(argv: list[str]) -> int:
    spec_path, out_path = argv[1], argv[2]
    with open(spec_path, encoding="utf-8") as handle:  # noqa: PTH123 - the standard library only
        spec = json.load(handle)
    seed = os.environ.get("REPRO_SEED", "0")
    if os.environ.get("REPRO_NET_GUARD") == "1":
        from repro_pytest import _guard_network  # noqa: PLC0415 - only when asked

        _guard_network()
    here = os.getcwd()  # noqa: PTH109
    for root in reversed(spec.get("roots", [])):
        sys.path.insert(0, os.path.join(here, root))  # noqa: PTH118
    with open(out_path, "w", encoding="utf-8") as out:  # noqa: PTH123
        for number, probe in enumerate(spec["probes"]):
            try:
                module = importlib.import_module(probe["module"])
                function = getattr(module, probe["function"])
            except BaseException as exc:  # noqa: BLE001 - what the import raised is the result
                _record(out, {"probe": number, "error": f"{type_name(type(exc))}: {exc}"[:500]})
                continue
            for index, given in enumerate(probe["inputs"]):
                random.seed(f"{seed}:{number}:{index}")
                record: dict[str, Any] = {"probe": number, "input": index}
                try:
                    value = function(*given["args"], **given["kwargs"])
                except BaseException as exc:  # noqa: BLE001 - SystemExit too: it is behaviour
                    result, complete = digest(exc)
                    record.update(outcome="raise", result=result, complete=complete)
                    record.update(type=type_name(type(exc)), preview=preview(exc, PREVIEW))
                else:
                    result, any_order, complete = digests(value)
                    record.update(outcome="return", result=result, complete=complete)
                    record.update(type=type_name(type(value)), preview=preview(value, PREVIEW))
                    if any_order != result:
                        record["any_order"] = any_order
                _record(out, record)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
