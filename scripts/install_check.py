"""A clean install and a first run, timed (H05): the documented procedure, followed exactly.

From the two wheels of a release (``scripts/build_wheels.py``), into a tool directory of its
own, away from any checkout: ``uv tool install`` as the README says, then ``repro --version``,
``repro doctor``, a first ``repro run`` on a small repository made here, and an export of its
card checked against the schemas the wheel carries. The run must really have run the tests: the
change is a refactor its test covers, so its card must be VERIFIED, with a selected test, and
with nothing missing but the timing of a test too fast to time (H06: an installed Repro once
completed runs in which no test could start). The cockpit and the schemas must come from
the installed wheels, not from a checkout. The whole procedure must take under ten minutes
(H05's target), and the time each step took is printed.

    uv run python scripts/install_check.py dist/wheels [--limit-s 600]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PYTHON = "3.13"  # the Python Repro is developed and tested on; uv fetches it if needed
TARGET_FILES = {
    "pyproject.toml": '[project]\nname = "calc"\nversion = "0.1.0"\n',
    "calc/__init__.py": "",
    "calc/core.py": "def total(items):\n    return sum(items)\n",
    "tests/test_core.py": (
        "from calc.core import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
    ),
}
HEAD_FILES = {"calc/core.py": "def total(items):\n    return sum(item for item in items)\n"}
#: What the first run may leave unchecked: its one test runs in well under 5 ms.
MAY_BE_MISSING = {"perf_not_assessable"}
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Install Check",
    "GIT_AUTHOR_EMAIL": "install-check@repro.invalid",
    "GIT_COMMITTER_NAME": "Install Check",
    "GIT_COMMITTER_EMAIL": "install-check@repro.invalid",
}


class CheckError(Exception):
    pass


def run(argv: Sequence[str], *, env: dict[str, str], cwd: Path) -> str:
    """``argv``'s output; its failure stops the check with what it said."""
    done = subprocess.run(  # noqa: S603 - the check's own commands
        list(argv), env=env, cwd=cwd, capture_output=True, text=True, check=False, timeout=900
    )
    if done.returncode != 0:
        raise CheckError(
            f"{' '.join(argv[:3])} exited {done.returncode}:\n{done.stdout}\n{done.stderr}"
        )
    return done.stdout + done.stderr


def make_target(root: Path, env: dict[str, str]) -> tuple[str, str]:
    """A small repository with a base and a head commit: what a first run is made on."""
    git = ["git", "-c", "core.longpaths=true", "-c", "init.defaultBranch=main"]
    root.mkdir()
    run([*git, "init", "-q"], env=env, cwd=root)
    shas = []
    for files in (TARGET_FILES, HEAD_FILES):
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        run([*git, "add", "-A"], env=env, cwd=root)
        run([*git, "commit", "-q", "-m", "change"], env=env, cwd=root)
        shas.append(run([*git, "rev-parse", "HEAD"], env=env, cwd=root).strip())
    return shas[0], shas[1]


def checked_card(card: dict[str, Any]) -> str:
    """The first run's isolation level, once its card shows that the tests really ran."""
    missing = [f"{m['reason']}: {m['detail']}" for m in card["missing"]
               if m["reason"] not in MAY_BE_MISSING]  # fmt: skip
    selected = card["conditions"]["selected_tests"]
    if card["status"] != "VERIFIED" or selected < 1 or missing:
        raise CheckError(
            f"the first run's card is {card['status']}, {selected} tests selected, "
            f"missing: {missing or 'nothing else'}"
        )
    return str(card["conditions"]["isolation_level"])


def check(wheels: Path, limit_s: float) -> list[tuple[str, float]]:
    engine = next(wheels.glob("repro_engine-*.whl"), None)
    events = next(wheels.glob("repro_events-*.whl"), None)
    if engine is None or events is None:
        raise CheckError(f"{wheels} needs both repro_engine and repro_events wheels")
    version = engine.name.split("-")[1]
    steps: list[tuple[str, float]] = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="repro-install-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp).resolve()  # as the installed code will see its own paths
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("REPRO_", "UV_", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"))
        }
        env |= {
            "UV_TOOL_DIR": str(work / "tools"),
            "UV_TOOL_BIN_DIR": str(work / "bin"),
            "REPRO_DATA_DIR": str(work / "data"),
            **GIT_IDENTITY,
        }

        def step(name: str, since: float) -> float:
            now = time.monotonic()
            steps.append((name, now - since))
            return now

        mark = time.monotonic()
        run(  # the README's command, the wheels' URLs in PEP 508's direct-reference form
            ["uv", "tool", "install", "--python", PYTHON,
             "--from", f"repro-engine @ {engine.as_uri()}",
             "--with", f"repro-events @ {events.as_uri()}", "repro-engine"],
            env=env, cwd=work,
        )  # fmt: skip
        mark = step("uv tool install", mark)
        repro = next((work / "bin").glob("repro*"), None)
        if repro is None:
            raise CheckError("uv tool install left no repro command")
        venv = work / "tools" / "repro-engine"  # the tool's own environment
        tool_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        shown = run([str(repro), "--version"], env=env, cwd=work).strip()
        if shown != f"repro {version}":
            raise CheckError(f"repro --version says {shown!r}, the wheel is {version}")
        report = json.loads(run([str(repro), "doctor", "--json"], env=env, cwd=work))
        cockpit = next(c for c in report["checks"] if c["name"] == "cockpit")
        if cockpit["status"] != "ok" or str(work / "tools") not in cockpit["summary"]:
            raise CheckError(f"the cockpit is not the installed wheel's: {cockpit}")
        mark = step("repro --version, repro doctor", mark)
        base, head = make_target(work / "target", env)
        argv = ["run", "--repo", str(work / "target"), "--base", base, "--head", head, "--no-serve"]
        said = run([str(repro), *argv], env=env, cwd=work)
        found = re.search(r"(run_[0-9A-HJKMNP-TV-Z]{26}) completed", said)
        if found is None:
            raise CheckError(f"repro run reported no completed run:\n{said}")
        exported = ["export", found.group(1), "--format", "json"]
        level = checked_card(json.loads(run([str(repro), *exported], env=env, cwd=work)))
        mark = step(f"the first repro run ({level})", mark)
        statement = work / "card.in-toto.json"
        run([str(repro), "export", found.group(1), "--format", "in-toto", "-o", str(statement)],
            env=env, cwd=work)  # fmt: skip
        probe = (
            "import json, sys; from repro_events.schemas import load_schema_set; "
            "s = load_schema_set(); root = str(s.root); "
            "assert sys.argv[2] in root, root; "
            "s.validator('attestation/in-toto-statement-v1.schema.json')"
            ".validate(json.load(open(sys.argv[1], encoding='utf-8'))); print(root)"
        )
        run([str(tool_python), "-I", "-c", probe, str(statement), str(work / "tools")],
            env=env, cwd=work)  # fmt: skip
        step("repro export, checked against the packaged schemas", mark)
    total = time.monotonic() - started
    steps.append(("total", total))
    if total > limit_s:
        raise CheckError(f"the procedure took {total:.0f} s, over {limit_s:.0f} s")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheels", type=Path, help="the directory holding the two wheels")
    parser.add_argument("--limit-s", type=float, default=600.0, help="H05's ten minutes")
    args = parser.parse_args()
    try:
        steps = check(args.wheels.resolve(), args.limit_s)
    except CheckError as failed:
        sys.stderr.write(f"install check failed: {failed}\n")
        return 1
    for name, seconds in steps:
        sys.stdout.write(f"{seconds:7.1f} s  {name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
