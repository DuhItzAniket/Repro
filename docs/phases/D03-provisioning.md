# D03 — Environment provisioning

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | in progress |
| **Depends on** | D02 |
| **Branch / PR** | `phase/D03-provisioning` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
Each side gets an environment its tests can run in: the same interpreter on both sides, the
project's dependencies from the package index, the project itself installed, and never any
target code running while the network is on. When that cannot be done, the change is
UNVERIFIABLE with the reason, never a crash.

## Scope
- **The project** (`repro.provision.inspect_project`): its kind from its files (uv, poetry, pdm,
  requirements, setuptools) and its requirements: `uv export --frozen` for `uv.lock`; the
  packages, versions and markers of `poetry.lock` / `pdm.lock`; `requirements*.txt` with `-r`
  includes inside the snapshot; else `[project]` dependencies, test extras and dependency
  groups, and `setup.py` / `setup.cfg` literals read with `ast` and `configparser`. Anything
  that is not from the index (a URL, a path, VCS, a pip option, a lock package from another
  source) is refused with its reason. `pytest` is added, and noted, when undeclared.
- **The environment** (`HostProvisioner` for the process sandbox, `DockerProvisioner` for
  containers): the dependencies and build requirements installed from wheels only into an
  environment cached by the digest of what it holds (interpreter, platform, requirements,
  cut-off date); a copy of it for the side; the project installed into the copy, editable and
  offline, in the sandbox. `env.provisioned` reports kind, Python version, lock digest, packages
  and whether the cache was used; a failure becomes an `environment_failed` missing item.
- **Repro's sandbox image** (`repro.sandbox.image`): the pinned Python 3.13 image with uv
  0.13.0 and `less`, `git`, `procps`, `tzdata`, built on demand and tagged by its Dockerfile's
  digest.
- **Five fixture projects** (`engine/tests/data/projects/`), one per kind.

## Out of scope
- Running the selected tests and comparing sides (D04–D06); projects needing another Python
  than 3.13, compiled extensions without wheels, or private indexes.

## Design notes
- **No target code with the network on.** The dependencies' step uses `--no-build`: a source
  distribution's build code would otherwise run with the network on. It reads the index Repro
  names (`--index-url https://pypi.org/simple`), with uv's configuration files ignored
  (`UV_NO_CONFIG`), and holds nothing of the project. The project's own build (its backend, its
  `setup.py`) runs only afterwards, offline, in the sandbox.
- **uv cannot use a read-only cache.** ADR-0004 and research/03 §7 planned a read-only cache
  mount with `--link-mode copy`. Measured with uv 0.13.0: a cache mounted read-only fails at once
  ("Failed to initialize cache", `EROFS`), whoever owns it, because uv opens files in it for
  writing whenever it initialises one. So the shared, cached thing is the dependencies'
  environment, which no target code has touched; each side gets a copy, and a uv cache of its
  own that is thrown away. ADR-0004 carries an implementation note.
- **The host never runs an environment's interpreter.** A package can ship a `.pth` file whose
  code runs at start-up. The Python version comes from the base interpreter named in
  `pyvenv.cfg` (`home`), run with `-I -S`; packages are counted from `.dist-info` directories.
- **The same interpreter on both sides, stated.** 3.13 everywhere: the image's in containers,
  uv's on the host. A project whose `requires-python` excludes it fails with uv's reason.
- **Editable builds.** The project is installed editable, so its code runs from the snapshot's
  own files (what tracing needs, Stage E), with `--no-build-isolation`, which means a backend's
  editable-time requirements must already be there. They are taken from the backends' source:
  hatchling 1.25.0's `get_requires_for_build_editable` adds `editables~=0.3`; poetry-core,
  pdm-backend and setuptools needed nothing more.
- **Reproducible resolution.** Unpinned requirements resolve with `--exclude-newer`, the same
  cut-off for both sides.

