"""The pinned TypeScript compiler: fetched once, checked, unpacked safely, run by Repro's worker
(K11; ADR-0017, phase 4)."""

import base64
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from repro.analysis import typescript
from repro.analysis.typescript import VERSION, TypeScriptError
from ts_support import NEEDS_NODE, pinned

MANIFEST = {"name": "typescript", "version": VERSION, "license": "Apache-2.0"}


@pytest.fixture(scope="module")
def package(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return pinned(pytestconfig, tmp_path_factory)


def tarball(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def a_package(manifest: dict[str, str] = MANIFEST) -> dict[str, bytes]:
    return {
        "package/package.json": json.dumps(manifest).encode(),
        "package/lib/typescript.js": b"// the compiler\n",
    }


def test_a_tarball_is_checked_against_the_registrys_integrity() -> None:
    data = b"not the compiler"
    with pytest.raises(TypeScriptError, match="does not match the registry's integrity"):
        typescript.check(data)
    own = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    typescript.check(data, own)
    with pytest.raises(TypeScriptError, match="sha1 is not checked"):
        typescript.check(data, "sha1-" + base64.b64encode(hashlib.sha1(data).digest()).decode())  # noqa: S324


def test_the_package_is_unpacked_once_and_then_used_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unpacked = typescript.unpack(tarball(a_package()), tmp_path)
    assert unpacked == typescript.package_dir(tmp_path) == tmp_path / f"typescript-{VERSION}"
    assert typescript.ready(unpacked)
    assert [p.name for p in tmp_path.iterdir()] == [unpacked.name]  # the scratch is gone

    def offline() -> bytes:
        raise TypeScriptError("offline")

    monkeypatch.setattr(typescript, "fetch", offline)
    assert typescript.ensure(tmp_path) == unpacked  # no fetch for a ready package
    (unpacked / typescript.MARKER).write_text("sha512-other\n", encoding="ascii")
    with pytest.raises(TypeScriptError, match="offline"):  # not the pinned one: fetched again
        typescript.ensure(tmp_path)


def test_a_package_that_is_not_the_pinned_one_is_refused(tmp_path: Path) -> None:
    other = {**MANIFEST, "version": "7.0.2"}
    with pytest.raises(TypeScriptError, match=f"not typescript {VERSION}"):
        typescript.unpack(tarball(a_package(other)), tmp_path)
    assert not typescript.package_dir(tmp_path).exists()


def test_a_path_out_of_the_tarball_is_refused(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    files = {**a_package(), "../escaped.js": b"outside"}
    with pytest.raises(TypeScriptError, match="could not be unpacked"):
        typescript.unpack(tarball(files), tools)
    assert not (tmp_path / "escaped.js").exists()
    assert not typescript.package_dir(tools).exists()


def test_without_node_the_worker_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(TypeScriptError, match="node is not installed"):
        typescript.run(tmp_path, {}, tmp_path)


@NEEDS_NODE
def test_the_pinned_compiler_is_the_registrys_and_the_worker_runs_it(
    package: Path, tmp_path: Path
) -> None:
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    assert (manifest["name"], manifest["version"], manifest["license"]) == (
        "typescript",
        "6.0.3",
        "Apache-2.0",
    )
    assert "Apache License" in (package / "LICENSE.txt").read_text(encoding="utf-8")
    assert typescript.run(package, {}, tmp_path) == {"version": "6.0.3", "api": [], "tests": []}
    assert list(tmp_path.iterdir()) == []  # the request file is removed


@NEEDS_NODE
def test_relative_paths_reach_the_worker_resolved(
    package: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The worker runs in its work directory: a relative tools directory must not be required
    # from there, or as a package name. Both paths are relative to the package's own directory:
    # on CI's Windows the package (the checkout's cache) and tmp_path are on different drives,
    # where no relative path joins them.
    monkeypatch.chdir(package.parent)
    work = Path(f"work-{tmp_path.name}")
    try:
        assert typescript.run(Path(package.name), {}, work)["version"] == "6.0.3"
    finally:
        shutil.rmtree(package.parent / work, ignore_errors=True)
