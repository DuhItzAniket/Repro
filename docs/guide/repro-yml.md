# `repro.yml`

A repository's policy for Repro: the invariants every change must keep, what a claim needs, and
how much may go unchecked. It lives at the repository's root. Its schema is
[`repro-yml.schema.json`](../../engine/src/repro/policy/repro-yml.schema.json).

```yaml
version: 1
invariants:
  - public_api_stable:
      except: ["mypkg.experimental.*"]
  - no_new_dependencies:
      allow: ["types-*"]
  - no_network: true
  - forbidden_paths: ["migrations/", "deploy/**/*.tf"]
  - perf_budget: { max_regression: 0.2 }
claims:
  require_explicit: true
missing:
  max_uncovered_changed_symbols: 0.25
```

Every part is optional. With no `repro.yml`, no invariant is evaluated and the defaults below
apply.

## Read from base, always
Repro reads the policy from the **base** side of the change, so a change cannot weaken the
policy it is judged by. When head edits `repro.yml`, the card shows the edit as a gap item
(`policy_change`) that flags, naming each weakening: an invariant removed, an exception or an
allowance added, a forbidden path dropped, the timing budget or the uncovered share raised,
`require_explicit` turned off.

The file is read safely: at most 64 KiB, one YAML document, no anchors or aliases, no duplicate
keys. If base's file is not valid, **no** invariant is evaluated (never the defaults instead),
and the card is UNVERIFIABLE with `policy_invalid`, saying what is wrong.

## Invariants
A list, one item per invariant, each at most once. Each gets a result on the card: `pass`,
`fail` (the card is FLAGGED), or `not_evaluated` when what it needs could not be observed (the
card is UNVERIFIABLE; never a pass by default).

### `public_api_stable`
No breaking change to the public API: a parameter moved, removed or newly required, a default
or a return type changed, an object or a base class removed. `true`, or `except` with dotted
patterns of objects allowed to change (`mypkg.experimental.*`). Not evaluated when a package's
API could not be read and nothing else broke.

### `no_new_dependencies`
No package added to the lock file or the declared requirements. `true`, or `allow` with the
package names allowed (patterns: `types-*`). A package only installed because another needs it is
not one the change declares. Not evaluated when a side's declared dependencies cannot be read
without running code (and are not locked), and nothing else was added.

### `no_network`
Head's tests attempt no network access beyond this machine (loopback and Unix sockets are
local). `true`. In a container (L3, L4) the network is blocked and a pass rests on that. In a
contained process (L2) attempts are detected, not blocked: code that bypasses Python's socket
functions escapes detection, so the card adds `network_not_enforced` to a pass.

### `forbidden_paths`
Paths the change must not touch: added, removed, modified or renamed (either name). Patterns are
relative to the repository's root, with `/`: `*` within a path segment, `**` across segments,
`?` one character. A pattern that matches a directory forbids everything under it
(`migrations` and `migrations/` as `migrations/**`); a pattern ending in `/` matches directories
only.

### `perf_budget`
No timed test slower than base by more than `max_regression` (a fraction: `0.2` is 20 %),
`{ max_regression: <number> }`, above 0 and at most 10. Repro times the selected tests that pass
on both sides, base and head interleaved. A test fails the budget when even the low end of its
95 % interval is past it, and the slowdown is significant and above this machine's noise. An
interval past the budget without that is not evaluated. Tests too fast to time (under 5 ms on
both sides) are listed as missing, not passed.

## `claims`
- `require_explicit` (default `false`): a change whose description holds no claim Repro can read
  is UNVERIFIABLE (`no_claims`). Only with agents on, which read the claims.

## `missing`
- `max_uncovered_changed_symbols` (default `0.25`, between 0 and 1): above this share of changed
  functions that no selected test reaches, or whose calls could not be compared, the card is
  UNVERIFIABLE (`coverage`).
