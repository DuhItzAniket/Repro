# J09 — Artifact package

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | paused: prepared; the results come with J07–J08, the archive with the owner |
| **Depends on** | J08 |
| **Branch / PR** | `phase/J09-artifact` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
A Zenodo DOI, image digests, a 30-minute kick-the-tires subset, and an AE-ready README
(roadmap). The owner decided (2026-10-18): "I prepare, you submit". This phase prepares; the
owner archives. J07 and J08 have not run (S2 waits for its budget and labels), so this phase
prepares what does not depend on their results, ahead of its place in the order.

## Scope
- **The kick-the-tires subset** (`scripts/kick_the_tires.py`). On one pinned fresh task
  (SWE-rebench `pypa__twine-1309`), with no model and no key, it runs the deterministic
  pipeline:
  - the row checked against its pinned SHA-256;
  - sealing with the image pinned by digest;
  - tier A, B0, and Repro in the task's image.

  It checks four outcomes known in advance.
- **The evaluators' guide** (`docs/paper/ARTIFACT.md`): what is in the artifact, the
  requirements, kick the tires, what needs a model and how cassettes replay it, and what the
  owner checks before archiving.
- **Archive metadata**: `.zenodo.json`, which Zenodo's GitHub integration reads, and
  `CITATION.cff` (cff-version 1.2.0). The author is the GitHub handle: the repository carries
  no personal names, and the owner sets the names before archiving.
- **Image digests**: every sealed task's manifest pins its image by digest (J01). The
  kick-the-tires run prints its manifest's SHA-256.

## Acceptance criteria
- [x] AC1: a kick-the-tires subset that runs in about 30 minutes, without keys.
- [x] AC2: an AE-ready guide.
- [x] AC3: images pinned by digest in the manifest.
- [ ] AC4: a Zenodo DOI. *The owner archives a release.*
- [ ] AC5: the study's data in the archive. *After J07–J08.*

---
*Filled in at the end of the phase:*

## Evidence
- **`scripts/kick_the_tires.py`**, run here (image already pulled), finished in 2 min 10 s with
  all four checks passing:

  | patch | tier A | B0 | Repro |
  |---|---|---|---|
  | gold | PLAUSIBLE | VERIFIED | UNVERIFIABLE |
  | seeded-wrong | INCORRECT_auto | VERIFIED | UNVERIFIABLE |

  Repro's cards are UNVERIFIABLE because twine's suite is order-dependent (J04), and they say
  so. The first pull of the image (about 4.5 GB) adds its own time.
- CI run: linked in the PR.

## Deviations from spec
- Prepared before J07–J08, by the owner's decision to keep going while Stage J waits.

## Dependencies added
None.
