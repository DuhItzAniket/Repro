# C05 — Git layer: refs, diffs, worktrees, snapshots

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | in progress |
| **Depends on** | C01 |
| **Branch / PR** | `phase/C05-git-layer` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
Repro can read any commit of a target repository safely: resolve the refs a run names, know
exactly which lines changed between base and head, and copy a commit's files into a `.git`-less
snapshot that is byte-for-byte the commit, on Windows as on Linux.

## Scope
- **Running git** (`repro.gitops.git`): every command gets `-c core.longpaths=true` (CLAUDE.md:
  per command, the user's configuration is never changed) and is hardened against the target
  repository's own configuration: hooks are pointed at an empty directory, `core.fsmonitor` is
  off, diffs use `--no-ext-diff --no-textconv`, and nothing prompts (`GIT_TERMINAL_PROMPT=0`).
  Command-line `-c` settings take precedence over a repository's `.git/config`.
- **Refs**: a ref (branch, tag, SHA, `HEAD`, also on a detached `HEAD`) resolves to a full commit
  SHA, or an error naming it; the merge base of base and head.
- **Diffs** (`repro.gitops.changes`): the files that changed (added, modified, deleted, renamed with
  similarity, type or mode changes, binary) from `git diff --raw -z` (exact paths, whatever they
  contain), and each text file's changed line ranges on both sides from `-U0` hunk headers.
- **Snapshots** (`repro.gitops.snapshot`): a commit's tree written to a directory without `.git`,
  from `git ls-tree` and `git cat-file --batch`: the committed bytes exactly (CRLF stays CRLF; no
  attributes, filters or line-ending conversion), executable bits on POSIX. Entries that cannot be
  written safely are skipped and listed, never written elsewhere: paths with `..`, `.git` (in any
  case), drive letters, `:`, `\`, control characters, Windows device names or trailing dots or
  spaces; symbolic links on Windows; submodules. A size limit guards the disk (THREAT_MODEL T4).
  Long paths work on Windows (extended-length paths).
- **Worktrees** (`repro.gitops.worktree`): `git worktree add --detach` for host-side static reads
  (THREAT_MODEL T3), and cleanup that survives Windows: `worktree remove --force`, then deleting
  what is left with retries while locked files are released, clearing read-only bits, then
  `worktree prune`.

## Out of scope
- Which snapshot runs where (Stage D); symbols from changed lines (C06); fetching from remotes.

## Design notes
- **Not `git archive`.** The roadmap named `git archive` for snapshots, but git documents that
  "attributes are by default taken from the `.gitattributes` files in the tree that is being
  archived", and that files with `export-ignore` "won't be added to archive files"
  [V: https://git-scm.com/docs/git-archive, checked 2026-10-14]. A project that marks its tests
  `export-ignore`, a common way to slim release archives, would be snapshotted without them, and
  `export-subst` would rewrite files. Reading the tree object gives the commit as it is. The goal
  (a `.git`-less snapshot) is unchanged.
- One `git cat-file --batch` process streams every blob, so a snapshot costs two git processes
  however many files the commit has.

## Acceptance criteria
- [x] AC1 (roadmap): tests cover long paths, spaces, CRLF repositories, detached HEADs and
      locked-file cleanup on Windows.
- [x] AC2: a snapshot is byte-for-byte the commit, ignores `.gitattributes`, and never writes
      outside its directory.
- [x] AC3: diffs report every change kind with exact paths and changed line ranges.
- [x] AC4: the target repository's hooks and fsmonitor never run.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_gitops_*.py` on the CI runners (Ubuntu, Windows); the locked-file test runs on Windows |
| AC2 | `test_gitops_snapshot.py` (bytes and modes compared with `git cat-file`; `export-ignore`; unsafe tree entries from a crafted tree) |
| AC3 | `test_gitops_diff.py` |
| AC4 | `test_gitops_git.py`: a repository whose hooks and fsmonitor would leave a marker file |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/gitops/`: `git.py`, `changes.py` (diffs), `snapshot.py`, `worktree.py`;
  THREAT_MODEL gains T17 and T18.
- Tests: `test_gitops_snapshot.py` (25), `test_gitops_diff.py` (16), `test_gitops_git.py` (10),
  `test_gitops_worktree.py` (5), and `gitrepo.py`, which builds trees with `git mktree`: git's
  index refuses names such as `..`, `.git`, `con` or `a:b` ("Ignoring path"), but `mktree`
  writes them, so a hostile repository can contain them. pytest 749 → 805 (803 pass and 2 skip
  on Windows: two POSIX-only tests).

## Evidence
- Windows (local): every hostile entry is skipped and nothing appears beside the snapshot; a
  path over 300 characters is written; `README`/`readme` and a file/directory pair collide on
  NTFS and are skipped; a worktree file held open for 0.6 s is waited for and the worktree
  removed; one never released is reported, git forgets the worktree anyway, and cleanup finishes
  once the handle closes.
- The hooks test first proves the trap is real: plain `git worktree add` runs the planted
  hooks on this machine; then resolve, diff, snapshot, worktree add/remove and status through
  `Git` run none of them.
- Diffs keep exact paths with spaces, quotes, a tab, a newline, a backslash, glob characters,
  a leading dash and non-ASCII text.
- CI run: linked in the PR.

## Deviations from spec
- Snapshots are written from the tree object rather than with `git archive` (see Design notes):
  `git archive` honours the archived tree's `export-ignore` and `export-subst` attributes.

## Known gaps
- Symbolic links are not created on Windows (they need a privilege); they are skipped and listed.
- Submodules are skipped: their commits are not in the repository.
- Line ranges are for text files; binary files and type changes report none.

## Dependencies added
None.

## Research notes
