"""Repro's sandbox image (D03): ``image/Dockerfile``, built on demand, tagged by its digest."""

import hashlib
import subprocess
from pathlib import Path
from typing import Final

from repro.sandbox.process import SandboxError

DOCKERFILE: Final = Path(__file__).with_name("image") / "Dockerfile"
#: Building pulls the base image and Debian packages: minutes on a slow network.
BUILD_TIMEOUT_S: Final = 1800.0


def image_tag() -> str:
    """``repro-sandbox:<first 12 hex digits of the Dockerfile's SHA-256>``."""
    return f"repro-sandbox:{hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:12]}"


def sandbox_image(docker: str = "docker") -> str:
    """The sandbox image's tag, built first if this machine does not have it."""
    tag = image_tag()
    try:
        present = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
            [docker, "image", "inspect", "--format", "{{.Id}}", tag],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if present.returncode == 0:
            return tag
        built = subprocess.run(  # noqa: S603 - docker, building Repro's own Dockerfile
            [docker, "build", "--tag", tag, "-"],
            input=DOCKERFILE.read_bytes(),
            capture_output=True,
            timeout=BUILD_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxError(f"the sandbox image: {exc}") from None
    if built.returncode != 0:
        problem = built.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SandboxError(f"building the sandbox image failed: {problem[-1] if problem else '?'}")
    return tag
