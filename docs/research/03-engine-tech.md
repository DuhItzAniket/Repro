<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Research 3: Engine technology for Repro

Accessed 2026-10-13. Scope: the Python engine. It takes a Python + pytest repo and a pair of refs. It builds worktrees and venvs, runs static analysis to find the blast radius, selects tests, runs them on base and head with a `sys.monitoring` tracer under network-off isolation, then diffs behaviour, API, dependencies and performance.

## Tagging legend

- **[V]** The fact was checked on a primary source I fetched: official docs, a PEP, the project repo or source file, or the PyPI/GitHub JSON APIs.
- **[V-local]** The fact was checked by running a command on a Windows 11 x64 development machine: a CLI's `--help`, a version query, or a small experiment.
- **[S]** The fact comes from a search snippet or a secondary source. I did not read the primary source.
- **[U]** Unverified. Treat it as a hypothesis to test.
- **[A]** My own analysis, inference or recommendation. It is not a sourced fact.

Note on method: the shared WebSearch budget ran out partway through. I did the remaining checks by fetching known primary URLs directly. That is why a few items stay [U].

### Development-machine notes

Some facts below were checked by running commands on a Windows 11 x64 development machine (tag `[V-local]`). Machine-specific details (hardware, installed versions) were removed before publication. Practical consequences for contributors are in `docs/IMPLEMENTATION_PLAN.md` (toolchain baseline).

---

## 1. PEP 669 / `sys.monitoring`

### 1.1 API surface

`sys.monitoring` is a namespace inside `sys`, added in 3.12 [V].

- **Tool IDs.** These are integers 0–5. Predefined: `DEBUGGER_ID=0`, `COVERAGE_ID=1`, `PROFILER_ID=2`, `OPTIMIZER_ID=5`. IDs 3 and 4 are unnamed [V].
  - Tools tell each other apart only by ID. "Tools cannot monitor each other" [V].
  - Using a predefined ID is not mandatory. Nothing stops a tool from using an ID that is already taken. Tools are only encouraged to cooperate [V, PEP 669].
- **ID management functions** [V]:
  - `use_tool_id(id, name)` raises `ValueError` if the ID is taken.
  - `get_tool(id)` returns the tool's name or `None`.
  - `free_tool_id(id)` releases the ID.
  - `clear_tool_id(id)` was **added in 3.14**.
  - Since 3.14, `free_tool_id` calls `clear_tool_id` first. **Before 3.14 it did not disable that ID's global or local events, nor unregister its callbacks.**
- **Turning events on and off** [V]:
  - `set_events(id, mask)` / `get_events(id)` work globally.
  - `set_local_events(id, code, mask)` / `get_local_events(id, code)` work per code object.
  - Local events add to global events. They do not mask them. An event enabled both ways fires once.
  - PEP 669 says event setting is per-interpreter, not per-thread [V].
