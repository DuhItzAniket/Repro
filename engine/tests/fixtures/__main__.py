"""Builds a fixture repository and prints its commits as JSON (the browser gates use it).

Run from ``engine/tests``: ``python -m fixtures <name> <dest>``; ``dest`` must not exist.
"""

import json
import sys
from pathlib import Path

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS


def main(argv: list[str]) -> int:
    if len(argv) != len(("name", "dest")) or argv[0] not in ALL_SPECS:
        names = "|".join(sorted(ALL_SPECS))
        sys.stderr.write(f"usage: python -m fixtures <{names}> <dest>\n")
        return 2
    built = build_repo(ALL_SPECS[argv[0]], Path(argv[1]))
    found = {"path": str(built.path), "base": built.base_sha, "heads": built.head_shas}
    sys.stdout.write(json.dumps(found) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
