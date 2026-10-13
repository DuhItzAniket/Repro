"""``repro-events``: validate and normalise event logs.

repro-events validate LOG [LOG ...]    exit 1 if any log has errors (warnings are printed)
repro-events normalise LOG [-o OUT]    canonical, id/time-normalised JSONL (for golden tests)
"""

import argparse
import sys
from pathlib import Path

from repro_events.log import dumps_jsonl, normalise_log, read_log, validate_log
from repro_events.schemas import load_schema_set


def _validate(paths: list[Path]) -> int:
    schemas = load_schema_set()
    failed = False
    for path in paths:
        lines, issues = read_log(path)
        issues += validate_log(schemas, lines)
        for issue in issues:
            sys.stdout.write(f"{path}: {issue}\n")
        errors = sum(1 for issue in issues if issue.severity == "error")
        failed |= errors > 0
        status = "FAIL" if errors else "ok"
        sys.stdout.write(f"{path}: {status} ({len(lines)} events, {errors} errors)\n")
    return 1 if failed else 0


def _normalise(path: Path, out: Path | None) -> int:
    lines, issues = read_log(path)
    if issues:
        for issue in issues:
            sys.stderr.write(f"{path}: {issue}\n")
        return 1
    text = dumps_jsonl(normalise_log(lines))
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8", newline="\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repro-events", description="Repro event-log tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate event logs (schema + log invariants)")
    validate.add_argument("logs", nargs="+", type=Path)
    normalise = sub.add_parser("normalise", help="write a normalised, canonical log")
    normalise.add_argument("log", type=Path)
    normalise.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.logs)
    return _normalise(args.log, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
