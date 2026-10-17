"""Where the cockpit's built files are, for ``repro serve``, ``run`` and ``replay`` (C08): the
configured directory, else this checkout's build, else the copy a release's wheel carries
(``repro/api/cockpit``, put there by ``scripts/build_wheels.py``; H05)."""

from pathlib import Path

#: This checkout's build of the cockpit (``pnpm build``), from ``engine/src/repro/api/``.
CHECKOUT_UI = Path(__file__).resolve().parents[4] / "apps" / "web" / "dist"
#: The build a release's wheel carries.
PACKAGED_UI = Path(__file__).resolve().parent / "cockpit"


def find_ui(configured: Path | None) -> Path | None:
    """The configured directory (``None`` if it holds no cockpit), else this checkout's build,
    else the packaged one; ``None`` if there is none."""
    candidates = [configured] if configured is not None else [CHECKOUT_UI, PACKAGED_UI]
    return next((c for c in candidates if (c / "index.html").is_file()), None)