## Acceptance criteria
- [ ] AC1 (roadmap): five fixture project types provision on both OSes.
- [ ] AC2 (roadmap): a broken install gives UNVERIFIABLE with a reason, never a crash.
- [ ] AC3: no target code runs while the network is on; anything but the index is refused.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_provision_env.py`: each kind on the host (Windows and Ubuntu in CI) and in a container (Ubuntu in CI, and Docker Desktop locally); the fixture's own tests pass in the result |
| AC2 | `test_provision_env.py`: a package that does not exist, one with only a source distribution, a project whose build fails; each a `ProvisionError` and an `environment_failed` item |
| AC3 | `test_provision_project.py`: URLs, VCS, paths, pip options, includes outside the snapshot and foreign lock sources are refused; `--no-build` refuses the sdist-only package |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/provision/`: `project.py`, `env.py`. `engine/src/repro/sandbox/image.py` and
  `image/Dockerfile`. `DockerSandbox.adopt_volume`.
- Fixture projects in `engine/tests/data/projects/` (excluded from Repro's own lint, type check
  and test collection: they are target code). The uv fixture's lock was written by uv 0.13.0;
  the poetry and pdm locks are fixtures in those formats, holding what Repro reads.
- Tests: `test_provision_project.py` (19), `test_provision_env.py` (14). pytest 926 → 959 (957
  pass and 2 skip on Windows with Docker Desktop).
- ADR-0004 implementation note; THREAT_MODEL T5 and T6; ARCHITECTURE §8.

## Evidence
- **Windows, process sandbox**: all five kinds provision and their tests pass in the result; a
  dependencies' environment is built in about 2–6 s and reused in about 1.4–4.6 s (the project's
  own install included), measured here.
- **Windows with Docker Desktop, containers**: all five kinds provision in Repro's image and their
  tests pass in the hardened container with no network, about 6 s each with the dependencies
  cached. On Linux, `colorama` (marked `sys_platform == 'win32'`) is rightly not installed.
- The image builds in about 30 s; its uv is 0.13.0, its tools present.
- A package that does not exist, the sdist-only `pyperclip` 1.9.0 (PyPI lists only
  `pyperclip-1.9.0.tar.gz`), and a failing `setup.py` each end in a `ProvisionError` with uv's
  reason and a valid `environment_failed` item.
- CI run: linked in the PR.

## Deviations from spec
- The read-only uv cache of ADR-0004 point 4 is replaced by a cached dependencies' environment
  (Design notes): uv cannot use a read-only cache.
- "Index-only egress" is enforced by what may be asked for (only index requirements, `--no-build`,
  Repro's index URL, no uv configuration), not by a network filter.

## Known gaps
- Python 3.13 only; a project that needs another version is UNVERIFIABLE.
- Workspaces with path members, private indexes and dependencies without wheels are refused.
- `poetry.lock` / `pdm.lock` are read for names, versions and markers only; a lock's per-group
  selection is not applied (every locked package is installed).
- Cached dependency environments accumulate (`~/.repro` on the host, `repro-env-*` volumes);
  pruning arrives with `repro doctor`'s maintenance in Stage H.

## Dependencies added
None.

## Research notes
- PEP 518: without `[build-system]`, tools use the default `requires = ["setuptools"]`.
  https://peps.python.org/pep-0518/ **[V]** 2026-10-14
- uv's Docker guide: install uv by `COPY --from=ghcr.io/astral-sh/uv:<version> /uv /uvx /bin/`,
  pinning a version, or a digest for reproducible builds.
  https://docs.astral.sh/uv/guides/integration/docker/ **[V]** 2026-10-14
- PyPI's JSON API: `pyperclip` 1.9.0 has only a source distribution (uploaded 2024-06-18).
  https://pypi.org/pypi/pyperclip/1.9.0/json **[V]** 2026-10-14
- Measured here: uv 0.13.0 cannot initialise a cache mounted read-only (`EROFS`), and hatchling
  1.25.0's `get_requires_for_build_editable` returns `editables~=0.3` (its `build.py`).
