"""What Repro pins for every run: hash seed, UTF-8 mode, time zone, locale."""

import os
import sys
import time


def test_the_run_is_pinned():
    assert sys.flags.hash_randomization == 0
    assert sys.flags.utf8_mode == 1
    assert os.environ["TZ"] == "UTC"
    assert os.environ["LC_ALL"] == "C.UTF-8"
    assert time.localtime(0).tm_hour == 0  # the epoch, in UTC
