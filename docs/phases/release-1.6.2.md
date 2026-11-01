# Release 1.6.2 — unchanged test cases, and how to choose the AI reviewers

| | |
|---|---|
| **Release** | `v1.6.2` |
| **Date** | 2026-11-01 |
| **Kind** | A patch release: one fix and documentation, no new feature, no breaking change |

## What it carries
| Part | PRs | What it brought |
|---|---|---|
| Fix | [#140](https://github.com/DuhItzAniket/Repro/pull/140) | Each parametrized case's own parameters get a digest in the pytest plugin; a case whose test changed only in its `parametrize` lists, with the same ID and digest on both sides, is kept, not `modified`. Found on Lectris PR #11, where 31 old cases were `modified` and a reviewer contradicted the true claim that no existing case changed |
| Docs | [#141](https://github.com/DuhItzAniket/Repro/pull/141) | The README, the GitHub Action's guide and the PyPI page: how to turn the AI reviewers on, the three backends, choosing a model, the budget |

## Compatibility
- No event schema or store change. Logs written by 1.6.1 read and replay as before.
- The coverage map's format is now 4, so cached maps are made again on the next run.
- A case whose parameters are not plain built-in values gets no digest and stays `modified`, as
  before.

## Published
Filled in after the tag: the GitHub release, PyPI and Zenodo.
