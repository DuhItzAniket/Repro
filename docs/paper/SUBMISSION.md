# Submission checklist (for the owner)

> Prepared in J10 (2026-10-18). The owner decided: "I prepare, you submit". Every item below is
> the owner's to tick. The draft is `draft.md`.

## Before the study's results
- [ ] Decide S2's budget (`PREREGISTRATION.md`), have the labels made, and tag `prereg-v1`.
- [ ] Consider a **registered report**. Some venues review the protocol before the results
  (`README.md`, "Venues"). The protocol, guideline and analysis code exist now.

## The venue
- [ ] Choose it. The tracker's near-term fit is **ISSTA 2027**: abstract 8 January 2027, paper
  11 January 2027, both AoE (verified 2026-10-13 on conf.researchr.org).
- [ ] Re-read the call for papers on the day you start formatting: the page limit, the
  template, the review model (double-blind or not), the artifact track, and its policy on AI
  assistance. None of these is checked here.
- [ ] If the review is double-blind: anonymise the repository link (an anonymous mirror or the
  venue's artifact system), and remove self-identifying text and commit metadata from what
  reviewers see.

## The paper
- [ ] Replace §5 of `draft.md` with the results (`python -m repro_bench.analysis` on the frozen
  labels), and the abstract's last sentence.
- [ ] Check every citation against its primary source by hand (`references.bib` notes what is
  still to complete: full author lists, proceedings DOIs).
- [ ] Have someone who has not worked on Repro read it (internal review).
- [ ] Disclose AI assistance as the venue's policy asks.

## The artifact
- [ ] Publish a release; Zenodo archives it from `.zenodo.json` once the repository is linked
  in Zenodo. Check the metadata first (`ARTIFACT.md`, "Archiving"): the creators' names, the
  licence identifier, the description.
- [ ] Cite the DOI in the paper's availability section.
- [ ] Run `scripts/kick_the_tires.py` on a clean machine before the artifact deadline.
