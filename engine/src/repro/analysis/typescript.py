"""The TypeScript compiler Repro pins, and its worker (K11; ADR-0017, phase 4).

The compiler API reads JavaScript and TypeScript alike. Repro uses it for a change's public API
(``repro.analysis.jsapi``) and for its edited tests' assertions (``repro.jsassert``).

**Which compiler.** Repro's own, never the target's: a target's ``node_modules/typescript`` is
the target's code. The pin is ``typescript`` 6.0.3, the last line whose package is the compiler
API in JavaScript, with no dependencies [npm registry, ``npm view typescript@6.0.3``, checked
2026-10-20: ``main`` is ``./lib/typescript.js``; 7.0.2 is native binaries per platform, with an
API under ``unstable/``]. Its licence is Apache-2.0, as its own ``package.json`` and
``LICENSE.txt`` say.

**How it is fetched.** Once, into ``<tools>/typescript-6.0.3`` (``<data dir>/tools`` by
default): the registry's tarball, checked against the registry's ``dist.integrity`` (sha512)
before it is unpacked, with tarfile's ``data`` filter (no absolute paths, no links out of the
directory). No package manager runs, so no lifecycle script can; the package needs none. A
directory holding the package and Repro's marker of the same integrity is used as it is, so an
image can carry it ready (``ensure`` there, at build time).

**How it runs.** The host's Node runs Repro's worker (``_ts_worker.cjs``) on a request file.
The worker loads the pinned compiler by its path and reads only the trees the request names and
the compiler's own lib directory. Parsing and type-checking run nothing of the target.
"""

import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

#: The pinned compiler, and the registry's integrity for its tarball
#: (``npm view typescript@6.0.3 dist.integrity``, 2026-10-20).
VERSION: Final = "6.0.3"
INTEGRITY: Final = (
    "sha512-y2TvuxSZPDyQakkFRPZHKFm+KKVqIisdg9/CZwm9ftvKXLP8NRWj38"
    "/ODjNbr43SsoXqNuAisEf1GdCxqWcdBw=="
)
TARBALL: Final = f"https://registry.npmjs.org/typescript/-/typescript-{VERSION}.tgz"
LICENSE: Final = "Apache-2.0"
#: Written into the unpacked package once it is checked: its integrity.
MARKER: Final = ".repro-integrity"
#: The tarball is 4.5 MB; anything far larger is not it.
MAX_BYTES: Final = 64 * 1024**2
FETCH_TIMEOUT_S: Final = 120.0
WORKER_TIMEOUT_S: Final = 300.0
WORKER: Final = Path(__file__).with_name("_ts_worker.cjs")
#: Variables that would make Node load more than the worker (``--require``, module paths).
_NODE_VARIABLES: Final = ("NODE_OPTIONS", "NODE_PATH")
_FETCHING: Final = threading.Lock()
#: A JavaScript error's line in Node's report of it: ``TypeError: x is undefined``.
_ERROR: Final = re.compile(r"^[A-Za-z]*Error\b")


class TypeScriptError(Exception):
    """The compiler could not be fetched or run; the message says why."""


def package_dir(tools: Path) -> Path:
    """Where the pinned compiler's package is kept under ``tools``."""
    return tools / f"typescript-{VERSION}"


def ready(package: Path) -> bool:
    """Whether ``package`` holds the pinned compiler, checked when it was unpacked."""
    try:
        marker = (package / MARKER).read_text(encoding="ascii").strip()
    except OSError:
        return False
    return marker == INTEGRITY and (package / "lib" / "typescript.js").is_file()


def ensure(tools: Path) -> Path:
    """The pinned compiler's package directory, fetched into ``tools`` on first use."""
    package = package_dir(tools)
    if ready(package):
        return package
    with _FETCHING:
        if not ready(package):
            unpack(fetch(), tools)
    return package