- **Local events** (can be disabled per code location) [V]: `PY_START, PY_RESUME, PY_RETURN, PY_YIELD, CALL, LINE, INSTRUCTION, JUMP, BRANCH_LEFT, BRANCH_RIGHT, STOP_ITERATION`. In 3.12/3.13 the list had `BRANCH` instead of LEFT/RIGHT.
- **Other events** (not tied to a location): `PY_THROW, PY_UNWIND, RAISE, EXCEPTION_HANDLED, RERAISE` [V].
  - **Changed in 3.15:** "Other events can now be turned on and disabled on a per code object basis". Returning `DISABLE` from one of them now disables it for the whole code object. In earlier versions that raised `ValueError` [V, 3.15 docs + What's New].
  - Implication [A]: on 3.12–3.14, `PY_UNWIND`/`RAISE` can only be set globally. A tracer that wants exception exits must filter by code object inside the callback.
- **Ancillary events:** `C_RETURN, C_RAISE` fire only when `CALL` is monitored [V].
- **Callback signatures** (no frame argument is passed) [V]:
  - `PY_START`, `PY_RESUME`: `(code, instruction_offset)`
  - `PY_RETURN`, `PY_YIELD`: `(code, instruction_offset, retval)`
  - `CALL`, `C_RAISE`, `C_RETURN`: `(code, instruction_offset, callable, arg0)`. `arg0` is `MISSING` when there are no arguments.
  - `RAISE`, `RERAISE`, `EXCEPTION_HANDLED`, `PY_UNWIND`, `PY_THROW`, `STOP_ITERATION`: `(code, instruction_offset, exception)`
  - `LINE`: `(code, line_number)`
  - `BRANCH_*`, `JUMP`: `(code, offset, destination_offset)`
- **`DISABLE`.** Returning `sys.monitoring.DISABLE` from a local-event callback disables that event at that code location only [V].
  - `restart_events()` re-enables everything disabled this way, **for all tools** [V].
  - PEP 669 says tools must therefore cope with events they had disabled coming back [V].
- **Re-entrancy.** "Events are suspended inside a tool's own callbacks for that tool, but other tools still see them" [V, PEP 669]. Implication [A]: user code that Repro's encoder triggers (`__eq__`, `__repr__`) does not recurse into Repro's own callbacks.
- **Coexistence with `sys.settrace` / `sys.setprofile`.** They act as tools 6 and 7, so they run alongside `sys.monitoring` tools [V, PEP 669].
- **`register_callback`** raises the audit event `sys.monitoring.register_callback` [V].

### 1.2 Version differences that matter to Repro

| Version | Relevant changes |
|---|---|
| 3.12 | `sys.monitoring` introduced. Only a `BRANCH` event. `free_tool_id` does **not** clear events or callbacks. `frame.f_locals` on function frames is a snapshot dict [V]. |
| 3.13 | No `sys.monitoring` API changes are documented on the 3.13 page [V]. PEP 667 makes `frame.f_locals` a **write-through `FrameLocalsProxy`** for optimized frames. Each access creates a new proxy [V]. This is safe for reading, but avoid writing through it [A]. The free-threaded build is experimental. |
| 3.14 | `BRANCH_LEFT`/`BRANCH_RIGHT` added and `BRANCH` deprecated. `clear_tool_id` added, and `free_tool_id` now clears [V]. **pdb uses the `sys.monitoring` backend for the pdb CLI and `breakpoint()`** [V]. coverage.py's `sysmon` core became the default on 3.14+ [V]. PEP 779: the free-threaded build is officially supported, with roughly a 5–10% single-thread penalty [V]. PEP 768 adds `sys.remote_exec`. It can be disabled with `PYTHON_DISABLE_REMOTE_DEBUG` / `-X disable-remote-debug` [V]. |
| 3.15 (released 2026-10-09 [V, PEP 790 + What's New]) | "Other" events (RAISE, PY_UNWIND, …) can now be set and disabled per code object [V]. New `profiling` package with `profiling.sampling` ("Tachyon"); its claim is "virtually zero overhead" [V]. Explicit `lazy` imports (PEP 810) [V]. UTF-8 mode is the default (PEP 686) [V]. `.start` files (PEP 829); `import` lines in `.pth` files are silently deprecated [V]. The free-threaded HOWTO says overhead is about 1% (macOS aarch64) to 8% (x86-64 Linux) on pyperformance [V]. |

Implications [A]:

- Pin **the same interpreter build** for base and head.
- Target the 3.12+ floor, and special-case 3.15+ to use per-code `PY_UNWIND`.
- 3.15 was released 4 days ago, so many dependencies will lack 3.15 wheels. **Do not let uv's new default (3.15, see §7) choose the target Python.**

### 1.3 Overhead: what is known and what is not

- PEP 669's expectations [V]:
  - With no events active, a 1–2% speedup versus 3.11-style tracing support.
  - A small set of events should cost "orders of magnitude less" than `settrace`.
  - Heavy `LINE` instrumentation is better than `settrace`, but by less.
  - Coverage tools get cheap by returning `DISABLE`.
  - Per-code-object memory rises by about 40%–200%. The PEP's table is garbled, so check the original for exact figures.
  - **Changing the active event set in a long-running program "can be expensive… possibly hundreds of milliseconds"**. Set events early, before modules load.
- Coverage.py 7.4 (Dec 2023): Ned Batchelder expected sysmon to cut measurement overhead "often lower than 5%". That was an expectation; no benchmark was published [V]. Branch coverage only got fast on 3.14, via `BRANCH_LEFT/RIGHT` [V].
- SlipCover (a `sys.monitoring`-based coverage tool, Apache-2.0, `slipcover 1.1.0`, 2026-08-13) reports 1.1x–3.4x speedups over coverage.py on CPython 3.10.5. Those numbers predate its sysmon backend [V].
- FOSDEM 2024 slides on the 3.12 monitoring API: a snippet gives multipliers of 3.5x / 1.2x / 2.7x for settrace vs PY_START vs PY_START+LINE. **The PDF could not be read, so the pairing of numbers to configurations is unconfirmed** [S].
- I found **no authoritative per-callback cost (ns/call) for PY_START + PY_RETURN with Python-level callbacks** [U]. **Repro must benchmark this itself** [A]. Suggested measurements:
  - recursive fib with no tool
  - PY_START + DISABLE
  - PY_START + PY_RETURN local events on one hot function, with arg encoding
  - the same on a real test suite

### 1.4 Interactions with coverage.py, debuggers, other tools

- **coverage.py tool-ID handling.**
  - coverage.py's sysmon tracer starts at `COVERAGE_ID` and **walks upward to 5** until `use_tool_id` succeeds. It raises "No sys.monitoring tool id is available" if none is free [V, `coverage/sysmon.py`].
  - Changelog 7.14.2: coverage "had assumed it could use the COVERAGE_ID tool id… other tools might also assume they could use that id". It now searches [V].
  - `start()` calls `sys.monitoring.restart_events()`, which re-enables **every** tool's DISABLEd events [V, source].
  - `stop()` calls `set_events(id, 0)` then `free_tool_id`. **On 3.12/3.13 this leaves coverage's local events registered** [V, source + 3.12 doc].
  - Implication [A]: never reuse an ID another tool just freed on 3.12/3.13. Always filter callbacks by Repro's own code set.
- **pdb (3.14+).** It uses sys.monitoring for CLI and `breakpoint()` sessions [V]. I did not verify which ID it takes; probably `DEBUGGER_ID` [U]. Same for debugpy/pydevd on 3.12+ [U].
- **Recommendation [A].** Repro's tracer should try IDs in the order **4, 3, 2, 5**, and avoid 0 (debugger) and 1 (coverage). If none is free, emit an explicit `missing: behaviour-trace (no tool id)` item rather than failing silently. Avoid running Repro's tracer and coverage.py in the same process; use separate passes (see the design section).

### 1.5 Free-threaded builds

- CPython gh-116818 ("make settrace, setprofile and monitoring thread-safe in free-threaded builds", PR #116775) was closed as completed in April 2024 [V].
- Events are per-interpreter, so callbacks fire on every thread [V, PEP 669].
- "It is not safe to access `frame.f_locals` from a frame object if that frame is currently executing in another thread" [V, FT HOWTO]. Reading the **current thread's** callee frame inside its own callback is the safe pattern [A].
- coverage 7.8.1 fixed "a race condition when using sys.monitoring with free-threading Python" [V].
- Design implication [A]:
  - Use per-thread buffers (`threading.local`), and no unlocked shared dict mutation.
  - Treat free-threaded targets as "supported later" and record `python_build: ft` on the card.

### 1.6 Capturing arguments at PY_START and results at PY_RETURN

- **Frame on the stack.**
  - PY_START "occurs immediately after the call, the callee's frame will be on the stack". PY_RETURN and PY_YIELD likewise [V, 3.13 docs].
  - coverage.py gets the callee frame inside its PY_START callback with `inspect.currentframe().f_back` [V, source]. `sys._getframe(1)` is equivalent.
  - `sys._getframe` "raises an auditing event `sys._getframe`". It is a CPython implementation detail [V].
  - Implication [A]: if Repro also installs an audit hook (§6), every frame grab runs the hook, so keep the hook's fast path trivial.
- **Arguments** [A]:
  - Parameter names are `code.co_varnames[:n]`, where `n = co_argcount + co_kwonlyargcount + (CO_VARARGS?1:0) + (CO_VARKEYWORDS?1:0)`. Use the `inspect.CO_*` flags.
  - Read values from `frame.f_locals`. On 3.13+ that is a cheap proxy with a cached name→index map [V, PEP 667 implementation notes].
  - Read the arguments **at PY_START**, before the body mutates them.
- **Return value.** The PY_RETURN callback receives `retval` directly [V].
- **Exceptions.**
  - `PY_UNWIND` = "exit from a Python function during exception unwinding" and receives the exception [V]. Use it for "function raised X".
  - `RAISE` fires where the exception is raised [V], which is less useful for per-function outcomes.
  - On 3.12–3.14, `PY_UNWIND` is global-only (see 1.1). Its cost scales with how many exceptions propagate, not with call count [A].
- **Generators and coroutines** [A]:
  - PY_START fires once. Each resumption fires PY_RESUME/PY_YIELD, and STOP_ITERATION covers the artificial `StopIteration` [V].
  - Record yields as a bounded sequence.
  - Key in-flight records by `id(frame)`. A suspended generator keeps the same frame.
- **Keying code objects.** coverage keys by `id(code)` and **keeps every code object alive in a list** so IDs are not reused [V, source]. Repro should do the same [A].

### 1.7 Making observations hashable and deterministic: the hazards

Each item below was verified empirically on CPython 3.11.9 / Windows with `-I`, unless tagged otherwise.

- **String-set iteration order changes with `PYTHONHASHSEED`.** `{'apple','banana','cherry','date'}` listed in three different orders for seeds 0/1/2 [V-local]. The docs say str/bytes hashes are "salted" per process unless PYTHONHASHSEED is fixed. `0` disables randomization, and the valid range is [0, 4294967295] [V, cmdline docs].
- **Int hashing does not depend on the seed.** A frozenset of ints iterated identically across seeds [V-local]. It still depends on insertion history and table size [A].
- **Default `repr()` embeds an address.** `<__main__.Foo object at 0x0000017D6B008A50>` changed on every run even with a fixed seed, because of ASLR [V-local]. Never hash raw reprs.
- **Dicts preserve insertion order.** This is a language guarantee since 3.7 [V]. So "same dict, different insertion order" is a real but usually unimportant difference. Report it as `order-only` [A].
- **Floats.** `repr(float)` is the shortest round-tripping string "on most systems" since 3.1 [V]. `float.hex()` is the documented platform-independent exact form [V]. NaN, `-0.0` and `0.0` need explicit canonical tokens [A].
- **pickle.** No byte-stability guarantee is documented. It is **"not secure"**: unpickling can execute arbitrary code [V]. Never hash pickles, and never unpickle data that untrusted runs produced on the host [A].
- **Paths** [A]: base and head run from different worktree roots, and from Linux paths when containerized. Normalize the worktree root → `<ROOT>`, temp dirs → `<TMP>`, home → `<HOME>`, and `\` → `/`.
- **Observer effect** [A]: calling `repr`, `__eq__`, properties or `__iter__` runs user code, which may mutate state, consume iterators or be slow. The encoder must walk structure without calling user methods. See the design section.

---

## 2. coverage.py

- **Version.** `coverage 7.16.2` (2026-09-27), Apache-2.0, `requires_python >=3.10` [V]. The repo moved to `coveragepy/coveragepy` [V, GitHub API].
- **Cores** (`[run] core` setting, or `COVERAGE_CORE`; the setting was added in 7.9) [V]:
  - `ctrace`: a C `sys.settrace` function. It "was the default until Python 3.13".
  - `sysmon`: "Only available in Python 3.12+, and the default in Python 3.14+". It "does not yet support plugins, dynamic contexts, or some concurrency libraries" and "in Python 3.12 and 3.13, it does not support branch coverage".
  - `pytrace`: pure Python.
- **Conflicts.** If the requested core conflicts with other settings, another core is used and a warning is issued (7.11.3 behaviour) [V].
  - **7.15.3: "the sysmon core is incompatible with dynamic contexts". Contexts set through the API (as pytest-cov does) "were previously dropped silently", and now produce a warning** [V].
  - So per-test contexts mean the settrace-based `ctrace` core, on every Python version [V + A].
- **Dynamic contexts.**
  - `[run] dynamic_context = test_function` starts a new context for every function whose name starts with `test` [V].
  - pytest-cov's `--cov-context=test` sets the context for each pytest test (added in 2.8, needs coverage 5.0+) [V].
  - The data file is SQLite [V].
- **Query API** (`CoverageData`, all since 5.0) [V]:
  - `contexts_by_lineno(filename) -> dict[int, list[str]]`
  - `measured_contexts()`
  - `set_query_context(s)` (regex via `re.search`)
  - `lines()`, `arcs()`, `measured_files()`, `read()`
  - Only the add/set methods are documented as thread-safe.
- **pytest-cov.** Version `7.1.0` (2026-03-21), MIT [V].
  - 7.0.0 dropped `.pth`-based subprocess measurement. Use `[run] patch = subprocess` (a coverage `patch` setting added in 7.10) [V].
  - pytest-cov 7 requires coverage ≥ 7.10.6 [V].
  - coverage's `execv` patch is not available on Windows [V].
- **Performance.** There is no authoritative published overhead figure for `ctrace` + per-test contexts on 3.12+ [U]. sysmon is the fast path but cannot do per-test contexts [V]. This is the main reason **Repro should not depend on coverage.py for test selection**. See the design section [A].

## 3. Test selection (RTS) tools

| Tool | Status (verified) | How it works | Fit for Repro |
|---|---|---|---|
| **pytest-testmon** | `2.2.0` (2025-12-01), MIT. **Last repo push 2025-12-01**, so about 10 months idle. 42 open issues, about 1.0k stars [V]. Requires `coverage>=6,<8`, `pytest>=5,<10` [V]. | Splits source into blocks and stores a **checksum per block**. A test is affected when an executed block it depends on changes. "There is no heuristics involved", and its reliability is "pretty much the same as limits of coverage.py" [V, blog]. It runs coverage with `Coverage(...).switch_context(test_name)` (API dynamic contexts) [V, source], so per §2 it cannot use the sysmon core. It refuses to run with pytest-cov when branch coverage is on [V, source]. `.testmondata` is SQLite. There is a commercial hosted offering (testmon.net) [V]. | Its ideas (block checksums, environment keys) are worth borrowing. Embedding it is a poor choice: it selects tests by **head-vs-last-run state**, not base-vs-head, uses the slow coverage path, and is lightly maintained [A]. |
| **pytest-rts** (F-Secure) | `2.5.0`, 2021-05-17 [V]. | Builds a mapping DB with `pytest --cov --cov-context=test`, then selects tests from a git diff [V]. | This is exactly Repro's planned approach, which validates the idea, but the tool is unmaintained [A]. |
| **pytest-picked** | `0.5.1`, 2024-11-06 [V]. | Runs tests "related to the changed files" (file-level) [V]. | Too coarse [A]. |
| **pytest-incremental** | `0.6.0`, 2021 [V]. | An incremental runner based on the import graph [S]. | Dead [A]. |
| **tach** | `0.35.3` (2026-10-06). Repo now `tach-org/tach`, MIT, written in Rust [V]. | Enforces module boundaries and dependencies [V]. I did not verify whether it also has a test-impact command [U]. | Optional [A]. |

**Reuse vs build [A]:** build the selector. A function-level per-test map comes nearly for free from Repro's own `sys.monitoring` PY_START collector, with DISABLE on non-project code. Use `grimp` for import-time and module-level changes. Use coverage.py only as an optional line-level evidence pass.

## 4. Static analysis libraries

| Library | Version / date / licence | What it gives Repro | Caveats |
|---|---|---|---|
| **ast** (stdlib) | n/a | Symbol table, line spans (`lineno`/`end_lineno`), signatures | The baseline [A]. |
| **grimp** | `3.17` (2026-09-04), BSD-2-Clause. Repo `python-grimp/grimp`, active [V]. | Module-level import graph [V]: `build_graph(pkg, include_external_packages, exclude_type_checking_imports, cache_dir)`, `find_downstream_modules`, `find_upstream_modules`, `find_shortest_chain(s)`, `get_import_details` (with `line_number`, `is_lazy`), `chain_exists` [V]. Import parsing moved to Rust in 3.9, and scanning to Rust multithreading in 3.11 [V]. 3.16 added free-threaded 3.14+, Python 3.15 (lazy imports) and Windows ARM64; 3.17 handles explicit lazy imports [V]. Used by import-linter (`2.15`, BSD-2) [V]. | **Module-level only, not symbol-level** [V]. Dynamic imports are not mentioned [V], so assume they are missed [A]. Static, so it does not execute target code [A]. |
| **griffe** | `2.3.2` (2026-10-06), ISC. Active [V]. 2.0 (2026-02-09) split into `griffe`/`griffecli`/`griffelib` and removed old git helpers [V]. | API extraction plus **`griffe check`** breaking-change detection [V]. Python API: `load(...)` / `load_git(objspec, ref=, repo=, search_paths=, allow_inspection=True, force_inspection=False, ...)`, then `find_breaking_changes(old, new)`, which yields `Breakage` objects with `.explain()` / `.as_dict()` [V]. **BreakageKind:** PARAMETER_MOVED, PARAMETER_REMOVED, PARAMETER_CHANGED_KIND, PARAMETER_CHANGED_DEFAULT, PARAMETER_CHANGED_REQUIRED, PARAMETER_ADDED_REQUIRED, RETURN_CHANGED_TYPE, OBJECT_REMOVED, OBJECT_CHANGED_KIND, ATTRIBUTE_CHANGED_TYPE, ATTRIBUTE_CHANGED_VALUE, CLASS_REMOVED_BASE [V]. Output styles: oneline, verbose, markdown, github, azdo [V]. `load_git` builds a temp worktree [V]. | **Return-type and attribute-type compatibility are "not yet supported"** [V]. "Public" is decided by convention (leading underscore), so false positives or negatives are possible [V]. **`allow_inspection=True` by default lets griffe *import* a module when static visiting fails** [V]. For untrusted repos pass `allow_inspection=False` or run griffe in the sandbox [A]. Repro already has worktrees, so use `load(search_paths=[wt])` instead of `load_git` [A]. **This saves months: use it as the API-diff layer** [A]. |
| **LibCST** | `1.9.0` (2026-07-29). PyPI licence text says "All contributions towards LibCST are MIT"; GitHub shows NOASSERTION [V]. Check for PSF-licensed parser components [U]. | Lossless CST plus metadata [V]: `PositionProvider`, `QualifiedNameProvider` (names local to module), `FullyQualifiedNameProvider` (needs `FullRepoManager`), `ScopeProvider` (assignments and accesses), `ParentNodeProvider`, `TypeInferenceProvider` (needs a Pyre server and watchman) [V]. | ScopeProvider does not track attribute names (`a.b.c` → `a`), and string annotations are not treated as accesses [V]. Useful for precise changed-line → enclosing-def mapping and for codemods, but `ast` is enough for the MVP [A]. |
| **jedi** | `0.20.1` (2026-10-12), MIT [V]. | `Script.goto`, `infer`, `get_references(scope='project'/'file')`, `Project(added_sys_path=...)`, `create_environment(venv)` [V]. | It **executes the environment's Python binary** to introspect it [V]. Run it inside the sandbox for untrusted repos [A]. `fast_parser` is not thread-safe [V]. |
| **pyright** | `1.1.414` (2026-09-10), MIT [V]. | CLI: `--outputjson`, `--pythonpath`, `--venvpath`, `--threads`, `--verifytypes` [V]. **No call-graph output from the CLI.** The language server offers "call hierarchy… places where a function is called" and Find References [V]. | Node-based. The PyPI wrapper's Node bootstrap is unverified [U]. Driving the LSP is heavy. Use it later for reverse call edges [A]. Alternatives with versions verified: `basedpyright 1.40.2`, `ty 0.0.86` (Rust, Astral, pre-1.0), `pyrefly 1.3.2` (Meta), `mypy 2.4.0` [V]. ty/pyrefly licences unverified [U]. |
| **pydeps** | `3.0.9` (2026-10-01), BSD-2-Clause [V]. | Import graph found from "import-opcodes in python bytecodes". It only finds modules reachable by the import machinery [V]. Needs Graphviz to render [V]. | Overlaps with grimp and is less suitable [A]. |

## 5. Behavioural equivalence and mutation tools

- **CrossHair** (`crosshair-tool 0.0.111`, 2026-09-28; licence NOASSERTION on GitHub, MIT on PyPI) [V].
  - `crosshair diffbehavior mod.f1 mod.f2` uses an SMT solver to search for inputs where two functions differ [V].
  - Options: `--exception_equivalence {ALL,SAME_TYPE,TYPE_AND_MESSAGE}`, `--max_uninteresting_iterations` (default 5), `--per_path_timeout`, `--per_condition_timeout`, `--unblock` [V].
  - Arguments need type annotations and must be deep-copyable and equality-comparable. CPython only. Deterministic code only. It "likely won't be able to detect differences in complex code". Finding no difference is not proof of equivalence [V].
  - To compare git refs, the docs suggest `git worktree add --detach clean` and comparing `foo.cut` with `clean.foo.cut` [V].
  - **"CrossHair will actually run your code"**, so it must run in the sandbox [V].
  - Fit [A]: an optional "deep check" for small pure functions in the blast radius. Its output (a counterexample input) is excellent evidence.
- **Hypothesis** (`6.169.0`, 2026-10-11, MPL-2.0) [V].
  - Ghostwriter: `hypothesis write --equivalent / --errors-equivalent / --roundtrip / --idempotent / --binary-op` [V].
  - `ghostwriter.equivalent(*funcs, allow_same_errors=False, ...)` checks that the functions return equal values. Only common parameters receive the same arguments [V].
  - It needs `black`. Unannotated parameters get placeholders. "Meant as a starting point" [V].
  - Fit [A]: generate inputs on the host. Then **replay the same serialized inputs** in the base and head sandboxes, each in its own process to avoid module name clashes, and compare canonical result hashes. Use only JSON-able inputs; never pickles across the trust boundary.
- **mutmut** (`3.8.0`, 2026-09-12, BSD-3) [V].
  - "Mutmut must be run on a system with `fork` support… on windows, you must run inside WSL". Both `fork` and `forkserver` modes are POSIX-only [V].
  - Has a `mutate_only_covered_lines` option [V].
- **cosmic-ray** (`8.7.0`, 2026-08-09, MIT) [V].
  - Uses a session SQLite DB, Operator classes, and a `local` distributor that mutates the code copy **in place**, or `http` distributed workers [V]. Windows support is unverified [U].
- **Use for Repro [A]:**
  1. **Seeding a benchmark.** Apply mutation operators to real repos to create synthetic "agent PRs" with known behaviour changes (ground truth = mutant). Measure Repro's recall: did the card flag it? Measure precision with refactor-only or equivalent mutants.
  2. **Strengthening evidence.** For a flagged function, run mutants of the *head* function against the selected tests to report whether the tests would even notice a change there. That is a test-adequacy signal on the card.
  - Both run inside the sandbox. mutmut needs Linux (container or WSL).

## 6. Network blocking and isolation

### 6.1 In-process guards

- **pytest-socket** (`0.8.1`, 2026-08-19, MIT, active) [V]. Mechanism from source [V]:
  - Saves `_true_socket = socket.socket`, `_true_connect`, `_true_getaddrinfo`, `_true_gethostbyname`.
  - `disable_socket()` replaces the **module attribute** `socket.socket` with a `GuardedSocket` subclass whose `__new__` raises (unless AF_UNIX is allowed), and replaces `socket.getaddrinfo`.
  - `--allow-hosts` patches `socket.socket.connect`.
  - Flags: `--disable-socket`, `--force-enable-socket`, `--allow-unix-socket`, `--allow-hosts`. Markers: `enable_socket`, `allow_hosts`. Fixture: `socket_enabled` [V].
  - Documented caveat: a socket opened by a higher-scoped fixture before disabling is not blocked [V].
- **Bypassability [A].** It is a guard against accidents, not a security boundary. Trivial bypasses:
  - `import _socket; _socket.socket(...)`
  - references captured before patching (`from socket import socket`)
  - C extensions that call the OS directly (libcurl, grpc core, DB drivers)
  - `subprocess`/`os.system` (curl, another Python)
  - `ctypes` calls to the platform's socket functions
  - undoing the patch (`socket.socket = original`)
- **Audit hooks (PEP 578).** `sys.addaudithook` docs [V]:
  - Hooks are "not suitable for implementing a 'sandbox'. In particular, malicious code can trivially disable or bypass hooks added using this function". Security hooks must be added via the C API before init, with `ctypes` removed.
  - If an existing hook raises a `RuntimeError` subclass, the new hook is silently not added.
  - Useful events, all present in the table [V]: `socket.connect(self,address)`, `socket.getaddrinfo`, `socket.__new__`, `socket.sendto`, `socket.bind`, `subprocess.Popen(executable,args,cwd,env)`, `os.system`, `os.exec`, `os.posix_spawn`, `os.spawn`, `os.startfile`, `_winapi.CreateProcess`, `ctypes.dlopen`, `ctypes.call_function`, `open(path,mode,flags)`, `os.remove`, `shutil.rmtree`, `http.client.connect`, `urllib.Request`, `winreg.OpenKey`, `sys.addaudithook`, `cpython._PySys_ClearAuditHooks`, `sys._getframe`.
  - Use them as a **detection and evidence layer**. Example: "test X tried to connect to 1.2.3.4:443" or "spawned `curl`" becomes a card item [A].
- **Honest posture [A].** An in-process socket guard plus audit hook stops accidental network use by honest tests and records attempts. It does **nothing** against code that wants to escape. Network-off can only be *claimed* when an OS boundary enforces it (namespace, container or VM). Otherwise the card must say `network: detected-only` (Ground Rule 3: never silently).

### 6.2 OS-level isolation options

| Option | Isolation | Windows (Home edition dev machine) | Linux CI | Notes |
|---|---|---|---|---|
| **Docker Desktop (WSL2 backend)** | Containers in a WSL2 VM. `--network none` leaves "only the loopback device" [V]. | Docker's page lists Win 11 Enterprise/Pro/Education 23H2+ for WSL2 and says Home/Education "only allow you to run Linux containers" [V]. Observed working on a Windows 11 Home machine via the WSL2 backend [V-local]. Licence: free for small business (<250 employees AND <$10M revenue), personal use, education and non-commercial OSS; others need a paid plan [V]. | Docker Engine is native. | **Recommended default sandbox on both** [A]. Bind mounts from the Windows FS into Linux are slow. Microsoft recommends keeping files on the Linux FS for Linux tooling [V, WSL docs]. Copy snapshots into a volume instead [A]. |
| **Podman** | Rootless or rootful containers [V]. | On Windows it runs in a "podman machine" on WSL2 or Hyper-V. **Hyper-V is not available on Home** [V]. Needs Windows 11 [V]. | Native. | An alternative CLI. Repo moved to `podman-container-tools/podman` [V]. |
| **gVisor (runsc)** | User-space kernel. Docker runtime via `runsc install` + `--runtime=runsc` [V]. | Not supported natively. Feasibility inside WSL2 Docker Engine is unverified [U]. | Linux 5.6+, x86_64/ARM64 [V]. | **Best hardening for Linux CI** [A]. |
| **Firecracker** | microVM | No | Needs `/dev/kvm` (KVM). x86_64/aarch64 Linux [V]. | Via E2B Embed (self-hosted) [V]. |
| **bubblewrap / nsjail** | Linux namespaces. nsjail adds seccomp-bpf (Kafel), cgroups, and network-namespace isolation [V]. | No (Linux only) [V]. | Yes | Lightweight per-process sandbox without a daemon [A]. |
| **Windows Sandbox** | Hypervisor-based disposable VM. Networking is on by default and can be disabled in the `.wsb` file [V]. | **Not supported on Windows Home** (Pro/Enterprise/Education only) [V]. **"Doesn't allow multiple instances to run simultaneously"** [V]. | n/a | Unusable here, and serial anyway [A]. |
| **Windows Job Objects** | Process-group limits (working set, CPU rate, process count, UI), accounting, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Child processes inherit the job by default [V]. | Yes, all editions [A]. | n/a | **No network or filesystem isolation** [A, from the documented feature set]. Children created via `Win32_Process.Create` (WMI) are **not** associated with the job [V], which is an escape route. Breakaway flags control inheritance [V]. Use it for timeouts and cleanup, not for security [A]. |
| **AppContainer** | Credential, device, file, **network**, process and window isolation; "granular access can be granted for Internet access, Intranet access, and acting as a server" [V]. | Windows feature [V]. Wrapping arbitrary Python/pytest in an AppContainer from Python is unverified [U]. | n/a | A possible future native-Windows layer. It is research work [A]. |
| **Plain WSL2** (no container) | **Not a sandbox.** Linux processes can launch Windows `.exe`s that "run as the active Windows user", and `C:\` is mounted at `/mnt/c` [V]. | n/a | n/a | Do not use bare WSL as an isolation layer [A]. |
| **E2B** (hosted or self-hosted) | One **Firecracker microVM** per sandbox, with a per-sandbox nftables egress firewall and domain allow/deny lists [V, `e2b-dev/infra`]. Self-hostable on one Linux+KVM host ("E2B Embed"), or via Terraform for GCP/AWS/Azure [V]. Python SDK: `Sandbox.create()`, `sandbox.commands.run()` [V]. | Client works anywhere [A]. | Yes | Strongest turnkey option. Sends code to a third party unless self-hosted [A]. |
| **Modal Sandboxes** | **gVisor by default**, with an optional VM runtime. Default lifetime 5 min, `timeout` up to 24 h, `idle_timeout` [V]. | Client only [A]. | Yes | Hosted only [A]. |
| **Daytona** | **The OSS repo is archived. "As of June 2026, Daytona's core development has moved to a private codebase"** [V]. | n/a | n/a | Avoid as a dependency [A]. |

Note: the E2B docs landing page contained text addressed to AI agents (telling them to query an MCP server). It was ignored and not acted on.

### 6.3 Layered design (detail in the design section)

- **L0** (always): separate processes and a fixed env.
- **L1** (always): in-process guard plus audit-hook **detection**.
- **L2** (always): Job Object (Windows) or cgroups/ulimits, plus timeouts.
- **L3** (default when Docker exists): Linux container with `--network none`, read-only root, no capabilities.
- **L4** (Linux CI, high assurance): gVisor or Firecracker (E2B Embed).

The card records the highest layer actually achieved [A].

## 7. uv

- **Version.** `uv 0.13.0` (2026-10-09), MIT OR Apache-2.0 [V]. Recent changes [V]:
  - **0.13.0 makes Python 3.15 the default stable version**.
  - Stricter tar handling (`UV_LEGACY_TAR_BACKEND=1` restores the old backend).
  - Cache format changes, so expect re-downloads.
  - **0.12.18 was a security release fixing path traversal during wheel installation on Windows (GHSA-2cv4-cqwr-gwf7)**. Any uv older than 0.12.18 predates it, so **upgrade before running untrusted installs** [V + A].
- **Link mode.** "Defaults to `clone` (Copy-on-Write) on macOS and Linux, and `hardlink` on Windows" [V, docs + V-local `--help`].
  - Values: clone, copy, hardlink, symlink. Symlink is discouraged [V-local].
  - The cache must be on the same filesystem as the venv, or uv "will not be able to link files" and falls back to copying [V].
  - Default cache on Windows: `%LOCALAPPDATA%\uv\cache` [V].
  - Concurrency: "safe to run multiple uv commands concurrently, even against the same virtual environment". The cache supports concurrent readers and writers [V].
  - `uv cache prune --ci` [V].
- **Untrusted-code caveat [A].** With `hardlink`, a venv file and the cache entry are the **same file**. Untrusted code that writes *in place* into its site-packages could therefore corrupt the shared cache for later runs. Mitigations:
  - `--link-mode copy` for sandboxed venvs, or a per-trust-domain cache, or a read-only cache mount inside the container plus `copy`.
  - Windows `clone` needs ReFS block cloning. Dev Drive supports block cloning on Win 11 24H2+ [V]. Whether uv's `clone` works on ReFS is unverified [U].
- **Commands** [V unless noted]:
  - `uv venv` has `--seed`, `--relocatable`, `--link-mode`, `--allow-existing`, `--system-site-packages` [V-local].
  - `uv python install`. `python-downloads = automatic|manual|never` [V].
  - `uv sync`:
    - `--locked` errors if the lockfile is outdated. `--frozen` uses it without checking.
    - `uv lock --check` is the explicit check.
    - `--no-install-project`, `--all-extras`, `--group/--all-groups`.
    - Exact sync by default (removes extraneous packages) [V].
  - `UV_PROJECT_ENVIRONMENT` sets the venv path for a project [V]. Also `UV_OFFLINE`, `UV_LINK_MODE`, `UV_CACHE_DIR`, `UV_NO_CACHE`, `UV_FROZEN`, `UV_LOCKED`, `UV_PYTHON`, `UV_PYTHON_DOWNLOADS`, `UV_COMPILE_BYTECODE`, `UV_EXCLUDE_NEWER`, `UV_CONCURRENT_INSTALLS` [V].
  - `--no-build` fails any operation that would build an sdist [V]. Building sdists runs untrusted build code [A].
  - `exclude-newer` limits candidates to those "uploaded prior to the given date" [V]. Use it to make non-locked resolutions reproducible [A].
- **`uv.lock` format** (observed in a real lockfile) [V]:
  - Top level: `version = 1`, `revision = N`, `requires-python`, `resolution-markers = [...]`.
  - `[[package]]` entries carry `name`, `version`, `source = { registry = ... }`, `dependencies = [{ name, marker }]`, `sdist = { url, hash = "sha256:…", size, upload-time }`, `wheels = [...]`.
  - The lock is **universal and portable across platforms** [V]. The schema version sits in `version`; a newer schema is rejected; patch releases within a minor keep compatibility; `revision` covers backward-compatible changes [V].
  - Export: `uv export --format requirements.txt | pylock.toml` (PEP 751) and CycloneDX [V].
- **Other project types** [V-local for formats]:
  - `uv pip install -r` accepts `requirements.txt`, `.py` with inline metadata, `pylock.toml`, `pyproject.toml`, `setup.py` and `setup.cfg`.
  - `uv pip list --format json -p <python>` and `uv pip freeze` (with `--strict`) list installed packages.
  - Poetry/PDM projects [A]: `uv pip install -e .` (or `.[test]`) works through their PEP 517 backends. That builds the project with untrusted backend code inside the sandbox. `poetry.lock`/`pdm.lock` are TOML and can be parsed for the dependency diff, but uv cannot install from them directly [U].
- **Dependency diff design [A]:**
  1. Parse base vs head lockfiles (uv.lock, poetry.lock, pdm.lock, requirements*.txt) as declared intent.
  2. Diff `uv pip list --format json` of the actually installed base vs head venvs as ground truth.
  3. Record lockfile drift (pyproject changed but `uv lock --check` fails on head) as its own evidence item.

## 8. git worktrees on Windows

- **`git worktree`** (docs current as of Git 2.56.0, 2026-09-28; local Git 2.55) [V]:
  - `add --detach`, `--no-checkout` (to configure sparse-checkout first), `--lock` (race-free), `-f`.
  - `remove` only works on clean worktrees unless `--force`. Worktrees with submodules need `--force`. A locked worktree needs `--force` twice.
  - `prune [--expire] [-n] [-v]`. `gc.worktreePruneExpire` cleans up worktrees deleted by hand.
  - `repair`.
  - Config is shared unless `extensions.worktreeConfig=true`. Then `config.worktree` is per-worktree. `core.sparseCheckout` should not be shared.
  - `worktree.useRelativePaths` requires newer Git.
  - **BUGS section: "support for submodules is incomplete. It is NOT recommended to make multiple checkouts of a superproject."**
- **Long paths.**
  - MAX_PATH = 260. The `\\?\` prefix allows about 32,767 characters. Windows 10 1607+ removes the limit only if **both** the registry `LongPathsEnabled=1` and an app manifest `longPathAware` are present. Relative paths stay limited to MAX_PATH [V].
  - Python is long-path-aware since 3.6, once the policy is enabled [V].
  - Git for Windows: long paths are "disabled by default". Enable with `core.longpaths=true`. It uses `\\?\` paths, and scripted git commands may still fail [V].
  - Pass it per command: `git -c core.longpaths=true worktree add ...`. Do not change the user's global config [A].
- **Cleanup.**
  - `shutil.rmtree(..., onexc=...)`: `onexc` was added in 3.12, and the docs show the read-only-bit-clearing recipe for Windows. Since 3.8 it does not delete the contents of directory junctions. The symlink-attack-resistant implementation is used "on platforms that support the necessary fd-based functions" [V].
  - Windows file locks from lingering processes, Defender or indexers cause `PermissionError`. Use Job Object kill-on-close, then retry with backoff, then `git worktree prune` [A].
- **Performance.** Worktrees share the object store, so `add` costs one checkout and no clone [A]. Dev Drive (ReFS) is available on all Windows SKUs, needs Win 11 22621.2338+ and 50 GB minimum, and supports block cloning on 24H2+ [V].
  - **Security trade-off:** a *trusted* Dev Drive puts Defender in performance mode (asynchronous scanning) [V]. That is undesirable for untrusted target code [A].
- **Security hazard of worktrees with untrusted code [A].** A linked worktree has a `.git` *file* pointing into the main repo's `.git/worktrees/<id>` and shares the main repo's config and hooks. Code running in the worktree can write to the host repo's `.git` (config, hooks), and the next host `git` command could then run attacker-chosen programs. Which config keys lead to code execution is unverified [U]. **Mitigation:**
  - Use the worktree only as a staging checkout on the host.
  - Give the sandbox a **snapshot without `.git`**: `git archive <ref>`, or copy the worktree minus the `.git` file into a container volume.
  - Or mount it read-only.

## 9. Perf diffing methodology

- **pyperf** (`2.10.0`, 2026-02-07, MIT, psf/pyperf active) [V]:
  - Spawns many worker processes. The doc example uses 20 workers × 3 values. Calibrates loops so "a value takes 100 ms by default". Usually skips the first value as warmup [V].
  - Multiple processes are used to average out ASLR and hash randomization [V].
  - `pyperf system tune` adjusts governor, Turbo Boost and IRQ affinity, and checks ASLR (which "must *not* be disabled manually") and the power cable. "Isolating at least 1 core has a significant impact on the stability"; `--affinity` pins CPUs; on Windows workers run at `REALTIME_PRIORITY_CLASS` [V].
  - `compare_to` uses a **Student's two-sample, two-tailed t-test**, plus a `--min-speed` threshold [V].
  - Unstable results trigger "WARNING: the benchmark result may be unstable" [V].
- **Statistics.**
  - Kalibera & Jones argue for reporting **effect-size confidence intervals of the ratio of means**, for example "5.5% ± 2.5% with 95% confidence". They offer parametric and non-parametric methods (arXiv 2007.10899, Kent TR 4-12, Nov 2013) [V]. The ISMM 2013 paper covers repetitions and hierarchical designs [S].
  - `scipy.stats.bootstrap(data, statistic, n_resamples=9999, paired=False, confidence_level=0.95, method='BCa', rng=...)` supports multi-sample statistics [V, SciPy 1.18.0].
- **Tools** (versions only): `pytest-benchmark 5.3.0`, `pytest-codspeed 5.0.3` [V]. Whether CodSpeed's instruction-count mode is low-noise and Linux-only is unverified [U]. Python 3.15's `profiling.sampling` can attribute where time went [V].
- **Recommended method [A]:**
  1. Never measure perf with the tracer on. Use a separate untraced pass.
  2. Interleave runs `B H H B B H …` (ABBA) so thermal and frequency drift cancels. Use the same Python build and the same container.
  3. Use per-test `call`-phase durations from pytest reports (exact semantics [U]). Ignore tests with median < about 5–10 ms (timer and overhead noise) and list them as `perf: not assessable` rather than "no change".
  4. Use R ≥ 10 repetitions per side for selected tests (more on laptops).
  5. Statistic: ratio of medians with a BCa bootstrap 95% CI, plus Mann–Whitney U, plus Benjamini–Hochberg across tests.
  6. **Run an A/A calibration** (base vs base) to measure the noise floor on *this* machine.
  7. Flag a regression only if the CI excludes 1 **and** |Δ| ≥ max(floor, A/A p95).
  8. Defensible starting floors: **10% on laptops** (15% on battery or thermal throttling) and **5% on dedicated or quiet CI**. These are my recommendations, not sourced standards. Treat them as configurable.
  9. Report text: "head slower 18% (95% CI 11–26%), noise floor 6%".

## 10. Determinism and flakiness

- **PYTHONHASHSEED.** See §1.7. A fixed integer gives repeatable str/bytes hashing, and `0` disables randomization [V].
- **pytest-randomly** (`5.0.0`, 2026-09-01, MIT) [V]:
  - Shuffles modules → classes → functions (and doctests).
  - **Resets `random` seeding around setup, call and teardown** using base seed + test ID. Also reseeds factory_boy, Faker, Model Bakery, NumPy (legacy) and Polyfactory.
  - `--randomly-seed=N|last`, `--randomly-dont-reorganize`, `--randomly-dont-reset-seed`, `-p no:randomly`. "Works with pytest-xdist".
  - Its README does not mention PYTHONHASHSEED [V].
- **pytest-xdist** (`3.8.0`, 2025-07-01, MIT) [V]:
  - Known limitation: "It is not possible to have tests that differ in order or their amount across workers". Sets used in parametrization can make workers collect differently; fix by sorting or using lists.
  - `-s` does not work. `--pdb` is disabled.
  - Modes: `load` (default; no ordering guarantee), `loadscope`, `loadfile`, `loadgroup`, `worksteal`, `no`. `-n auto` (physical cores) and `-n logical` [V].
- **Time.**
  - **freezegun** (`1.5.5`, 2025-08-09; last push Aug 2025) does a find-and-replace of `datetime`/`time` references at module level. It is slow on large projects and misses class-level references and C extensions [V].
  - **time-machine** (`3.5.1`, 2026-09-08, MIT) mocks the stdlib functions "everywhere they may be referenced" without `LD_PRELOAD`. Other libraries' system calls are not mocked. CPython only [V].
- **Reruns.**
  - `pytest-rerunfailures 16.7` (2026-09-17): `--reruns`, `--reruns-delay`, `--only-rerun REGEX`, `--rerun-except REGEX`, `@pytest.mark.flaky(reruns=N)`. Requires xdist ≥ 2.3 to rerun crashed tests [V].
  - `pytest-repeat 0.9.4` [V]. `pytest-flakefinder 1.1.0` (2022) [V].
- **Repro policy [A]:**
  1. Fixed env for base and head: `PYTHONHASHSEED=0`, `-p no:randomly` (or the same `--randomly-seed`), `-p no:xdist` or Repro-level deterministic sharding, `PYTHONUTF8=1`, `TZ`/locale pinned (`TZ=UTC` is honoured on Windows too: measured in D04 with CPython 3.12–3.15 on a host whose own time zone is not UTC, `time.localtime(0)` is midnight), a minimal environment, and an empty `addopts` override where needed (`-o addopts=`).
  2. **Run base twice.** The second run uses a different `PYTHONHASHSEED` and a reversed test order.
     - A test whose outcome differs is `flaky`.
     - An observation field that differs is `unstable` and is masked from the base/head diff.
     - Both appear on the card as explicit items.
  3. When a head test fails and base passed, rerun the head test k=3 times (and base k=3) before calling it a regression, and record the pass ratio.
  4. Do not freeze time globally by default (it changes behaviour). Detect time-dependence through the A/A run and offer an opt-in time-machine mode.

---

## Recommended engine design

### A. Reuse vs build

| Concern | Reuse | Build |
|---|---|---|
| Worktrees and cleanup | `git` CLI (`worktree add --detach`, `-c core.longpaths=true`), `shutil.rmtree(onexc=)` | Run manager, snapshot export to the sandbox (no `.git`), retry and kill logic |
| Venvs | **uv** (`uv python install`, `uv venv`, `uv sync --locked`/`uv pip install`, `--link-mode copy` in sandbox, `--exclude-newer`) | Project-type detection (uv/poetry/pdm/requirements/setup.py), Python version choice |
| Import graph | **grimp** (Rust core, lazy imports, BSD-2) | Mapping of module-level changes to importers |
| Symbol table and changed-line → symbol | stdlib **ast** (`lineno`/`end_lineno`); LibCST later | Qualname-based symbol IDs stable across refs, rename matching |
| Public API diff | **griffe** `load(search_paths=[wt], allow_inspection=False)` + `find_breaking_changes` | Mapping `Breakage` → evidence IDs; return-type and attribute-type checks griffe lacks (annotation string compare) |
| Per-test function map (test selection) | none suitable (testmon and pytest-rts are coverage-context based and idle) | **Own `sys.monitoring` PY_START collector** inside the Repro pytest plugin |
| Behaviour trace | none | **Own tracer + canonical encoder** (core IP) |
| Line coverage (optional evidence) | coverage.py 7.16 in a *separate* pass (`sysmon` core without contexts, or `ctrace` with contexts) | — |
| Network | pytest-socket's *approach* (simple to vendor) + audit hooks for detection | Evidence events from attempts |
| Isolation | Docker (`--network none`), gVisor on Linux CI, optional E2B Embed | Sandbox driver abstraction (native Windows, container, remote) |
| Determinism | pytest-randomly flags, PYTHONHASHSEED, pytest-rerunfailures semantics | A/A runs, unstable-field masking |
| Perf stats | `scipy.stats.bootstrap`, Mann–Whitney; pyperf for microbenchmarks | Interleaved runner, A/A noise floor |
| Deep checks (later) | CrossHair `diffbehavior`, Hypothesis ghostwriter, mutmut/cosmic-ray (in Linux sandbox) | Input replay across sides, benchmark seeding |

### B. Pipeline

1. **Prepare.**
   - `git -c core.longpaths=true worktree add --detach <short-root>\b <base>` and `…\h <head>`. Use a short root such as `%LOCALAPPDATA%\repro\r\<8-char-run-id>\{b,h}` on the same volume as the uv cache.
   - Sandbox mode: export each tree into a container volume with no `.git`.
2. **Static pass** (host, never executes target code).
   - `git diff -U0 base head` gives changed hunks. `ast` maps hunks to the enclosing symbol (module, class, function) on each side.
   - Changes at module or class-body level are `module-level` symbols.
   - grimp reverse dependencies (`find_downstream_modules`) give the importers.
   - griffe API diff with `allow_inspection=False`.
   - Lockfile diff.
3. **Install pass** (sandbox, network allowed only to the package index). Building sdists executes code.
   - `uv sync --locked` (record `uv lock --check`), or `uv pip install -r … --exclude-newer <head commit date>`.
   - Interpreter: same version for both sides, chosen from `.python-version` / `requires-python` / CI config. Must be ≥ 3.12 or tracing becomes an explicit `missing` item.
   - Then `uv pip list --format json` for the installed-dependency diff.
4. **Selection pass** (sandbox, network off; base, plus head for new or changed tests).
   - Full suite under the Repro plugin in `collect-map` mode.
   - Global PY_START on a tool ID.
   - Project code: record `code → current test nodeid`. Non-project code: return `DISABLE` once.
   - Result: test → set of functions.
   - Select = tests touching blast-radius functions ∪ tests importing changed module-level symbols ∪ new or modified tests.
   - Cache the map per base commit plus lockfile hash, the testmon-like environment key.
5. **Trace passes** (sandbox, network off): base run A, base run A′ (different seed and order), head run H.
   - Selected tests only, with the tracer on blast-radius code objects.
   - Emit per-test observation records and outcome. Detection events come from the guard and audit hook.
6. **Perf pass** (sandbox, untraced, interleaved).
7. **Diff and evidence.**
   - Compare A vs A′ to find unstable fields.
   - Diff A vs H on stable fields only.
   - Give each difference an evidence ID. Missing data (timeouts, unencodable values, tool ID unavailable, subprocess untraced, network not enforced) becomes explicit `missing` items.

### C. Tracer design (inside the Repro pytest plugin, target venv, Python ≥3.12)

```python
# sketch, not final code
import sys, inspect, threading
mon, E = sys.monitoring, sys.monitoring.events
CO_VARARGS, CO_VARKEYWORDS = inspect.CO_VARARGS, inspect.CO_VARKEYWORDS

def claim_tool_id():
    for tid in (4, 3, 2, 5):                # leave 0 (debugger) and 1 (coverage) alone
        try:
            mon.use_tool_id(tid, "repro"); return tid
        except ValueError:
            pass
    return None                             # -> card item: missing behaviour-trace

KEEP = []                                   # keep code objects alive (id() reuse), like coverage.py
TARGET = {}                                 # id(code) -> symbol_id ; filled lazily
LOCAL = E.PY_RETURN | E.PY_YIELD | E.PY_RESUME

def on_py_start(code, off):
    sid = TARGET.get(id(code))
    if sid is None:
        sid = resolve(code)                 # (normalized co_filename, co_qualname, ordinal) -> symbol or False
        TARGET[id(code)] = sid; KEEP.append(code)
        if sid:
            mon.set_local_events(TID, code, LOCAL)  # cost once per code object
    if not sid:
        return mon.DISABLE                  # non-target: never called again at this location
    f = sys._getframe(1)                    # callee frame is on the stack at PY_START
    n = code.co_argcount + code.co_kwonlyargcount \
        + bool(code.co_flags & CO_VARARGS) + bool(code.co_flags & CO_VARKEYWORDS)
    loc = f.f_locals
    push(id(f), sid, encode_args({k: loc[k] for k in code.co_varnames[:n] if k in loc}))
    # keep PY_START enabled for targets (we need every call), subject to per-test budget

def on_py_return(code, off, retval):  record_exit(code, "return", encode(retval))
def on_py_unwind(code, off, exc):     # global on 3.12-3.14; filter cheaply
    if id(code) in TARGET and TARGET[id(code)]:
        record_exit(code, "raise", encode_exc(exc))
```

Further rules [A]:

- **Per-test attribution.** `pytest_runtest_setup/call/teardown` hooks set a thread-local "current test and phase". Records land in a per-test buffer that is flushed to `<out>/obs/<nodeid-hash>.msgpack` after each test.
- **Budgets.** For each (test, function), fully encode the first *N* calls (e.g. 200). After that, keep counts and rolling hashes only, then stop. On stop, return `DISABLE` from PY_START and `set_local_events(TID, code, 0)`. Mark `truncated: true` explicitly.
- **Hot-path overhead is unknown [U].** Benchmark it in M-tracer before committing to budgets.
- **Threads, async, generators.** In-flight calls are keyed by `id(frame)`, with per-thread stacks. Yields are recorded as bounded sequences.
- **Subprocesses.** Children are not traced. Record `subprocess.Popen` via the audit hook and add a card item "behaviour in subprocess not traced". Injection via `.pth` is deprecated in 3.15 (PEP 829 `.start` files) [V]; revisit later.
- **3.15+.** Use `set_local_events` for `PY_UNWIND` on targets instead of the global setting [V for the capability].

### D. Canonical value encoding (making observations hashable and stable) [A]

`canon(x, depth, budget) -> bytes` uses a deterministic, CBOR-like tagged encoding. The hash is `blake2b(canon, digest_size=16)`. Each observation stores `hash`, `type_sig`, and up to 3 sampled *safe* previews.

- **Scalars.**
  - `None/bool/int`: exact.
  - `str`: exact, after path normalization (`<ROOT>`, `<TMP>`, `<HOME>`, `\`→`/`, `0x[0-9a-f]{6,}`→`<ADDR>`).
  - `bytes`: exact.
  - `float`: `float.hex()`, with explicit `nan` / `-0.0`.
  - `complex`, `Decimal`, `Fraction`: exact string forms.
- **Sequences.** `list/tuple`: ordered elements.
- **Dicts.** Ordered key/value pairs, plus a second **order-insensitive** digest (sorted by encoded key). A difference only in the ordered digest is reported as `order-only`.
- **Sets and frozensets.** Elements sorted by their encoded bytes, which removes PYTHONHASHSEED effects.
- **Objects.** `type.__module__ + qualname` + a structural walk:
  - dataclass fields, `__slots__`, or `vars(obj)` read via `object.__getattribute__`
  - **never** calling `__repr__`, `__eq__`, properties, `__iter__` or `__len__` of user classes
  - known safe adapters for enum (name), datetime (isoformat; flagged time-like), pathlib (normalized), UUID (flagged random-like), re.Pattern, numpy/pandas (dtype + shape + blake2 of the buffer when contiguous)
- **Opaque values.** Generators, iterators, files, sockets, locks, modules and functions encode as `<opaque:type>` (functions as `<fn:qualname>`). Consuming them would change behaviour.
- **Exceptions.** Type qualname + canonical `args` (normalized) + `__cause__` type chain. Messages are kept but stored separately, so that "same type, different message" is distinguishable.
- **Guards.** Cycle detection (an id-set within one call), max depth (e.g. 6), max nodes (e.g. 5,000), a time budget per encode, and try/except around everything. Truncated or failed encodes are tagged as such and **never** treated as equal.
- **Mutation evidence.** Optionally re-encode the arguments, including `self`, at return. An argument whose hash changed is a *behaviour*: "f mutates its input".
- **Stability check.** Fields that differ between A and A′ (same code, different seed and order) are unstable. They are masked from the A-vs-H diff and listed on the card.

### E. Isolation layers (what the card states)

| Layer | Windows dev machine (Home edition) | Linux CI |
|---|---|---|
| L0 process | Separate process per side, minimal env, fixed seeds | same |
| L1 detect | Guard (socket, getaddrinfo) + audit hook → evidence | same |
| L2 contain | **Job Object**: kill-on-close, memory, CPU, process limits, wall timeout. Throwaway dirs. *Network is not enforced.* | cgroups/ulimit + timeouts |
| L3 enforce (default when available) | **Docker Desktop (WSL2) Linux container**: `--network none`, `--read-only` + tmpfs, `--cap-drop ALL`, `--security-opt no-new-privileges`, non-root user, `--pids-limit/--memory/--cpus`. Snapshot copied into a volume (not a bind mount of a live worktree). uv cache read-only + `--link-mode copy`. The install step runs in a separate container with egress limited to the index, or wheels are prefetched on the host and installed `UV_OFFLINE=1`. | Docker/Podman, same flags; or bubblewrap/nsjail `--unshare-net` |
| L4 harden | not available locally (no Windows Sandbox on Home; gVisor unverified in WSL2) | **gVisor `--runtime=runsc`** or **Firecracker via E2B Embed** (needs KVM) |

Rules [A]:

- If L3 is unavailable, the card says `network: detected-only` and `isolation: process`.
- Running the tests in Linux on a Windows box changes the platform, but base and head share it, so the *diff* stays valid. Record `platform: linux-container` on the card.

### F. Windows caveats checklist

1. `sys.monitoring` needs 3.12+, and many machines still default to an older Python. Use `uv python install` for the target and for the engine.
2. Upgrade uv: versions before 0.12.18 lack the Windows wheel path-traversal fix.
3. uv defaults to Python **3.15** since 0.13.0. Pin the interpreter explicitly.
4. Long paths: `LongPathsEnabled=1` is set here, but Git needs `-c core.longpaths=true` per command. Keep roots short anyway: relative paths stay capped at 260, and other tools are not long-path-aware.
5. Cache and worktrees must be on the same volume for hardlinks. Hardlinks plus untrusted code risks cache poisoning, so use `copy` in sandboxes.
6. Windows Sandbox and Hyper-V are unavailable on Home. Use Docker Desktop (WSL2), which works here, or a Linux CI runner. Bare WSL is not isolation (Windows interop).
7. Bind mounts from Windows to the Linux container are slow. Copy snapshots into volumes.
8. File locks: kill the Job Object before cleanup, then retry `rmtree(onexc=…)`, then `git worktree prune`.
9. Defender scanning slows venv creation. A trusted Dev Drive speeds it up but lowers scanning of untrusted code. Prefer keeping untrusted code inside the container's VM disk.
10. mutmut needs fork, so run it in the container. CrossHair and Hypothesis run anywhere, but inside the sandbox.

### G. Known hard problems and mitigations [A]

| Problem | Mitigation |
|---|---|
| Symbol identity across refs (moves, renames, overloads, conditional defs) | Key by module + qualname + ordinal. Fall back to AST-similarity matching. Unmatched symbols become `added`/`removed` items. |
| Module-level and import-time changes (constants, decorators, class bodies, `__init__`) | Treat them as blast radius of all importers (grimp downstream). Select tests that import them. Observe import-time effects only coarsely. |
| Dynamic dispatch, monkeypatching, plugins, `getattr` | Selection uses the dynamic per-test function map from base, plus head for new paths. The static graph is only a supplement. |
| New or changed tests | Always run them on both sides. On base they may not collect; record "not applicable on base". |
| Non-determinism (hash seed, order, time, randomness, threads) | A/A′ runs, unstable-field masking, rerun quorum, explicit flaky items. |
| Observer effect of encoding | Structural encoder that never calls user dunders. Budgets. Re-entrancy is safe because events are suspended in the tool's own callback [V]. |
| Overhead on hot functions | Target-only local events, DISABLE for everything else, per-test call budgets. Benchmark early because the true per-call cost is unknown [U]. |
| Tool-ID contention (coverage, pdb, debuggers) | ID search order 4, 3, 2, 5. No coverage in the same process. Explicit `missing` if no ID is free. On 3.12/3.13 do not reuse IDs others freed. |
| Free-threaded targets | Per-thread buffers. Mark as experimental on the card. |
| Subprocess-based tests | Audit-hook detection plus a `missing` item. Injection later. |
| Untrusted install step (sdist builds, setup.py) | Install inside the sandbox. Prefer `--no-build`. Pin the tool version and upgrade uv. |
| Host repo tampering via worktree `.git` | Sandbox gets a `.git`-less snapshot. Never run target code in a live linked worktree on the host. |
| Perf noise on laptops | Untraced interleaved runs, A/A floor, CI-based ratios, "not assessable" for tiny tests. |
| griffe or jedi executing code | `allow_inspection=False` for griffe. Run jedi/pyright only inside the sandbox. |

---

## Sources

All URLs were accessed on 2026-10-13. Tags follow the legend above.

**Python core**

- https://docs.python.org/3/library/sys.monitoring.html (3.15.0 docs) [V]
- https://docs.python.org/3.12/library/sys.monitoring.html [V]
- https://docs.python.org/3.13/library/sys.monitoring.html [V]
- https://peps.python.org/pep-0669/ [V]
- https://docs.python.org/3.15/whatsnew/3.15.html (first ~100k chars) [V]
- https://docs.python.org/3/whatsnew/3.14.html (chars 0–200k) [V]
- https://peps.python.org/pep-0790/ (3.15.0 final 2026-10-09) [V]
- https://docs.python.org/3/howto/free-threading-python.html [V]
- https://github.com/python/cpython/issues/116818 [V]
- https://peps.python.org/pep-0667/ [V]
- https://docs.python.org/3/library/sys.html (addaudithook, _getframe) [V]
- https://docs.python.org/3/library/audit_events.html [V]
- https://docs.python.org/3/using/cmdline.html (PYTHONHASHSEED, -I, -P, UTF-8) [V]
- https://docs.python.org/3/reference/datamodel.html (dict order, `__repr__`) [V]
- https://docs.python.org/3/library/pickle.html [V]
- https://docs.python.org/3/tutorial/floatingpoint.html [V]
- https://docs.python.org/3/library/shutil.html (rmtree onexc) [V]
- https://docs.python.org/3/library/threading.html [V]
- https://docs.python.org/3/using/windows.html (MAX_PATH) [V]
- Local experiment: CPython 3.11.9 `-I` with PYTHONHASHSEED 0/1/2 (set order, repr address, float repr) [V-local]

**Coverage and test selection**

- https://coverage.readthedocs.io/en/latest/changes.html [V]
- https://coverage.readthedocs.io/en/latest/config.html [V]
- https://coverage.readthedocs.io/en/latest/contexts.html [V]
- https://coverage.readthedocs.io/en/latest/api_coveragedata.html [V]
- https://raw.githubusercontent.com/coveragepy/coveragepy/main/coverage/sysmon.py [V]
- https://nedbatchelder.com/blog/202312/coveragepy_with_sysmonitoring.html [V]
- https://nedbatchelder.com/blog/202503/faster_branch_coverage_measurement.html [V]
- https://nedbatchelder.com/blog/202407/pushing_back_on_sysmonitoring (search summary only) [S]
- FOSDEM 2024 "Python 3.12's new monitoring and debugging API" slides, https://archive.fosdem.org/2024/events/attachments/fosdem-2024-1678-python-3-12-s-new-monitoring-and-debugging-api/slides/22878/Python3_12MonitoringFOSDEM20min_Ni4FuSI.pdf (PDF unreadable; numbers from a snippet) [S]
- https://github.com/plasma-umass/slipcover [V]
- https://pytest-cov.readthedocs.io/en/latest/changelog.html [V]
- https://github.com/tarpas/pytest-testmon [V]
- https://testmon.org/blog/determining-affected-tests/ [V]
- https://raw.githubusercontent.com/tarpas/pytest-testmon/main/testmon/testmon_core.py [V]
- https://pypi.org/pypi/pytest-testmon/json [V]
- https://pypi.org/pypi/pytest-rts/json [V]

**Static analysis**

- https://grimp.readthedocs.io/en/stable/usage.html [V]
- https://grimp.readthedocs.io/en/stable/changelog.html [V]
- https://mkdocstrings.github.io/griffe/guide/users/checking/ [V]
- https://mkdocstrings.github.io/griffe/changelog/ [V]
- https://mkdocstrings.github.io/griffe/reference/api/checks/ [V]
- https://mkdocstrings.github.io/griffe/reference/api/loaders/ [V]
- https://libcst.readthedocs.io/en/latest/metadata.html [V]
- https://jedi.readthedocs.io/en/latest/docs/api.html [V]
- https://raw.githubusercontent.com/microsoft/pyright/main/docs/command-line.md [V]
- https://raw.githubusercontent.com/microsoft/pyright/main/docs/features.md [V]
- https://raw.githubusercontent.com/thebjorn/pydeps/master/README.rst [V]

**Behavioural equivalence and mutation**

- https://crosshair.readthedocs.io/en/latest/diff_behavior.html [V]
- https://hypothesis.readthedocs.io/en/latest/reference/integrations.html [V]
- https://raw.githubusercontent.com/boxed/mutmut/main/README.rst [V]
- https://cosmic-ray.readthedocs.io/en/latest/ [V]
- https://cosmic-ray.readthedocs.io/en/latest/concepts.html [V]

**Network and isolation**

- https://pypi.org/pypi/pytest-socket/json (README) [V]
- https://raw.githubusercontent.com/miketheman/pytest-socket/main/src/pytest_socket/__init__.py [V]
- https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/ [V]
- https://docs.docker.com/desktop/setup/install/windows-install/ [V]
- https://docs.docker.com/engine/network/drivers/none/ [V]
- https://docs.docker.com/desktop/features/wsl/ (little relevant content) [V]
- https://learn.microsoft.com/en-us/windows/wsl/filesystems [V]
- https://raw.githubusercontent.com/podman-container-tools/podman/main/docs/tutorials/podman-for-windows.md [V]
- https://gvisor.dev/docs/user_guide/quick_start/docker/ [V]
- https://raw.githubusercontent.com/google/gvisor/master/g3doc/user_guide/install.md [V]
- https://raw.githubusercontent.com/firecracker-microvm/firecracker/main/docs/getting-started.md [V]
- https://raw.githubusercontent.com/containers/bubblewrap/main/README.md [V]
- https://raw.githubusercontent.com/google/nsjail/master/README.md [V]
- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects [V]
- https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation [V]
- https://docs.e2b.dev/ (the page contained agent-directed text; ignored) [V]
- https://raw.githubusercontent.com/e2b-dev/infra/main/README.md [V]
- https://modal.com/docs/guide/sandbox [V]
- https://raw.githubusercontent.com/daytonaio/daytona/main/README.md (archived notice) [V]

**uv**

- https://docs.astral.sh/uv/concepts/cache/ [V]
- https://docs.astral.sh/uv/reference/settings/ [V]
- https://docs.astral.sh/uv/concepts/projects/sync/ [V]
- https://docs.astral.sh/uv/concepts/resolution/ [V]
- https://docs.astral.sh/uv/reference/environment/ [V]
- https://github.com/astral-sh/uv/releases [V]
- https://raw.githubusercontent.com/miketheman/pytest-socket/main/uv.lock (real lockfile, format observed) [V]
- Local: `uv venv --help`, `uv help pip install`, `uv pip list --help`, `uv lock --help` [V-local]

**git and Windows filesystem**

- https://git-scm.com/docs/git-worktree [V]
- https://gitforwindows.org/git-cannot-create-a-file-or-directory-with-a-long-path.html [V]
- https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation [V]
- https://learn.microsoft.com/en-us/windows/dev-drive/ [V]

**Performance**

- https://pyperf.readthedocs.io/en/latest/system.html [V]
- https://pyperf.readthedocs.io/en/latest/cli.html [V]
- https://pyperf.readthedocs.io/en/latest/run_benchmark.html [V]
- https://arxiv.org/abs/2007.10899 (Kalibera & Jones) [V]
- Kalibera & Jones, "Rigorous Benchmarking in Reasonable Time", ISMM 2013 (via search summaries) [S]
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html [V]

**Determinism**

- https://pypi.org/pypi/pytest-randomly/json (README) [V]
- https://pytest-xdist.readthedocs.io/en/stable/known-limitations.html [V]
- https://pytest-xdist.readthedocs.io/en/stable/distribution.html [V]
- https://time-machine.readthedocs.io/en/latest/comparison.html [V]
- https://raw.githubusercontent.com/adamchainz/time-machine/main/docs/comparison.rst [V]
- https://raw.githubusercontent.com/pytest-dev/pytest-rerunfailures/master/README.rst [V]

**Versions, dates, licences and activity**

- PyPI JSON API, https://pypi.org/pypi/{pkg}/json [V], for: coverage, pytest-cov, pytest-testmon, grimp, import-linter, griffe, libcst, jedi, pyright, pydeps, crosshair-tool, hypothesis, mutmut, cosmic-ray, pytest-socket, uv, pyperf, pytest-randomly, pytest-xdist, freezegun, time-machine, pytest-rerunfailures, pytest (9.1.1), pytest-benchmark, claude-agent-sdk (0.2.165), pytest-incremental, pytest-picked, tach, slipcover, pytest-codspeed, ty, pyrefly, basedpyright, mypy, ruff.
- GitHub REST API, https://api.github.com/repos/{owner}/{repo} [V], for push dates, licences, archived flag and redirects: grimp → python-grimp, coveragepy → coveragepy/coveragepy, podman → podman-container-tools, tach → tach-org, Daytona archived. The API rate limit was hit before ty/pyrefly/ruff could be checked [U].
- Search-result summaries: free-threading and monitoring thread-safety, Kalibera & Jones [S].
