# E02 — Canonical value encoder

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | E01 |
| **Branch / PR** | `phase/E02-canonical-encoder` · [#47](https://github.com/DuhItzAniket/Repro/pull/47) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Turn any value a traced function receives or returns into a digest that is the same for the
same value in every process, hash seed, Python version and working directory, different for
different values wherever it can tell, explicitly incomplete where it cannot, and obtained
without running a line of the target's own code.

## Scope
- **The encoder** (`sandbox/_hook/repro_encode.py`, standard library only), extending E01's:
  - objects: the type's name and the instance's state (instance dictionary, then `__slots__`
    values), read through the interpreter's own descriptors taken from `type`, `object` and
    `BaseException`, never looked up on the value or its class;
  - builtin subclasses (a named tuple, an `int` subclass): the builtin value through the base
    type's own C methods and iterators, plus the instance's state;
  - exceptions: type, `args`, and the types along the `__cause__` / `__context__` chain;
  - exact standard-library value types the target already imported: `datetime`, `date`,
    `time`, `timedelta`, `Decimal`, `Fraction`, `UUID`, paths, `re.Pattern`; enum members by
    name;
  - functions, classes, modules, generators, coroutines, code and frames as named tokens;
  - strings normalised: the snapshot root, the temporary and home directories become
    `<ROOT>`, `<TMP>`, `<HOME>` (and `\` becomes `/` after them); hexadecimal addresses become
    `<ADDR>`;
  - for results, a second, order-insensitive digest, from the same walk: dictionaries sorted,
    their insertion orders kept apart;
  - guards: depth, nodes, time (50 ms), and object cycles (`Y`), each making the encoding
    incomplete (a container holding itself is stopped by the depth guard);
  - previews (`preview`): at most 512 characters, under the same rules (for `trace.sample` and
    `diff.behaviour`, E04).
- **The tracer** digests a call's arguments as the tuple of its parameters' values (in
  parameter order; the names are the function's), its result with both digests (the second
  recorded only where it differs, `result_any_order`), and a raised exception whole.
- **`repro.runner.trace.same`**: two encodings are the same value only when both are complete.
- **Tests**: Hypothesis properties and a corpus of hostile objects (`engine/tests/hostile.py`).

## Out of scope
- Storing observations and masking unstable fields (E03); classifying diffs (different result,
  order-only, new exception, mutation) and reproducers (E04); value previews for reproducers.

## Design notes
- **Descriptors from the builtin types, not from the value.** `type.__dict__["__mro__"]`,
  `type.__dict__["__dict__"]`, `type.__dict__["__qualname__"]` and `BaseException`'s `args`,
  `__cause__`, `__context__` are fetched once and applied to the value's real type
  (`type(value)`). A metaclass `__getattribute__`, an instance `__getattribute__` or
  `__getattr__`, a `__class__` property, properties, `__eq__`, `__hash__`, `__repr__`, `__iter__`
  or `__len__` therefore never run. `issubclass` on the real type replaces `isinstance`, which
  can consult a forged `__class__`.
- **A class's own descriptor makes it opaque.** If a class puts its own descriptor where the
  instance dictionary or a slot would be, reading it would run its code; the object is then its
  type's name only, a missed difference rather than a run of target code.
- **Containers are never rebuilt.** A subclassed `dict` or `set` is read through `dict.items` and
  the base type's own iterators, which walk the underlying table; copying it instead would let
  an overridden `__iter__` or `keys` run (the corpus caught `dict.copy` calling `keys()` on a
  subclass that overrides `__iter__`) and would hash its keys again.
- **Only modules already imported.** Adapters exist for the standard-library types of modules
  the target has itself imported; the encoder imports nothing, so it changes nothing about the
  run. The table is rebuilt only when the number of imported modules changes.
- **Order kept, order told apart, where it matters.** Dictionaries keep insertion order in the
  main digest, as Python does (deterministic in every process). For results, the same walk
  also sorts them and keeps their orders apart, so E04 can call a difference in order alone
  `order_only` (ARCHITECTURE §4.3). Arguments are join keys built the same way by the same test
  on both sides, so they skip the sorting.
- **Encoder speed is a requirement (A08).** The first full version pushed the dict-heavy
  benchmark test to 1.35–1.55×: it walked dictionary-holding values twice. Then: one walk for
  both digests; cycle tracking for objects only; lazy setup; one checkpoint comparison per value
  for the node and time guards; a string scanned for a directory or an address only when it is
  long enough to hold one; exact lists, tuples and insertion-order dictionaries walked inline;
  the second hash only when some dictionary was out of sorted order; sorting only for results.
- **A record per traced call is no longer flushed on its own.** Call records go out with the
  test's own record (ARCHITECTURE §4.3 says records are flushed per test). A flush cost about
  2.3 µs per call on Windows; a process killed mid-test loses at most that test's calls, whose
  test has no record either, and the reader counts a cut last line as malformed.

## Acceptance criteria
- [x] AC1 (roadmap): Hypothesis property tests — stable across processes and hash seeds, never
  calls user dunders, guards terminate, truncated values are never equal.
- [x] AC2 (roadmap): a fuzz corpus of hostile objects, alone and mixed with generated values.
- [x] AC3: the tracer's overhead stays within E01's check with the full encoder.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_encoder_properties.py`: generated builtins digested in fresh interpreters under two other hash seeds; equal values (a pickle round trip) give equal digests; guards terminate under a second for any depth and width; an incomplete encoding is never `same` as anything, itself included |
| AC2 | `test_no_user_code_runs_on_hostile_objects[…]` (18 kinds), `test_no_user_code_runs_on_mixtures` (generated mixtures), `test_what_objects_encode_to`, `test_builtin_subclasses_keep_their_value` |
| AC3 | `scripts/bench_tracer.py` on 3.12–3.15, appended to `docs/perf/E01-tracer-bench.jsonl` |

---
*Filled in at the end of the phase:*

## What shipped
- `sandbox/_hook/repro_encode.py`: objects, builtin subclasses, exceptions, standard-library
  adapters, the normaliser, `digest` / `digests`, guards, `preview`.
- `sandbox/_hook/repro_trace.py`: arguments as the parameters' values, `result_any_order`,
  exceptions encoded whole; `sandbox/_hook/repro_pytest.py`: call records flushed per test.
- `TraceCall.result_any_order`; `repro.runner.trace.same`.
- Tests: `test_encoder_properties.py` (Hypothesis properties, the hostile corpus, previews,
  builtin subclasses), `engine/tests/hostile.py`, updated `test_encode.py` and `test_tracer.py`
  (dictionary order, cross-version digests). pytest 1103 → 1121 (1109 pass and 12 skip on
  Windows with Docker Desktop stopped: the container tests skip too; CI runs them).
- `scripts/bench_tracer.py` marks a commit dirty only for changes to `engine/` or `scripts/`.

## Evidence
The benchmark with the full encoder (commit `9a11026`), Windows (x64), 8 rounds, call-phase
medians, BCa 95 % intervals; `docs/perf/E01-tracer-bench.jsonl`:

| Python | `fib(28)` | 40,000 records | 1,000,000 small calls |
|---|---|---|---|
| 3.12.13 | 1.15× (1.05–1.27) | 1.18× (1.04–1.24) | 1.10× (1.03–1.19) |
| 3.13.13 | 1.12× (1.03–1.20) | 1.14× (1.10–1.23) | 1.08× (1.04–1.14) |
| 3.14.4 | 1.12× (1.05–1.19) | 1.16× (1.13–1.21) | 1.09× (1.00–1.17) |
| 3.15.0 | 1.09× (1.02–1.16) | 1.15× (1.07–1.22) | 1.01× (0.93–1.10) |

- No interval lies above 1.20× (the highest low end is 1.13×); point estimates 1.01–1.18×,
  against E01's 0.89–1.20×.
- On the way: the first full encoder measured 1.35–1.55× on the records test (rows of
  `v0.4.0-35-g6a62f58-dirty`), one walk for both digests 1.24–1.32× (`e6cb771`), sorting for
  results only 1.14–1.28× (`2df4982`, over on 3.13 and 3.15); all kept in the file.
- Per call of the records test, in-process on 3.13.13 (2,000 calls, median of 7, two runs):
  encoding arguments and result 9.6–10.1 µs against E01's 10.1–10.8 µs; writing the record
  4.3–5.1 µs without the flush against 6.5–7.1 µs with it.
- The garbage collector is not the cost: on the records test, plain and traced runs made the
  same collections (37, 3 and 0 of generations 0, 1 and 2; medians of 6 runs each).
- Hostile corpus: 18 kinds of object (every comparison, hashing, `repr` and iteration dunder;
  instance `__getattribute__` / `__getattr__`; a metaclass `__getattribute__` and instance
  checks; a forged `__class__`; properties; a class's own `__dict__` and slot descriptors;
  `dict` and `list` subclasses overriding `items`, `keys`, `__iter__`, `__len__`; an exception
  with hostile dunders under a `raise ... from` chain), alone and inside generated mixtures:
  none of their code runs.
- Digests identical on 3.12.13, 3.13.13, 3.14.4 and 3.15.0, and under two other hash seeds.
- CI run: linked in the PR (#47).

## Deviations from spec
- ARCHITECTURE §4.3: "Dicts get ordered and order-insensitive digests." Arguments get the
  ordered digest only: they are join keys, built by the same test in the same way on both
  sides, and sorting them cost the benchmark more than its limit allowed. Results get both.
- A list or dict that contains itself is stopped by the depth guard (`X`), not by cycle
  detection (`Y`, objects only): tracking every container's identity cost too much per value.
- The order-insensitive digest equals the ordered one when every dictionary was already in
  sorted order (nothing to tell apart), which saves a second hash.
- research/03 §D's previews are built (`preview`) but not yet recorded by the tracer: E04's
  reproducers and E07's samples take them.

## Known gaps
- A class that defines its own `__dict__` or slot descriptors is encoded by type only, so two
  of its instances can share a digest (a missed difference, never target code run).
- Standard-library adapters cover the types listed in Scope; any other C-implemented type
  without a `__dict__` is its type's name only.
- Values that mutate while being walked (another thread) give an incomplete encoding.
- Free-threaded builds remain unsupported (E01).

## Dependencies added
None.

## Research notes
- research/03 §1.7 (hashing hazards) and §D (canonical value encoding) are the design this
  phase builds; ARCHITECTURE §4.3.
