# D01 — Sandbox abstraction & process isolation (L0–L2)

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | done |
| **Depends on** | C03, A08 |
| **Branch / PR** | `phase/D01-process-sandbox` · [#38](https://github.com/DuhItzAniket/Repro/pull/38) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Target commands run in a sandbox that states the isolation it actually achieves: their own
process tree with a minimal environment (L0), Repro's detection of network, subprocess and
file-write attempts (L1), and containment of their processes, memory and time (L2). Detected
attempts become evidence.

## Scope
- **`repro.sandbox.ProcessSandbox`** runs a command from a directory, with a minimal environment
  (only the host variables a process needs to start; a fresh home and temporary directory;
  `PYTHONHASHSEED=0`; no bytecode files), a wall-clock timeout and a stop request, and returns
  how it ran: outcome (`exited`, `timeout`, `stopped`), exit status, output (up to a limit),
  whether processes were left running, and the detections.
- **L2, Windows**: a Job Object. The command is created suspended, assigned to the job, then
  resumed, so nothing it starts runs outside it. Job-wide committed memory, an active-process
  limit, kill-on-close, no error dialogs.
- **L2, POSIX**: a new session (so a process group) and resource limits (`RLIMIT_AS`,
  `RLIMIT_NPROC`, no core files) set by a launcher before it `exec`s the command.
- **L1**: `_hook/sitecustomize.py`, first on `PYTHONPATH`, adds an audit hook to every Python
  process of the command and records network (`socket.connect`, `sendto`, `sendmsg`,
  `getaddrinfo`, `gethostbyname`), subprocess (`subprocess.Popen`, `os.system`, `os.exec`,
  `os.posix_spawn`, `os.spawn`, `os.startfile`, `os.fork`) and file-write attempts outside the
  command's directories (`open` for writing, `os.remove`, `os.rename`, `os.rmdir`,
  `shutil.rmtree`), with the pytest test running at the time.
- **Evidence**: one record per distinct attempt, of the new types `subprocess_attempt` and
  `file_attempt` beside `network_attempt`.
- **`sandbox.ready`**: backend `process`, the level achieved (`L2`, or `L1` where containment is
  unavailable) and `network: detected-only`, never more.
- **`repro doctor`**: a `containment` check.

## Out of scope
- Containers, network enforcement, filesystem isolation (L3, D02); provisioning (D03); the
  pytest plugin (D04); running tests on both sides (D06).

## Design notes
- **Created suspended, never raced.** Assigning a running process to a job leaves a window in
  which it can start children outside it. CPython's `Popen` does not keep the primary thread's
  handle, so the process is resumed with the documented Toolhelp32 thread snapshot and
  `ResumeThread`, not the undocumented `NtResumeProcess`.
- **No `preexec_fn`.** Python's documentation warns it is not safe in a program with threads,
  and the engine has several. A launcher (`_rlimits.py`, `python -I -S`) sets the limits and
  `exec`s the command, which keeps its PID.
- **`RLIMIT_NPROC` counts all of the user's threads** (setrlimit(2)), so the launcher counts them
  from `/proc` and allows the configured number on top.
- **The hook is detection only.** Python's audit-hook documentation says hooks are not a
  sandbox, and code that bypasses audited functions is not seen. It never raises into the
  target, records at most 1,000 attempts per process, and its log is read as untrusted:
  malformed records are dropped.
- **Killing only what is ours.** After the command is reaped, its process-group ID could be
  reused, so the group is probed before it is killed, and the unconditional kill is only on the
  exception path. Windows needs no probe: closing the job kills what is in it.
- **A C03 bug found here:** the bus validated `evidence.created` events with the evidence's
  `seq` missing, which only the writer knows, so no evidence could be emitted through the bus.
  It now validates with a placeholder, as it already did for the event's own `seq`.

