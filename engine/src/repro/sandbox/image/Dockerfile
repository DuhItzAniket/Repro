# Repro's sandbox image (D03): the pinned Python 3.13 + uv image Repro's sandboxes start from,
# with the command-line tools test suites commonly call. A08 found click's pager tests failing
# on both sides for want of `less`; such failures are the environment's, not the change's.
#
#   less    pagers (click, pydoc)
#   git     suites that create repositories of their own in temporary directories
#   procps  ps, used by process-management tests
#   tzdata  the system time-zone database (zoneinfo)
#
# uv is the version Repro pins everywhere else (0.13.0), copied from its image by digest as uv's
# Docker guide recommends; the base image's own uv is older.
#
# Built on demand by repro.sandbox.image and tagged by this file's SHA-256, so a changed file is
# a new image. The Debian packages are the bookworm repository's at build time; the image's ID
# is recorded with each run.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca
COPY --from=ghcr.io/astral-sh/uv@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install --yes --no-install-recommends less git procps tzdata \
    && rm -rf /var/lib/apt/lists/*
