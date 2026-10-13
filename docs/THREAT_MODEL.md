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
| T1 | Target code opens network connections (exfiltration, nondeterminism) | A1, A3 | L3 container `--network none`. L1 detection records attempts as evidence. The card reports `enforced` vs `detected-only` | D01–D02 | Without Docker, network is detected but not blocked, and the card says so |
| T2 | Target code reads or writes host files | A1, A3 | Container with read-only root, tmpfs, snapshot copied into a volume, no host mounts other than the read-only cache | D02 | At L0–L2, filesystem isolation relies on OS permissions only. Stated on the card |
| T3 | Tampering with host `.git` via linked worktree | A1 | Target code runs only from `.git`-less snapshots. Worktrees are used only for host-side static reads | C05, D02 | None known |
| T4 | Resource exhaustion (fork bomb, memory, disk, infinite loop) | A1 | Job Objects / cgroups, pids/memory/cpu limits, wall-clock timeouts, disk quota on volumes | D01–D02 | Short-lived host slowdown before limits kick in |
| T5 | Malicious build/install scripts | A3 | Provision inside the sandbox. Egress limited to the package index or offline wheels. `--no-build` where possible | D03 | Index-only egress still permits contacting the index |
| T6 | uv cache poisoning via hardlinks | A1, A3 | `--link-mode copy` in sandboxes, read-only cache mount | D03 | None known |
| T7 | Prompt injection alters agent behaviour | A2 | `tools=[]` with read-only `mcp__repro__*` tools only. `dontAsk` plus a deny hook. `setting_sources=[]`. Scratch `cwd`. Delimited untrusted text. `verbatim_prompts` | G01, G03 | The model may still be persuaded to a wrong verdict. Mitigated by T8 controls |
| T8 | Agent issues an unsupported or forged verdict | A2 | Evidence-ID enum schema, exact-quote validation, consistency check against deterministic evidence, deterministic status rules, order-swap/panel for contradicted verdicts | G05, G08, F04 | A verdict that is wrong but validly cited remains possible. The deterministic evidence is shown next to it |
| T9 | PR weakens the policy it is judged by | A1 | `repro.yml` read from base. Head changes to policy become flagged gap items | F01 | None known |
| T10 | PR weakens or deletes tests to pass | A1 | Test-file diff (`test_change` evidence). Base versions of modified tests run on head | D06 | Subtle assertion weakening may evade the heuristics. Reviewers see the test diff |
| T11 | Target manipulates traces or results (writes fake observation files, patches the tracer) | A1 | Container results directory is collected and validated against schema. Tracer state lives in the plugin's private module. Anomalies (missing or extra files, schema errors) become missing items, never passes | D04, E01 | In-process code can interfere with the tracer. Evidence from a hostile run is tagged with the isolation level and anomaly flags |
| T12 | Secrets leak into events, logs, cards or PR comments | — | Minimal sandbox env (no host env vars). Bus-level secret scrubbing. Gitleaks in CI. API keys read only by the agents module | A06, C03, H03 | Secrets embedded in target repo content may appear in evidence snippets. Snippets are scrubbed with the same patterns |
| T13 | Local process abuses Repro's API | A4 | Bind to 127.0.0.1, per-session token for WS/REST (from H03), no state-changing endpoints without the token | C04, H03 | Same-user malware is out of scope |
| T14 | Untrusted pickles or objects deserialised on the host | A1 | Observations are CBOR/JSON only. Pickle is never unpickled. Encoder output is data, not code | E02–E03 | None known |
| T15 | Code-executing analysers on the host (griffe inspection, jedi) | A1 | griffe `allow_inspection=False`. Executing analysers run only inside the sandbox | C06, E05 | None known |

## 5. What the card must state
Isolation level achieved (L0–L4), network (`enforced` / `detected-only`), platform (native or
Linux container), and any anomaly flags from T11. A card never implies more isolation than was
actually in place.

## 6. Out of scope (for now)
Same-user malware on the host. Hardware side channels. Supply-chain compromise of Repro's own
dependencies, beyond dependency review and pinning (A06). Multi-tenant hosting (a non-goal).
