"""Helpers for command-line tests."""

import os
import socket
from pathlib import Path


def clean_env(tmp_path: Path, **variables: str) -> dict[str, str]:
    """The real environment without REPRO_* variables, with the data under ``tmp_path``."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("REPRO_")}
    return {**env, "REPRO_DATA_DIR": str(tmp_path / "data"), **variables}


def free_port() -> int:
    """A loopback port nothing listens on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
