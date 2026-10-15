# Repro — Threat Model

Repro runs code it does not trust and feeds text it does not trust to LLMs. A security failure
would harm the user's machine, and a falsely positive verdict undermines the reason Repro
exists. This model is reviewed at every stage gate and formally in phase H03.

## 1. Assets
| Asset | Why it matters |
|---|---|
| Host machine (files, processes, credentials) | Target code must not escape to it |
| Host repository and its `.git` (config, hooks) | Tampering could execute code on the user's next git command |
| Secrets: Anthropic API key, GitHub token, environment | Must never reach target code, events, logs, cards or PR comments |
| Verdict integrity | A forged or manipulated VERIFIED is the worst product failure |
| Event logs and evidence | Basis of every verdict and of replay |
| Shared caches (uv cache, environment images) | Poisoning affects later runs |

## 2. Adversaries
- **A1 Malicious or careless PR content:** code, tests, build scripts, dependencies.
- **A2 Prompt injection:** instructions hidden in the PR description, commit messages, code
  comments, docstrings, file names or test output.
- **A3 Compromised dependency:** malicious sdist build or install hook in the target's
  dependency tree.
- **A4 Network observer / local process:** another process on the machine connecting to
  Repro's API.
- **A5 Hostile web page:** a site the user visits while Repro serves, scripting the user's own
  browser against `127.0.0.1` (C04).

## 3. Trust boundaries
```
 host engine (trusted) ──snapshot copy──► sandbox (untrusted target code)
 host engine ──rendered evidence + delimited PR text──► LLM (untrusted output)
 host engine ──127.0.0.1──► browser UI
 CI runner ──token──► GitHub API
```

## 4. Threats and mitigations

