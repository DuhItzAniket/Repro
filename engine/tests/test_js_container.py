"""JavaScript and TypeScript at L3 (K11; ADR-0017, phase 4): the tests in containers with
Node.js and no network.

Without Docker: a container's paths and the tests' IDs, the install's own container, the
environment read in the sandbox, and an image of the user's refused. With Docker (skipped where
it is missing, except where ``REPRO_REQUIRE_DOCKER=1``, as in ``test_run_stage``):
- a real Vitest change through ``repro run``'s pipeline in containers on Repro's Node.js image,
  its dependencies installed with ``npm ci`` from a real lockfile (``data/js/vitest-npm``) in
  the install's container, the only one with the network;
- pnpm's and Yarn's installs there (``data/js/vitest-pnpm``, ``vitest-yarn``), with none of
  the project's own code run.
"""

import json
import os
import posixpath
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gitrepo import Entry, Repo
from repro import jsmap, jsts, language
from repro.bus import EventBus
from repro.card import regenerate
from repro.card.job import StoreCards
from repro.gitops import Git
from repro.ids import new_run_id
from repro.js_stage import NO_ENV_IMAGE, NODE_UNDETECTED, JsOptions
from repro.orchestrator import Orchestrator
from repro.pipeline import Change, pipeline_jobs
from repro.run_stage import Backend
from repro.sandbox import DockerSandbox, Limits, docker_available
from repro.sandbox.detect import Detections
from repro.sandbox.image import node_image
from repro.sandbox.process import Execution
from repro.store import ArtifactStore, StoreReader, StoreWriter
from repro_events.log import read_log, validate_log
from repro_events.schemas import load_schema_set

#: Vitest projects with real lockfiles: npm's, pnpm's and Yarn classic's.
DATA = Path(__file__).parent / "data" / "js"
docker = pytest.mark.skipif(
    not docker_available() and os.environ.get("REPRO_REQUIRE_DOCKER") != "1",
    reason="Docker with Linux containers is not available",
)


def done(argv: Sequence[str], stdout: bytes = b"", code: int = 0, stderr: bytes = b"") -> Execution:
    return Execution(tuple(argv), "exited", code, 0.1, stdout, stderr, False, False,
                     Detections((), 0, truncated=False))  # fmt: skip


class FakeVolume:
    """What ``VolumeTree`` asks of a ``DockerSandbox``, in memory: its volume's files, and runs
    that write the report the runner would."""

    def __init__(self, report: Mapping[str, Any], shown: bytes = b"") -> None:
        self.files: dict[str, bytes] = {}
        self.runs: list[tuple[list[str], dict[str, str]]] = []
        self.report, self.shown = report, shown

    def write_files(self, directory: str, files: Mapping[str, bytes]) -> None:
        self.files[f"{directory}/"] = b""  # the directory itself
        for path, data in files.items():
            self.files[posixpath.normpath(f"{directory}/{path}")] = data

    def read_file(self, relative: str) -> bytes | None:
        return self.files.get(relative)

    def run(
        self, argv: Sequence[str], *, env: Mapping[str, str], stop: Callable[[], bool] | None
    ) -> Execution:
        self.runs.append((list(argv), dict(env)))
        if "--showConfig" in argv:
            return done(argv, self.shown)
        (out,) = [a.split("=", 1)[1] for a in argv if a.startswith("--outputFile=")]
        inside = PurePosixPath(out).relative_to("/work").as_posix()
        self.files[inside] = json.dumps(self.report).encode()
        return done(argv)


REPORT = {
    "testResults": [
        {
            "name": "/work/test/m.test.js",
            "assertionResults": [
                {
                    "fullName": "m adds",
                    "title": "adds",
                    "ancestorTitles": ["m"],
                    "status": "passed",
                    "location": {"line": 3, "column": 3},
                }
            ],
        }
    ]
}


