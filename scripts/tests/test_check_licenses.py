import pytest

from check_licenses import normalise, spdx_allowed


@pytest.mark.parametrize(
    "expression",
    [
        "MIT",
        "Apache-2.0",
        "MIT OR Apache-2.0",
        "Apache-2.0 OR BSD-2-Clause",
        "(MIT OR GPL-3.0-only) AND Apache-2.0",
        "Apache-2.0 WITH LLVM-exception",
        "MPL-2.0",
    ],
)
def test_allowed_expressions(expression: str) -> None:
    assert spdx_allowed(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-3.0-only",
        "AGPL-3.0-or-later",
        "MIT AND GPL-2.0-only",
        "SSPL-1.0",
        "",
        "LicenseRef-Proprietary",
        "MIT OR",  # malformed
    ],
)
def test_disallowed_or_malformed_expressions(expression: str) -> None:
    assert not spdx_allowed(expression)


def test_trove_and_free_text_names_map_to_spdx() -> None:
    assert normalise("MIT License") == "MIT"
    assert normalise("Mozilla Public License 2.0 (MPL 2.0)") == "MPL-2.0"
    assert normalise("ISC License (ISCL)") == "ISC"
