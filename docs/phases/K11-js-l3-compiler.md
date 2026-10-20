# K11 — JavaScript: L3 and the compiler's view

| | |
|---|---|
| **Stage** | K — Expansion |
| **Status** | done |
| **Depends on** | K08 |
| **Branch / PR** | `phase/K11-js-l3-compiler` · [#110](https://github.com/DuhItzAniket/Repro/pull/110) |
| **Started / finished** | 2026-10-20 / 2026-10-20 |

## Objective
ADR-0017's phase 4, second part, after the owner split it on 2026-10-20 (K08 was the card).
Four pieces:
- JavaScript tests in a container with Node and no network (L3);
- the public API diff, from the TypeScript compiler API;
- edited tests' assertions, from the same compiler;
- base's version of an edited test, run against head's code.

## Scope
- **The container** (`sandbox/image/node.Dockerfile`, `sandbox.image.node_image`).
  - The image is the official Node 22 bookworm-slim, pinned by its index digest (read with
    `docker buildx imagetools inspect`, 2026-10-20).
  - pnpm 10.34.7 and Yarn 1.22.22 come through Corepack 0.36.0, each pinned by version and by
    its tarball's SHA-512 (the registry's integrity).
  - Under `auto`, a JavaScript run takes the container when Docker answers, as a Python run
    does; L4 under gVisor.
  - The install has a container of its own (`jsts.install_in_container`), the only one with
    the network.
  - Node's version and the installed packages are read in a sandboxed run with no network.
  - The tests run through a `Tree` (`HostTree` at L2, `VolumeTree` at L3), so test IDs are the
    same on both.
- **Installs that run no project code.** `--ignore-scripts` is not enough: pnpm runs
  `.pnpmfile.cjs`, and Yarn 1 runs `.yarnrc`'s `yarn-path`. `--ignore-pnpmfile` and
  `YARN_IGNORE_PATH=1` are passed on the host and in containers (THREAT_MODEL T5).
- **The network at L3.** It is enforced, but Node does not load Repro's Python audit hook.
  `no_network` therefore passes on enforcement alone, and its message says the attempts are not
  seen.
- **The compiler** (`analysis/typescript.py`, `analysis/_ts_worker.cjs`).
  - It is `typescript` 6.0.3: fetched once from the npm registry, its sha512 checked, unpacked
    by Repro with tarfile's `data` filter. No package manager runs.
  - The package's name, version and licence (Apache-2.0) are checked.
  - It runs on the host's Node, never from the target's `node_modules`, and reads only the
    scratch trees and its own `lib`.
- **The API diff** (`analysis/jsapi.py`).
  - Entry points come from `package.json` (`exports` in all its forms, `types`, `typings`,
    `module`, `main`), mapped back to their sources through `tsconfig.json`.
  - Each export is compared: functions, classes, interfaces, type aliases, constants, enums.
  - Breaks reuse Python's `ApiBreak` (`api_diff` evidence, `diff.api`, warn). The schema
    gained `parameter_changed_type`.
- **Assertions** (`jsassert.py`): `expect(...)` chains and `assert` calls from the syntax tree
  of each edited test's own lines. The findings are `assertion_removed`, `assertion_weakened`
  and `raises_widened`.
- **Base on head** (`js_stage.base_copy`).
  - Base's version of an edited test file is written beside head's
    (`m.test.ts` → `m.repro-base.test.ts`) and run there.
  - A failure where base passed is `base_test_fails_on_head`, which flags whatever the claims
    say.
  - A copy that would replace one of the project's files is not run, and is a missing item.

## Out of scope
- Timing JavaScript tests, and generated probes: still Python's.
- Yarn 2+ (Berry): its `.yarnrc.yml` plugins can run code, and the install flags are Yarn 1's.
- The API diff does not handle wildcard subpaths, an `outDir` set in an extended package's
  tsconfig, bundler-only builds or `references`: each is a missing item. It does not compare
  class heritage, index or construct signatures, or generic type parameters.

## Acceptance criteria
- [x] AC1: a JavaScript change runs at L3 with no network, its test IDs the same as at L2,
  and its card says L3.