## Acceptance criteria
- [x] AC1 (roadmap): fork-bomb, memory-hog and timeout fixtures are contained.
- [x] AC2 (roadmap): detected network and subprocess attempts become evidence.
- [x] AC3: the sandbox states the level it achieved: `sandbox.ready` is never above it.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_sandbox.py`: fork bomb (bounded at 127 processes), memory hog (4 GiB against 512 MiB), timeout with a child, processes left running; on Windows and Linux |
| AC2 | `test_sandbox.py`: detections of a connect, a subprocess and a write outside; evidence records validated and emitted through the bus; a flood capped; a tampered log |
| AC3 | `test_sandbox.py`: the ready payload; `test_doctor.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/sandbox/`: `process.py` (the sandbox), `winjob.py` (Job Objects),
  `_rlimits.py` (the POSIX launcher), `_hook/sitecustomize.py` (the audit hook), `detect.py`,
  `evidence.py`, `limits.py`.
- Schema: `EvidenceType` gains `subprocess_attempt` and `file_attempt` (additive).
- `repro.bus`: evidence can be emitted (the C03 fix above). `repro doctor`: `containment`.
- THREAT_MODEL T1, T4 and T12 updated.
- Tests: `test_sandbox.py` (14), `test_bus.py` (+1), `test_doctor.py` updated. pytest 891 → 906
  (904 pass and 2 skip on Windows).

## Evidence
- **Windows** (local): every sandbox test passes. The fork bomb started at most the job's limit
  of processes and all were gone after the timeout. The memory hog failed with `MemoryError`;
  the job's peak was 521 MiB against a 512 MiB limit: what the process committed while
  suspended, before it joined the job, is not counted ("Memory operations performed by the
  process before it was associated with the job are not examined"), about 9 MiB here.
- **Linux**: the same tests pass in `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` as a
  non-root user (43 sandbox and bus tests); CI runs them on Ubuntu too.
- A command that opens a socket, starts a process and writes outside its directory takes
  0.47 s in the sandbox on Windows, and all three attempts are reported; a write inside its own
  directory is not.
- `repro doctor` on Windows: `containment  L2: Job Object`.
- CI run: linked in the PR (#38).

## Deviations from spec
- The roadmap names "audit-hook detection"; subprocess and file-write attempts needed evidence
  types the schema did not have, so `EvidenceType` gained two values (additive: no core field
  and no payload version changes).

## Known gaps
- At L2, filesystem isolation relies on OS permissions; writes outside are detected, not
  prevented (D02).
- On POSIX, a process that starts its own session leaves the process group: it keeps its
  resource limits, but the group kill does not reach it. Containers (D02) close this.
- The hook sees only Python-level attempts in processes that load it: a command run with `-I`
  or `-S`, or a non-Python program, is not watched.

## Dependencies added
None (the standard library: `ctypes`, `resource`, `subprocess`).

## Research notes
- Job Objects: `JOBOBJECT_BASIC_LIMIT_INFORMATION` limit flags (`ACTIVE_PROCESS` 0x8,
  `JOB_MEMORY` 0x200, `DIE_ON_UNHANDLED_EXCEPTION` 0x400, `KILL_ON_JOB_CLOSE` 0x2000) and
  `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `JOBOBJECT_BASIC_ACCOUNTING_INFORMATION`, the
  information classes 1 and 9, `AssignProcessToJobObject` (the handle needs `PROCESS_SET_QUOTA`
  and `PROCESS_TERMINATE`; nested jobs since Windows 8; children join the job by default),
  `THREADENTRY32`, `CreateToolhelp32Snapshot` (`TH32CS_SNAPTHREAD` 0x4), `THREAD_SUSPEND_RESUME`
  0x0002. https://learn.microsoft.com/en-us/windows/win32/api/ (the pages for each)
  **[V]** 2026-10-14
- `setrlimit(2)`: `RLIMIT_AS` is the address space; `RLIMIT_NPROC` limits "the number of
  extant process (or, more precisely on Linux, threads) for the real user ID", and `fork` fails
  with `EAGAIN` at the limit. https://man7.org/linux/man-pages/man2/setrlimit.2.html **[V]**
  2026-10-14
- Python's audit events table: the events and their arguments used by the hook.
  https://docs.python.org/3/library/audit_events.html **[V]** 2026-10-14
- `subprocess`: "The preexec_fn parameter is NOT SAFE to use in the presence of threads in your
  application. The child process could deadlock before exec is called." `start_new_session`
  makes the `setsid()` call in the child.
  https://docs.python.org/3/library/subprocess.html **[V]** 2026-10-14
