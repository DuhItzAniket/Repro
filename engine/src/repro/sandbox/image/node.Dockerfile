# Repro's sandbox image for JavaScript and TypeScript (K11; ADR-0017, phase 4): the official
# Node.js 22 image on Debian bookworm, pinned by digest, with the package managers a lockfile
# names and the command-line tools test suites commonly call.
#
#   npm     the base image's own: 10.9.9, with Node.js 22.23.3
#   pnpm    10.34.7, the newest of pnpm 10, which is JavaScript: pnpm 12 (Repro's own) fetches
#           a native binary the first time it runs, outside Corepack's check
#   yarn    1.22.22 (Yarn classic), the base image's own version
#   git     suites that create repositories of their own in temporary directories
#
# pnpm and Yarn come through Corepack 0.36.0, which Node.js 22 ships. Each is pinned by version
# and by the SHA-512 of its tarball: the npm registry's integrity (`npm view <name>@<version>
# dist.integrity`, as hex), which Corepack checks on download ("Mismatch hashes" otherwise). The
# base image's own Yarn is replaced by Corepack's. A project that names a version of its own
# (package.json's `packageManager`) gets that one, fetched while the install has the network.
# Corepack never writes that field (COREPACK_ENABLE_AUTO_PIN=0) or looks for newer versions
# (COREPACK_DEFAULT_TO_LATEST=0).
#
# The base image's digest is its index's (every platform), read on 2026-10-20 with
#   docker buildx imagetools inspect node:22-bookworm-slim
#
# Built on demand by repro.sandbox.image and tagged by this file's SHA-256, so a changed file is
# a new image. The Debian packages are the bookworm repository's at build time.
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ENV COREPACK_HOME=/opt/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    COREPACK_ENABLE_AUTO_PIN=0 \
    COREPACK_DEFAULT_TO_LATEST=0
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/local/bin/yarn /usr/local/bin/yarnpkg \
    && corepack enable pnpm yarn \
    && corepack install --global \
        pnpm@10.34.7+sha512.ba98abc585539933375b5971f4bc6d6c73a1b4b7edc4a879e7d102fe5423d1e02309d67c60a11f04955093a96e521ad9c3b138cdd654ca5be563f378b3ae48bd \
        yarn@1.22.22+sha512.a6b2f7906b721bba3d67d4aff083df04dad64c399707841b7acf00f6b133b7ac24255f2652fa22ae3534329dc6180534e98d17432037ff6fd140556e2bb3137e \
    && chmod -R a+rX "$COREPACK_HOME"
