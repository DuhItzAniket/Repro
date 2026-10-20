"""Repro's sandbox images, built on demand, each tagged by its Dockerfile's digest.

- ``image/Dockerfile`` (D03): Python with uv, for Python projects (``sandbox_image``).
- ``image/node.Dockerfile`` (K11): Node.js with npm, pnpm and Yarn, for JavaScript and
  TypeScript projects (``node_image``).
"""

import hashlib
import subprocess
from pathlib import Path
from typing import Final

from repro.sandbox.process import SandboxError

DOCKERFILE: Final = Path(__file__).with_name("image") / "Dockerfile"
NODE_DOCKERFILE: Final = Path(__file__).with_name("image") / "node.Dockerfile"
#: Building pulls the base image and Debian packages: minutes on a slow network.
BUILD_TIMEOUT_S: Final = 1800.0


def image_tag(dockerfile: Path = DOCKERFILE, repository: str = "repro-sandbox") -> str:
    """``<repository>:<first 12 hex digits of the Dockerfile's SHA-256>``."""
    return f"{repository}:{hashlib.sha256(dockerfile.read_bytes()).hexdigest()[:12]}"


def sandbox_image(docker: str = "docker") -> str:
    """The Python sandbox image's tag, built first if this machine does not have it."""
    return _built(DOCKERFILE, "repro-sandbox", "the sandbox image", docker)


def node_image(docker: str = "docker") -> str:
    """The Node.js sandbox image's tag, built first if this machine does not have it."""
    return _built(NODE_DOCKERFILE, "repro-sandbox-node", "the Node.js sandbox image", docker)


def _built(dockerfile: Path, repository: str, what: str, docker: str) -> str:
    tag = image_tag(dockerfile, repository)
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
            input=dockerfile.read_bytes(),
            capture_output=True,
            timeout=BUILD_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxError(f"{what}: {exc}") from None
    if built.returncode != 0:
        problem = built.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SandboxError(f"building {what} failed: {problem[-1] if problem else '?'}")
    return tag
