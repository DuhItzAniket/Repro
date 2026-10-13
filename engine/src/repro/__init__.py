"""Repro engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("repro-engine")
except PackageNotFoundError:  # imported from a source tree that was never installed
    __version__ = "0+unknown"