- [x] AC2: an install runs none of the project's code: no lifecycle script, no pnpmfile, no
  `yarn-path`.
- [x] AC3: the public API's breaks are `diff.api` evidence; without Node or the compiler, the
  API is a missing item, never a pass.
- [x] AC4: a weakened, widened or removed assertion in an edited test is named.
- [x] AC5: a test edited to fit a regression is caught by its base version on head.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_js_container.py`: a Vitest change through the pipeline in containers (FLAGGED, L3, `fetch` refused); test IDs equal on both sandboxes |
| AC2 | `test_js_container.py::test_the_hosts_install_runs_none_of_the_projects_code_either`, `::test_an_install_in_a_container_runs_none_of_the_projects_code` |
| AC3 | `test_jsapi.py`: every breakage kind, the schema, CommonJS, `.d.ts`, unresolvable entries; `test_typescript.py`: integrity, refusals, no Node |
| AC4 | `test_jsassert.py`; `test_js_stage.py::test_the_public_api_and_a_weakened_assertion_by_typescript` |
| AC5 | `test_js_stage.py::test_a_test_edited_to_fit_a_regression_is_caught_by_its_base_version` |

---
*Filled in at the end of the phase:*

## What shipped
- **Engine:** `sandbox/image/node.Dockerfile` and `node_image()`; `jsts`'s install in a
  container and its `Tree`s; `analysis/typescript.py`, `analysis/_ts_worker.cjs`,
  `analysis/jsapi.py` and `jsassert.py`; base on head in `js_stage`.
- **Schema:** the breakage `parameter_changed_type`.
- **Tests:** `test_js_container.py` (with a real npm lockfile fixture), `test_typescript.py`,
  `test_jsapi.py`, `test_jsassert.py`, and additions to `test_js_stage.py`.

## Evidence
All on Windows 11 with Docker Desktop 29.8.2, 2026-10-20.
- **Real container runs:**
  - a Vitest change at L3 took 34.9 s end to end, 3.4 to 4.1 s to install a side, and the
    card was FLAGGED, at L3, on Node 22.23.3;
  - a Jest 30.5.2 change took 42.1 s (scratch project, not committed);
  - `label`'s changed result was found through the traces in the container, and a test's
    `fetch` was refused on each side.
- **Installs that run project code, before and after the fix**, in the image:
  - a `.pnpmfile.cjs` wrote its marker file, and so did a `.yarnrc` `yarn-path`;
  - after the fix, neither did, and both installed.
- **The compiler:**
  - `npm view typescript@6.0.3 dist.integrity` matches the downloaded tarball's sha512, and
    its sha1 matches the registry's shasum;
  - the licence is Apache-2.0, from the package itself;
  - it has no install scripts and no dependencies;
  - 7.0.2 is the native port, with no `lib/typescript.js`.
- **The API diff on real libraries:**
  - p-limit v3.1.0 → v6.0.0 reports `export=` and `Limit` removed;
  - v6.2.0 → v7.0.0 reports no break;
  - ky's entry cannot be resolved (its `outDir` is in a dependency's tsconfig), and is a
    missing item.
- **Suites:** the JavaScript, container, TypeScript and invariants tests pass (227, Docker
  included). The full suite is in CI.

## Deviations from spec
- ADR-0017 named no compiler version. 6.0.3 is pinned because 7.x has no JavaScript API in its
  package.
- `no_network` at L3 passes on enforcement, not on detection: Node does not load the Python
  audit hook.

## Known gaps
- Yarn 2+ is not handled. pnpm config dependencies beyond `.pnpmfile.cjs` were not tested.
- A project's `.npmrc` can point the install at another registry, at L2 as at L3.
- The compiler's view of CommonJS relies on `sourceFile.symbol`, which is not in the public
  typings: re-check it on any version bump.
- The image's cold build was not timed end to end. Its first trial's main step took 71.2 s,
  with an earlier version of the file.

## Dependencies added
- `typescript` 6.0.3 (Apache-2.0), fetched at run time into Repro's data directory, checked by
  sha512; not a Python dependency.
- The Node.js image (`node:22-bookworm-slim`, by digest), with pnpm 10.34.7 and Yarn 1.22.22
  through Corepack, by SHA-512.