def test_a_containers_run_names_its_tests_as_the_hosts(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"  # the host's copy, where the project's config is found
    root.mkdir()
    (root / "vitest.config.mjs").write_text("export default {};\n", encoding="utf-8")
    project = jsts.JsProject(root, "vitest", "npm")
    volume = FakeVolume(REPORT)
    out = tmp_path / "runs" / "base-A"
    tree = jsts.VolumeTree(cast(DockerSandbox, volume))
    side = jsts.run_tests(project, tree, out, "abc", trace={"src/m.js": ["add"]})
    assert side.problem == ""
    assert side.outcomes == {"test/m.test.js::m adds": "passed"}
    assert side.starts == {"test/m.test.js::m adds": (3, 3)}
    # The same test reported by a run on the host has the same ID.
    host = {"testResults": [{**REPORT["testResults"][0], "name": str(root / "test" / "m.test.js")}]}
    assert jsts.read_report(json.dumps(host).encode(), root) == side.outcomes
    ((argv, env),) = volume.runs
    here = "/work/.repro/runs/base-A"
    assert argv[:3] == ["node", "/work/node_modules/vitest/vitest.mjs", "run"]
    assert f"--outputFile={here}/{jsts.REPORT}" in argv
    assert argv[-2:] == ["--config", jsmap.WRAPPER]
    assert env["NODE_OPTIONS"] == jsts.NODE_OPTIONS
    assert env["REPRO_JS_MAP"] == f"{here}/{jsmap.MAP_FILE}"
    assert env["REPRO_JS_TRACE_OUT"] == f"{here}/repro-calls.jsonl"
    # The run's directory, the setup files and the wrapper went into the volume, not the host.
    assert ".repro/runs/base-A/" in volume.files
    names = {jsmap.VITEST_SETUP, jsmap.WRAPPER, jsmap.TRACE_RUNTIME, jsmap.TRACE_PLUGIN}
    assert names <= volume.files.keys()
    assert 'import base from "./vitest.config.mjs";' in volume.files[jsmap.WRAPPER].decode()
    assert not (root / jsmap.WRAPPER).exists()
    # The report is kept on the host, as a process sandbox's is; the map was never written.
    assert (out / jsts.REPORT).read_bytes() == volume.files[f".repro/runs/base-A/{jsts.REPORT}"]
    assert side.map is not None
    assert side.map.problem == "the setup file wrote no map"


def test_jests_setup_is_named_by_its_path_in_the_container(tmp_path: Path) -> None:
    project = jsts.JsProject(tmp_path, "jest", "npm")
    shown = json.dumps({"configs": [{"setupFilesAfterEnv": ["/work/own.js"]}]}).encode()
    volume = FakeVolume(REPORT, shown)
    jsts.run_tests(project, jsts.VolumeTree(cast(DockerSandbox, volume)), tmp_path / "H", "abc")
    (config, _), (argv, _) = volume.runs
    assert config == ["node", "/work/node_modules/jest/bin/jest.js", "--showConfig"]
    assert argv[-3:] == ["--setupFilesAfterEnv", "/work/own.js", "/work/repro_map_jest.cjs"]
    assert jsmap.JEST_SETUP in volume.files


def box(**changes: Any) -> DockerSandbox:
    found = {"docker": "docker", "volume": "repro-0123456789ab", "image": "img", "runtime": None}
    return cast(DockerSandbox, SimpleNamespace(**(found | changes)))


def test_the_install_has_a_container_of_its_own_with_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = jsts.JsProject(tmp_path, "vitest", "npm")
    seen: list[list[str]] = []

    def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    jsts.install_in_container(box(runtime="runsc"), project)
    ((*flags, script),) = seen
    assert "--network" not in flags  # the only container with the network: no target code runs
    for flag in ("--read-only", "ALL", "no-new-privileges", "1000:1000", "runsc"):
        assert flag in flags
    assert "YARN_IGNORE_PATH=1" in flags
    assert flags[flags.index("-v") + 1] == "repro-0123456789ab:/work"
    assert script.endswith("; npm ci --ignore-scripts --no-audit --no-fund")
    assert "trap 'rm -rf /work/.repro/cache' EXIT" in script  # the caches are not the project's
    assert "export COREPACK_HOME=/tmp/corepack" in script


def test_an_install_that_fails_or_hangs_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = jsts.JsProject(tmp_path, "vitest", "pnpm")
    said = (
        b"npm error `npm ci` can only install packages when your package.json and "
        b"package-lock.json are in sync.\nnpm error A complete log of this run can be found in: "
        b"/tmp/x.log\n"
    )
    failed = subprocess.CompletedProcess(["docker"], 1, b"", said)
    monkeypatch.setattr(subprocess, "run", lambda *_, **__: failed)
    with pytest.raises(jsts.JsError, match="the install failed: npm error `npm ci` can only"):
        jsts.install_in_container(box(), project)
    # pnpm writes its errors on stdout; Node's version ends an uncaught error's output.
    pnpm = b" ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with frozen-lockfile\n"
    failed = subprocess.CompletedProcess(["docker"], 1, pnpm, b"Node.js v22.23.3\n")
    with pytest.raises(jsts.JsError, match="failed: ERR_PNPM_OUTDATED_LOCKFILE  Cannot install"):
        jsts.install_in_container(box(), project)
    removed: list[list[str]] = []

    def hangs(argv: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[1] == "run":
            assert argv[-1].endswith(
                "; pnpm install --frozen-lockfile --ignore-scripts --ignore-pnpmfile"
            )
            raise subprocess.TimeoutExpired(argv, 1)
        removed.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", hangs)
    with pytest.raises(jsts.JsError, match="longer than"):
        jsts.install_in_container(box(), project)
    ((docker, rm, force, name),) = removed  # the container is removed, not left running
    assert (docker, rm, force) == ("docker", "rm", "-f")
    assert name.startswith("repro-install-")


def test_the_hosts_install_runs_none_of_the_projects_code_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = jsts.JsProject(tmp_path, "vitest", "pnpm")
    entry = tmp_path / "node_modules" / "vitest" / "vitest.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    seen: list[tuple[list[str], Mapping[str, str]]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)
    jsts.install_dependencies(project)
    ((argv, env),) = seen
    assert argv == [
        "/usr/bin/pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile"
    ]  # fmt: skip
    assert env["YARN_IGNORE_PATH"] == "1"


#: What a project's own code would leave if it ran during the install.
RAN = "require('node:fs').writeFileSync('/work/RAN', 'ran');\n"


@docker
@pytest.mark.parametrize(
    ("fixture", "own"),
    [
        ("vitest-pnpm", {".pnpmfile.cjs": RAN + "module.exports = { hooks: {} };\n"}),
        ("vitest-yarn", {".yarnrc": 'yarn-path "./own-yarn.cjs"\n', "own-yarn.cjs": RAN}),
    ],
)
def test_an_install_in_a_container_runs_none_of_the_projects_code(
    tmp_path: Path, fixture: str, own: dict[str, str]
) -> None:
    """pnpm's hooks file and Yarn classic's ``yarn-path`` are the project's code, which runs
    with the install's network unless they are ignored (both ran here before they were)."""
    files = {p.name: p.read_bytes() for p in (DATA / fixture).iterdir()}
    files |= {name: text.encode() for name, text in own.items()}
    repo = Repo(tmp_path / "repo")
    sha = repo.commit(dict(files))
    tree = tmp_path / "tree"  # the host's copy, which the project is read from
    tree.mkdir()
    for name, data in files.items():
        (tree / name).write_bytes(data)
    project = jsts.JsProject.detect(tree)
    limits = Limits(timeout_s=300)
    with DockerSandbox(
        tmp_path / "box", Git(repo.path), sha, image=node_image(), limits=limits
    ) as box:
        jsts.install_in_container(box, project)
        node, installed = jsts.container_environment(box, project)
        assert node.startswith("22.")
        assert "vitest" in installed
        assert box.read_file("RAN") is None
        left = box.run(["ls", "-A", "/work/.repro"])
        assert left.stdout.split() == []  # the caches went with the install's container


class Probe:
    """A sandbox whose ``node -e`` prints ``stdout``."""

    def __init__(self, stdout: bytes, code: int = 0) -> None:
        self.stdout, self.code = stdout, code
        self.argv: list[str] = []

    def run(self, argv: Sequence[str], **_: Any) -> Execution:
        self.argv = list(argv)
        return done(argv, self.stdout, self.code, b"node: bad option")


def test_the_environment_is_read_in_the_sandbox(tmp_path: Path) -> None:
    project = jsts.JsProject(tmp_path, "vitest", "npm")
    found = {"node": "v22.23.3", "entry": True, "installed": {"vitest": "5.0.5", "vite": "8.1.0"}}
    probe = Probe(json.dumps(found).encode() + b"\n")
    node, installed = jsts.container_environment(cast(DockerSandbox, probe), project)
    assert (node, installed) == ("22.23.3", {"vitest": "5.0.5", "vite": "8.1.0"})
    assert probe.argv[0::2] == ["node", jsts._ENVIRONMENT]
    assert probe.argv[-1] == "node_modules/vitest/vitest.mjs"
    gone = Probe(json.dumps({**found, "entry": False}).encode())
    with pytest.raises(jsts.JsError, match=r"vitest\.mjs cannot be read"):
        jsts.container_environment(cast(DockerSandbox, gone), project)
    with pytest.raises(jsts.JsError, match="node did not report in the container: node: bad"):
        jsts.container_environment(cast(DockerSandbox, Probe(b"", 9)), project)


# -- through the pipeline -------------------------------------------------------------------------

SOURCE = (
    "export function add(a, b) {\n  return a + b;\n}\n\n"
    'export function label(n) {\n  return "n=" + n.toFixed(1);\n}\n'
)
TESTS = (
    'import { add, label } from "../src/m.js";\n'
    'describe("m", () => {\n'
    '  test("adds", () => {\n'
    "    expect(add(1, 2)).toBe(3);\n"
    "    expect(add(0, 0)).toBe(0);\n"
    "  });\n"
    '  test("labels", () => {\n    expect(label(2)).toContain("n=");\n  });\n'
    '  test("old", () => {\n    expect(add(2, 2)).toBe(4);\n  });\n'
    "});\n"
)
#: Node's own attempt: blocked in a container, and not seen by Repro's detection.
NETWORK = (
    'test("cannot reach the network", async () => {\n'
    "  const signal = AbortSignal.timeout(5000);\n"
    '  await expect(fetch("https://registry.npmjs.org/", { signal })).rejects.toThrow();\n'
    "});\n"
)


def project_files() -> dict[str, Entry]:
    return {
        "package.json": (DATA / "vitest-npm" / "package.json").read_bytes(),
        "package-lock.json": (DATA / "vitest-npm" / "package-lock.json").read_bytes(),
        "vitest.config.mjs": "export default { test: { globals: true } };\n",
        "repro.yml": "version: 1\ninvariants:\n  - no_network: true\n",
        "src/m.js": SOURCE,
        "test/m.test.js": TESTS,
        "test/net.test.js": NETWORK,
    }


def reproduce(
    tmp_path: Path,
    head: dict[str, Entry | None],
    backend: Backend,
    *,
    env_image: str | None = None,
    js: JsOptions | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Base (``project_files``) against base with ``head`` applied: the run's events, checked,
    and its card."""
    repo = Repo(tmp_path / "repo")
    base_sha = repo.commit(project_files())
    head_sha = repo.commit(head)
    git = Git(repo.path)
    found = language.detect(git, base_sha, head_sha)
    change = replace(Change.resolve(git, repo.path, base_sha, head_sha), language=found)
    database = tmp_path / "repro.db"
    writer = StoreWriter(database).start()
    run_id = new_run_id()
    try:
        jobs, state = pipeline_jobs(
            git,
            change,
            tmp_path / "work",
            backend=backend,
            cache=tmp_path / "cache",
            analyse_only=False,
            artifacts=ArtifactStore(tmp_path / "runs", writer),
            cards=StoreCards(database, writer),
            env_image=env_image,
            js=js,
        )
        try:
            result = Orchestrator(EventBus(writer), concurrency=2).run(
                change.spec(), jobs, run_id=run_id
            )
        finally:
            state.close()
        assert result.outcome == "completed", result.jobs
    finally:
        writer.close()
    with StoreReader(database) as reader:
        events = [json.loads(e.body) for e in reader.iter_events(run_id)]
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines, issues = read_log(log)
    assert issues + validate_log(load_schema_set(), lines) == []
    (published,) = [e for e in events if e["kind"] == "card.published"]
    assert regenerate(events).identical
    return events, published["payload"]["card"]


def payloads(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in events if e["kind"] == kind]


def evidence(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [
        p["evidence"] for p in payloads(events, "evidence.created") if p["evidence"]["type"] == kind
    ]


def test_an_image_of_the_users_is_refused_for_javascript(tmp_path: Path) -> None:
    events, card = reproduce(tmp_path, {"src/m.js": SOURCE + "\n"}, "process", env_image="x:1")
    found = [p["missing"] for p in payloads(events, "missing.recorded")]
    refused = [m for m in found if m["reason"] == "environment_failed"]
    assert {m["detail"] for m in refused} == {f"base: {NO_ENV_IMAGE}", f"head: {NO_ENV_IMAGE}"}
    assert payloads(events, "sandbox.ready") == []
    assert card["status"] == "UNVERIFIABLE"


@docker
def test_a_change_is_reproduced_in_containers_with_no_network(tmp_path: Path) -> None:
    head = SOURCE.replace("return a + b;", "return a - b;").replace("n.toFixed(1)", "n")
    events, card = reproduce(tmp_path, {"src/m.js": head}, "docker")
    ready = payloads(events, "sandbox.ready")
    assert {(r["side"], r["backend"], r["isolation_level"], r["network"]) for r in ready} == {
        ("base", "docker", "L3", "enforced"),
        ("head", "docker", "L3", "enforced"),
    }
    assert all("repro-sandbox-node:" in r["platform"] for r in ready)
    for env in payloads(events, "env.provisioned"):
        assert (env["project_kind"], env["python_version"]) == ("npm", None)
        assert env["node_version"].startswith("22.")  # the image's Node.js, not the host's
        assert env["installed_packages"] > 1  # vitest and what it needs, read in the container
    # The tests' IDs are the host's (test_js_stage), and so are the outcomes.
    classes = {
        o["targets"][0]["test"]: o["data"]["class"] for o in evidence(events, "test_outcome")
    }
    assert classes == {
        "test/m.test.js::m adds": "P2F",
        "test/m.test.js::m labels": "P2P",
        "test/m.test.js::m old": "P2F",
    }
    found = evidence(events, "behaviour_diff")  # traced in the container
    assert ("src/m.js:label#0", "result_changed") in {
        (b["targets"][0]["symbol"], b["data"]["change"]) for b in found
    }
    # The network is cut off: Node's fetch failed on each side, so its test passed (each run's
    # report is kept on the host). No network_not_enforced item; no_network passes on the
    # enforcement alone, and says that Node's attempt was not seen.
    for run in ("base-A", "head-H", "base-A2"):
        report = (tmp_path / "work" / "runs" / run / jsts.REPORT).read_bytes()
        outcomes = jsts.read_report(report, PurePosixPath("/work"))
        assert outcomes["test/net.test.js::cannot reach the network"] == "passed", run
    assert "network_not_enforced" not in {item["reason"] for item in card["missing"]}
    (result,) = payloads(events, "invariant.result")
    assert (result["invariant"], result["result"]) == ("no_network", "pass")
    assert result["message"].endswith(f"their attempts are not seen ({NODE_UNDETECTED})")
    assert card["status"] == "FLAGGED"
    conditions = card["conditions"]
    assert (conditions["language"], conditions["isolation_level"]) == ("javascript", "L3")
    assert conditions["node_version"].startswith("22.")
