# Release 1.3.1 — the first release archived on Zenodo

| | |
|---|---|
| **Release** | `v1.3.1` |
| **Date** | 2026-10-21 |
| **Kind** | A patch release: no change to Repro's code |

## Why
On 2026-10-21 the owner connected the repository to Zenodo's GitHub integration. Zenodo
archives the releases published after a repository is connected ("new releases from the
repository will be automatically ingested and archived", help.zenodo.org, "Enable a repository",
checked 2026-10-21 **[V]**), so v1.3.0, published the day before, has no record there. This
release is the first Zenodo archives, and gives Repro its DOI. The record's metadata is the
repository's `.zenodo.json`, which Zenodo reads in place of `CITATION.cff` when both exist
(help.zenodo.org, "Describe your software", checked 2026-10-21 **[V]**).

## What it carries
| Part | PRs | What it brought |
|---|---|---|
| CI | [#112](https://github.com/DuhItzAniket/Repro/pull/112) | The Python tests' job may take 45 minutes: on Windows it took 22 to 27 with K08 and K11's tests, and once passed the 30-minute guard |
| Docs | [#113](https://github.com/DuhItzAniket/Repro/pull/113) | The Action's GitHub Marketplace listing, and 1.3.0's install check, in the release record and the Action's guide |

## Published
- The GitHub release `v1.3.1`, with both wheels attached by the release workflow.
- PyPI: `repro-events` and then `repro-engine`, 1.3.1.
- Zenodo: the release's archive and its DOI, added to the README and `CITATION.cff` once
  Zenodo has made them.