def fetch(url: str = TARBALL) -> bytes:
    """The compiler's tarball from the registry, checked against ``INTEGRITY``."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as response:  # noqa: S310 - the registry's https URL
            data: bytes = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise TypeScriptError(
            f"TypeScript {VERSION} could not be fetched from the npm registry: {exc}"
        ) from None
    if len(data) > MAX_BYTES:
        raise TypeScriptError(f"the TypeScript {VERSION} tarball is larger than {MAX_BYTES} bytes")
    check(data)
    return data


def check(data: bytes, integrity: str = INTEGRITY) -> None:
    """Raises unless ``data`` has the ``integrity`` (the registry's ``sha512-<base64>``)."""
    algorithm, _, expected = integrity.partition("-")
    if algorithm != "sha512":
        raise TypeScriptError(f"an integrity of {algorithm} is not checked: sha512 is")
    found = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    if found != expected:
        raise TypeScriptError(
            f"the TypeScript {VERSION} tarball does not match the registry's integrity: "
            f"sha512-{found}"
        )


def unpack(data: bytes, tools: Path) -> Path:
    """Unpacks the checked tarball into ``package_dir(tools)``; the package's own name, version
    and licence are checked first. Another process that got there first wins."""
    tools.mkdir(parents=True, exist_ok=True)
    package = package_dir(tools)
    scratch = Path(tempfile.mkdtemp(prefix=f".typescript-{VERSION}-", dir=tools))
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(scratch, filter="data")
        unpacked = scratch / "package"
        _check_manifest(unpacked)
        (unpacked / MARKER).write_text(INTEGRITY + "\n", encoding="ascii")
        if package.exists() and not ready(package):
            shutil.rmtree(package)
        try:
            unpacked.rename(package)
        except OSError:
            if not ready(package):
                raise
    except (OSError, tarfile.TarError) as exc:
        raise TypeScriptError(
            f"the TypeScript {VERSION} tarball could not be unpacked: {exc}"
        ) from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return package


def _check_manifest(package: Path) -> None:
    try:
        manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TypeScriptError(f"the tarball's package.json cannot be read: {exc}") from None
    found = (manifest.get("name"), manifest.get("version"), manifest.get("license"))
    if found != ("typescript", VERSION, LICENSE):
        raise TypeScriptError(f"the tarball holds {found}, not typescript {VERSION} ({LICENSE})")


def run(package: Path, request: Mapping[str, Any], work: Path) -> dict[str, Any]:
    """The worker's response to ``request`` (``_ts_worker.cjs`` says what each holds), run by
    the host's Node with the compiler in ``package``."""
    node = shutil.which("node")
    if node is None:
        raise TypeScriptError("node is not installed")
    work = work.resolve()  # the worker runs in it, and requires the compiler by its path
    work.mkdir(parents=True, exist_ok=True)
    asked = work / "ts-request.json"
    asked.write_text(
        json.dumps({"typescript": str(package.resolve()), **request}), encoding="utf-8"
    )
    environment = {k: v for k, v in os.environ.items() if k.upper() not in _NODE_VARIABLES}
    try:
        done = subprocess.run(  # noqa: S603 - the host's node, Repro's own worker
            [node, str(WORKER), str(asked)],
            capture_output=True,
            timeout=WORKER_TIMEOUT_S,
            env=environment,
            cwd=work,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TypeScriptError(f"the compiler took longer than {WORKER_TIMEOUT_S:g} s") from None
    except OSError as exc:
        raise TypeScriptError(f"node could not be started: {exc}") from None
    finally:
        asked.unlink(missing_ok=True)
    if done.returncode != 0:
        # Node ends an uncaught error's report with its own version: the error is the line
        # naming one.
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        errors = [line.strip() for line in lines if _ERROR.match(line.strip())]
        message = errors[-1] if errors else lines[-1] if lines else "no message"
        raise TypeScriptError(
            f"the compiler's worker failed (exit {done.returncode}): {message[:300]}"
        )
    try:
        response: dict[str, Any] = json.loads(done.stdout)
    except ValueError:
        raise TypeScriptError("the compiler's worker gave no JSON") from None
    return response
