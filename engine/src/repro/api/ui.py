"""Where the cockpit's built files are, for ``repro serve``, ``run`` and ``replay`` (C08)."""

from pathlib import Path

#: This checkout's build of the cockpit (``pnpm build``), from ``engine/src/repro/api/``.
CHECKOUT_UI = Path(__file__).resolve().parents[4] / "apps" / "web" / "dist"


def find_ui(configured: Path | None) -> Path | None:
    """The configured directory, else this checkout's build; ``None`` if it holds no cockpit."""
    candidate = configured if configured is not None else CHECKOUT_UI
    return candidate if (candidate / "index.html").is_file() else None
