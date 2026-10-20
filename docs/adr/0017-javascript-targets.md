# ADR-0017: JavaScript and TypeScript targets

- **Status:** accepted by the owner (2026-10-19). Phase 1 is built (K01); phases 2 to 4 are
  K06, K07 and K08. They add a Node.js runtime to the sandbox image and a language field to
  the event schema's core, which this acceptance approves.
- **Date:** 2026-10-18
- **Phase:** K01

## Context
Repro reproduces Python changes: snapshots, provisioning with uv, pytest with Repro's plugin,
a `sys.monitoring` tracer, griffe and grimp for symbols and imports. Agent-written changes are
just as common in JavaScript and TypeScript, where the test runners are Vitest and Jest. The
roadmap's K01 asks for those targets and notes they need "a V8-side tracer design".

What the platform offers, read on 2026-10-18:
- **Vitest's JSON reporter** "generates a report of the test results in a JSON format
  compatible with Jest's `--json` option" [V vitest.dev/guide/reporters]. Per test it gives
  the file, `fullName`, `ancestorTitles` and `status` (seen in K01's run of Vitest 5.0.4).
- **Node's module customization hooks.** `module.registerHooks()` takes synchronous `resolve`
  and `load` hooks, and `load` may return different source for a module (the docs' example
  rewrites it) [V nodejs.org/api/module.html]. Its stability is 1.2, release candidate. The
  asynchronous `module.register()` is deprecated.
- **V8's precise coverage**, through the inspector protocol:
  - `Profiler.startPreciseCoverage` (with `callCount` and `detailed`) "resets execution
    counters";
  - `Profiler.takePreciseCoverage` "collect[s] coverage data for the current isolate, and
    resets execution counters" [V ChromeDevTools/devtools-protocol, `js_protocol.json`].

  Taking it between tests gives each test's executed functions.

## Decision
JavaScript and TypeScript targets in four phases, each usable on its own:

1. **Outcomes (built, K01).** `repro.jsts`, and `repro js-run`:
   - a Vitest or Jest project with a lockfile;
   - dependencies installed with lifecycle scripts off, so no code runs while the network is
     reachable (the D03 rule);
   - the suite run on base and on head in the process sandbox, read from the runner's JSON
     report and compared test by test.

   It makes no card; it says what is missing.
2. **The test → function map (built, K06).** A setup file (Vitest `setupFiles`, Jest
   `setupFilesAfterEnv`)
   opens an in-process inspector session, starts precise coverage, and takes it after each
   test. Functions with a count above zero are what the test ran, by file and range. This is
   the map that selection (D06) needs, with the same rule: a changed function selects the
   tests that ran it.

   As built (K06), functions are known by file and *name*, not range. V8 reports ranges in
   the code the runner executes, which Vite and Babel have rewritten (`add`, at offset 0 in
   its source, was at 507 in what Vitest ran). Changed lines are attributed to named functions
   by a conservative scanner, and code in no named function selects the tests that loaded its
   file.
3. **Function-level traces (built, K07).** A synchronous `load` hook rewrites the modules
   that hold changed functions, wrapping each changed function to record its arguments,
   result or exception with an encoder ported from `repro_encode`. The same plan is used on
   base and on head. TypeScript is handled where the runner already compiles it (Vitest
   through Vite, Jest through its transform): the hook sees JavaScript.

   As built (K07), there is no Node `load` hook: neither runner loads the project's modules
   through Node's loader. Vitest evaluates what Vite transformed, and Jest evaluates modules
   in its own `vm` contexts. Each runner's own transform point is used instead.
   - **Vitest:** a Vite plugin, last of the transforms, added by the wrapper config. It wraps
     the changed functions in place, so calls from inside the module are traced.
   - **Jest:** the setup file mocks each changed module by its own exports, wrapped. Only
     calls through a module's exports are traced, and the summary says so.

   The encoder hashes with SHA-256 cut to 128 bits, not BLAKE2b-128, which Node's `crypto`
   does not offer at that length. JavaScript runs are only ever compared with each other.
   The calls are Python's records, so E03's comparison reads them: base twice (the second
   shuffled), then head.
4. **The card.** The event schema gains the target's language. Symbols and changes come from
   the TypeScript compiler API (which also reads JavaScript); the API diff reads exported
   declarations. Isolation is L3 in a container with Node (`sandbox_image`, J04), and Node's
   network use is cut off there. Repro's L1 guard is a Python audit hook and does not see Node.

## Consequences
- Phase 1 runs on the host's Node in the process sandbox (L2). A Node process's network
  attempts are not detected there, and the output says so.
- Phases 2 and 3 run Repro's code inside the target's runner, as the pytest plugin does for
  Python. Their correctness depends on the runner's hooks, which differ between Vitest and
  Jest. Each needs its own fixture suite (as D04 did for pytest).
- Phase 4 changes the event schema's core (a language for the run). CLAUDE.md requires the
  owner's approval for that.

## Alternatives considered
- **Istanbul-style instrumentation of every file** (coverage counters inserted at build). It
  is heavier than V8's own coverage, and it changes every module rather than only those with a
  changed function.
- **Running `node --cpu-prof`.** A sampling profile, not exact: a test that runs a function
  briefly can miss it. Selection needs exact membership.
