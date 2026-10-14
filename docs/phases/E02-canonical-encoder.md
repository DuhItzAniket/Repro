# E02 — Canonical value encoder

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | in progress |
| **Depends on** | E01 |
| **Branch / PR** | `phase/E02-canonical-encoder` · PR pending |
| **Started / finished** | 2026-10-15 / — |

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
  - a second, order-insensitive digest with every dictionary sorted by its keys' encodings;
  - guards: depth, nodes, time (50 ms), and cycles (`Y`), each making the encoding incomplete.
- **The tracer** records the second digest only where it differs (`args_any_order`,
  `result_any_order`), and digests a raised exception whole.
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
- **Order kept, order told apart.** Dictionaries keep insertion order in the main digest, as
  Python does; the second digest sorts them, so E04 can call a difference in order alone
  `order-only` (ARCHITECTURE §4.3).

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

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- research/03 §1.7 (hashing hazards) and §D (canonical value encoding) are the design this
  phase builds; ARCHITECTURE §4.3.
