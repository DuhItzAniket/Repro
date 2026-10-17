"""The kick-the-tires script's offline parts (J09); the whole run needs Docker and the network,
and its result is in the phase record."""

import pytest

from kick_the_tires import FALLBACK, TASK, pinned_digest, wrong


def test_the_seeded_patch_empties_the_fallback_phrase() -> None:
    gold = f"+            {FALLBACK}\n"
    assert wrong(gold) == '+            status_phrase = ""\n'
    with pytest.raises(SystemExit, match="no longer holds"):
        wrong("+            pass\n")


def test_the_task_is_pinned_among_the_candidates() -> None:
    digest = pinned_digest()
    assert len(digest) == 64
    assert TASK == "pypa__twine-1309"
