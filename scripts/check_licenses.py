"""Licence allow-list check for every installed Python distribution and pnpm package.

Usage:  uv run python scripts/check_licenses.py

Exit status 1 lists every package whose licence is not on the allow-list or cannot be
determined. Unknown licences are failures, not passes. Exceptions must be listed in
EXCEPTIONS with a justification.
"""

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions

# Permissive licences, plus OFL-1.1 (fonts) and MPL-2.0 (file-level copyleft that does not
# affect our Apache-2.0 code when the dependency is used unmodified).
ALLOWED = frozenset(
    {
        "0BSD", "Apache-2.0", "BlueOak-1.0.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0",
        "CC-BY-4.0", "ISC", "MIT", "MIT-0", "MPL-2.0", "OFL-1.1", "PSF-2.0", "Python-2.0",
        "Unlicense", "Zlib",
    }
)  # fmt: skip

# Trove classifiers and free-text licence fields seen in the wild, mapped to SPDX ids.
ALIASES = {
    "mit license": "MIT",
    "mit": "MIT",
    "bsd license": "BSD-3-Clause",  # generic "BSD"; every BSD variant is permissive
    "bsd": "BSD-3-Clause",
    "isc license (iscl)": "ISC",
    "isc license": "ISC",
    "isc": "ISC",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
}

# name -> justification. Keep empty unless a dependency genuinely needs it.
EXCEPTIONS: dict[str, str] = {}

FIRST_PARTY = frozenset({"repro-engine", "repro-bench", "repro-events", "repro-workspace"})


@dataclass(frozen=True)
class Finding:
    ecosystem: str
    name: str
    version: str
    license: str
    problem: str


def spdx_allowed(expression: str) -> bool:
    """Evaluate an SPDX expression (AND/OR/WITH, parentheses) against the allow-list."""
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    position = 0

    def parse_or() -> bool:
        nonlocal position
        result = parse_and()
        while position < len(tokens) and tokens[position].upper() == "OR":
            position += 1
            right = parse_and()
            result = result or right
        return result

    def parse_and() -> bool:
        nonlocal position
        result = parse_atom()
        while position < len(tokens) and tokens[position].upper() == "AND":
            position += 1
            right = parse_atom()
            result = result and right
        return result

    def parse_atom() -> bool:
        nonlocal position
        if position >= len(tokens) or tokens[position].upper() in {"AND", "OR", "WITH", ")"}:
            raise ValueError(expression)
        item = tokens[position]
        position += 1
        if item == "(":
            inner = parse_or()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError(expression)
            position += 1
            return inner
        if position < len(tokens) and tokens[position].upper() == "WITH":
            if position + 1 >= len(tokens):
                raise ValueError(expression)
            position += 2  # licence exceptions only grant extra permissions
        return item.removesuffix("+") in ALLOWED

    try:
        result = parse_or()
    except ValueError:
        return False  # malformed expressions are never allowed
    return result and position == len(tokens)


def normalise(raw: str) -> str:
    text = raw.strip()
    return ALIASES.get(text.lower(), text)


def python_license(dist: Distribution) -> str:
    metadata = dist.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return str(expression)
    classifiers = [
        normalise(c.split(" :: ")[-1])
        for c in (metadata.get_all("Classifier") or [])
        if c.startswith("License ::")
    ]
    if classifiers:
        return " OR ".join(sorted(set(classifiers)))
    free_text = (metadata.get("License") or "").strip().splitlines()
    return normalise(free_text[0]) if free_text else ""


def check_python() -> Iterable[Finding]:
    for dist in distributions():
        name = dist.metadata["Name"]
        if name in FIRST_PARTY or name in EXCEPTIONS:
            continue
        license_ = python_license(dist)
        if not license_:
            yield Finding("python", name, dist.version, "", "licence unknown")
        elif not spdx_allowed(license_):
            yield Finding("python", name, dist.version, license_, "not on the allow-list")


def check_pnpm() -> Iterable[Finding]:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        yield Finding("npm", "pnpm", "", "", "pnpm not found; cannot check JS licences")
        return
    # Fixed argument list and a resolved executable path; no untrusted input reaches the call.
    output = subprocess.run(  # noqa: S603
        [pnpm, "licenses", "list", "--json", "--recursive"],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout
    for license_, packages in json.loads(output).items():
        for package in packages:
            name = package["name"]
            if name in EXCEPTIONS:
                continue
            version = ",".join(package.get("versions", []))
            if license_ in {"", "Unknown", "UNLICENSED"}:
                yield Finding("npm", name, version, license_, "licence unknown")
            elif not spdx_allowed(normalise(license_)):
                yield Finding("npm", name, version, license_, "not on the allow-list")


def main() -> int:
    findings = sorted([*check_python(), *check_pnpm()], key=lambda f: (f.ecosystem, f.name.lower()))
    for f in findings:
        sys.stderr.write(f"{f.ecosystem}: {f.name} {f.version}: {f.license!r} - {f.problem}\n")
    if findings:
        sys.stderr.write(
            f"{len(findings)} licence problem(s). Allowed: {', '.join(sorted(ALLOWED))}\n"
        )
        return 1
    sys.stdout.write("licences: all dependencies are on the allow-list\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