| ID | Threat | Adversary | Mitigation | Phase | Residual risk |
|---|---|---|---|---|---|
| T1 | Target code opens network connections (exfiltration, nondeterminism) | A1, A3 | L3 container `--network none` (D02; the escape suite's raw `_socket`, `ctypes` libc and subprocess attempts are blocked, and the attempts Python sees are still recorded). L1 detection records attempts as evidence: since D01 an audit hook loaded into every Python process of the command reports network, subprocess and file-write attempts (`network_attempt`, `subprocess_attempt`, `file_attempt` evidence). The card reports `enforced` vs `detected-only` | D01–D02 | Without Docker, network is detected but not blocked, and the card says so. The detection log is written inside the target's own processes, so it can be falsified or bypassed (C extensions, `ctypes`): malformed records are dropped, and no detection never proves no attempt |
| T2 | Target code reads or writes host files | A1, A3 | Container with read-only root, an `exec` tmpfs at `/tmp`, the commit streamed into a volume of its own from its tree object, all capabilities dropped, `no-new-privileges`, uid 1000, and no host mounts other than Repro's audit hook (read-only) and, from D03, the read-only cache; results are read back with `docker cp` | D02 | At L0–L2, filesystem isolation relies on OS permissions only. Stated on the card |
| T3 | Tampering with host `.git` via linked worktree | A1 | Target code runs only from `.git`-less snapshots. Worktrees are used only for host-side static reads. At L3 no `.git` is reachable from the container at all, and the escape suite checks the host repository's `.git` is unchanged | C05, D02 | None known |
| T4 | Resource exhaustion (fork bomb, memory, disk, infinite loop) | A1 | D01: on Windows a Job Object (created suspended, assigned, resumed) with job-wide memory, an active-process limit and kill-on-close; on POSIX a new session and resource limits (`RLIMIT_AS`, `RLIMIT_NPROC`, no core files) set by a launcher before `exec`; a wall-clock timeout kills the whole tree, and processes left when the command ends are killed and reported. Tested with bounded fork-bomb, memory-hog and timeout fixtures on both OSes. D02: container pids/memory/cpu limits, disk quota on volumes | D01–D02 | Short-lived host slowdown before limits kick in. At L2 on POSIX, a process that starts its own session leaves the process group (it keeps its resource limits), and `RLIMIT_NPROC` counts the user's other threads too |
| T5 | Malicious build/install scripts | A3 | D03: provisioning is two steps. The dependencies are installed from wheels only (`--no-build`), from the index Repro names, with uv's configuration files ignored, so no build code runs while the network is on; requirements that name anything but the index (URLs, paths, VCS, pip options) are refused beforehand. The project itself is then built offline, in the sandbox | D03 | The dependency step's network is not limited at the network layer: what it may fetch is limited by refusing every other source beforehand. A dependency with no wheel makes the run UNVERIFIABLE (`environment_failed`) |
| T6 | uv cache poisoning via hardlinks | A1, A3 | `--link-mode copy` everywhere. uv cannot use a read-only cache (D03), so nothing a target can write is shared: the shared, cached thing is the dependencies' environment, built before any target code runs and copied for each side, and each side's uv cache is its own and thrown away | D03 | None known |
| T7 | Prompt injection alters agent behaviour | A2 | `tools=[]` with read-only `mcp__repro__*` tools only. `dontAsk` plus a deny hook. `setting_sources=[]`. Scratch `cwd`. Delimited untrusted text. `verbatim_prompts` | G01, G03 | The model may still be persuaded to a wrong verdict. Mitigated by T8 controls |
| T8 | Agent issues an unsupported or forged verdict | A2 | Evidence-ID enum schema, exact-quote validation, consistency check against deterministic evidence, deterministic status rules, order-swap/panel for contradicted verdicts | G05, G08, F04 | A verdict that is wrong but validly cited remains possible. The deterministic evidence is shown next to it |
| T9 | PR weakens the policy it is judged by | A1 | `repro.yml` read from base. Head changes to policy become flagged gap items | F01 | None known |
| T10 | PR weakens or deletes tests to pass | A1 | Test-file diff (`test_change` evidence): removed tests, added skips and xfails, fewer or weaker assertions, widened `pytest.raises`. Base versions of modified tests run on head, from a copy of head's snapshot with base's test files written over it (paths checked to stay inside it) | D06 | Subtle assertion weakening may evade the heuristics. Reviewers see the test diff |
| T11 | Target manipulates traces or results (writes fake observation files, patches the tracer) | A1 | Container results directory is collected and validated against schema. Tracer state lives in the plugin's private module. Anomalies (missing or extra files, schema errors) become missing items, never passes. D04: the results file is read with bounds (64 MiB, 200,000 records, 2,000 characters a field); malformed records are counted, not trusted; a run without its session record is incomplete, never passing. D05: a test's map comes from the same process; a forged map could drop a test from selection or hide a coverage gap, so it is bounded and validated the same way, and its places must name files inside the snapshot | D04, D05, E01 | In-process code can interfere with the tracer. Evidence from a hostile run is tagged with the isolation level and anomaly flags |
| T12 | Secrets leak into events, logs, cards or PR comments | — | Minimal sandbox env (D01: only the host variables a process needs to start, a fresh home and temporary directory). Bus-level secret scrubbing. Gitleaks in CI. API keys read only by the agents module | A06, C03, H03 | Secrets embedded in target repo content may appear in evidence snippets. Snippets are scrubbed with the same patterns. E04: values leave the sandbox as text only as previews of the calls a reproducer run names (at most 512 characters each, through the same scrubbing); every other observation is digests |
| T13 | Local process abuses Repro's API | A4 | Bind to 127.0.0.1 (`repro serve` refuses other addresses until H03), per-session token for WS/REST (from H03), no state-changing endpoints without the token (C04 has none) | C04, H03 | Same-user malware is out of scope. Until H03, any local process can read runs through the API |
| T17 | The target repository's configuration or a committed hooks directory makes git run its programs on the host (`core.hooksPath` set by a hook manager, `core.fsmonitor`, diff drivers) | A1 | Every git command runs with `-c core.hooksPath=<empty dir>` and `-c core.fsmonitor=false`, which take precedence over the repository's config; diffs use `--no-ext-diff --no-textconv`; snapshots read tree objects (no filters). Tested with planted hooks and an fsmonitor command | C05 | A git vulnerability in object parsing itself |
| T18 | Crafted tree entries write outside a snapshot or alias other files (`..`, `.git`, `GIT~1`, drive letters, `:` streams, `\`, device names, trailing dots or spaces, case collisions, escaping symlinks) | A1 | Each entry is checked before anything is written; unsafe ones are skipped and listed, never written elsewhere; symlinks are created only on POSIX and only inside the snapshot | C05 | Skipped entries are files the run cannot use; they are reported |
| T16 | A web page in the user's browser reads the local API: cross-site WebSocket hijacking, or DNS rebinding of its own domain to 127.0.0.1 | A5 | A WebSocket handshake carrying an `Origin` must match an allow-list (the server's own origins and explicit `--allow-origin`); every request must name a local `Host` | C04 | A page served from an allow-listed origin can read runs |
| T14 | Untrusted pickles or objects deserialised on the host | A1 | Observations are CBOR/JSON only. Pickle is never unpickled. Encoder output is data, not code. E01: the tracer sends only digests and type names, never values; the encoder runs in the target's process and walks exact builtin types only, so no user `__eq__`, `__repr__`, `__iter__` or property runs to observe a value. E02: objects, builtin subclasses and exceptions are read through the interpreter's own descriptors (taken from `type`, `object`, `BaseException`), never through the value's or class's attribute lookup; a hostile-object corpus and Hypothesis mixtures check that none of the target's code runs | E01–E03 | A class with its own `__dict__` or slot descriptors is encoded by type only (a missed difference, never target code run). E03: observation artifacts are a deterministic CBOR subset with no tags; the reader refuses anything else (it re-encodes and compares), and the trace file is capped in the sandbox and on reading |
| T15 | Code-executing analysers on the host (griffe inspection, jedi) | A1 | griffe `allow_inspection=False`. Executing analysers run only inside the sandbox. E05: griffe reads files written from git to a scratch tree, never the target's environment; a test package that raises on import (and would write a marker) proves nothing ran. Installed sets are listed inside each side's sandbox, by its interpreter with `-I -S` (metadata files only) | C06, E05 | None known |
| T19 | Static analysis on the host resolves a target name through the import system and runs target code: a target package named like an already-imported module (`logging`, `grimp`, `repro`) or placed on `sys.path` before a lazy import, or analyses files outside the tree (symlinks, `..`) | A1 | Symbols and non-package imports are read with `ast` from blobs. grimp runs as `python -I -S` in its own process, over a tree written from regular-file blobs only (no symlinks; each path checked as in T18), and is handed each package's directory through its package-finder setting: the tree is never on `sys.path` and no target name is resolved with `find_spec`. Tested with shadowing names and an `__init__.py` that would leave a marker if run | C07 | grimp's own parser (Rust) reading hostile source |

## 5. What the card must state
Isolation level achieved (L0–L4), network (`enforced` / `detected-only`), platform (native or
Linux container), and any anomaly flags from T11. A card never implies more isolation than was
actually in place.

## 6. Out of scope (for now)
Same-user malware on the host. Hardware side channels. Supply-chain compromise of Repro's own
dependencies, beyond dependency review and pinning (A06). Multi-tenant hosting (a non-goal).
