"""A release's wheels (H05): repro-engine with the cockpit inside, repro-events with the schemas.

uv_build puts in a wheel what is under the package's own directory. The cockpit's build
(``apps/web/dist``) and the event schemas (``packages/events/schema``) live elsewhere in the
checkout, so they are copied in for the build, to ``repro/api/cockpit`` and
``repro_events/schema`` (both git-ignored), and removed afterwards. At run time a checkout's own
copy is preferred (``repro.api.ui``, ``repro_events.schemas``); an installed wheel has only its
own. Each wheel is checked for what it must carry before the script says it is done.

    pnpm build
    uv run python scripts/build_wheels.py [--out dist/wheels]
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COCKPIT = ROOT / "apps" / "web" / "dist"
SCHEMAS = ROOT / "packages" / "events" / "schema"
COPIES = {
    COCKPIT: ROOT / "engine" / "src" / "repro" / "api" / "cockpit",
    SCHEMAS: ROOT / "packages" / "events" / "python" / "src" / "repro_events" / "schema",
}
#: What each wheel must hold, besides its code.
MUST_HOLD = {
    "repro_engine": (
        "repro/api/cockpit/index.html",
        "repro/sandbox/_hook/sitecustomize.py",
        "repro/sandbox/image/Dockerfile",
        "repro/sandbox/image/node.Dockerfile",
        "repro/agents/prompts/lock.json",
    ),
    "repro_events": (
        "repro_events/schema/event.schema.json",
        "repro_events/schema/attestation/reproduction-card-v0.schema.json",
    ),
}


def build(out: Path) -> list[Path]:
    """The two wheels, built with the cockpit and the schemas copied in, into ``out``."""
    if not (COCKPIT / "index.html").is_file():
        sys.exit("build_wheels: the cockpit is not built (run pnpm build first)")
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("repro_*.whl"):
        stale.unlink()
    try:
        for source, target in COPIES.items():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
        for package in ("repro-events", "repro-engine"):
            subprocess.run(  # noqa: S603 - uv, with this script's own arguments
                ["uv", "build", "--package", package, "--wheel", "--out-dir", str(out)],  # noqa: S607
                cwd=ROOT,
                check=True,
            )
    finally:
        for target in COPIES.values():
            shutil.rmtree(target, ignore_errors=True)
    wheels = sorted(out.glob("repro_*.whl"))
    for wheel in wheels:
        names = set(zipfile.ZipFile(wheel).namelist())
        distribution = wheel.name.split("-")[0]
        missing = [name for name in MUST_HOLD.get(distribution, ()) if name not in names]
        if missing:
            sys.exit(f"build_wheels: {wheel.name} lacks {', '.join(missing)}")
    return wheels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "wheels")
    args = parser.parse_args()
    for wheel in build(args.out):
        sys.stdout.write(f"{wheel.relative_to(ROOT) if wheel.is_relative_to(ROOT) else wheel}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
