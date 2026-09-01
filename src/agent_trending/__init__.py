"""Agent Trending Weekly."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-trending-daily")
except PackageNotFoundError:  # Source-tree import without an installed package.
    __version__ = "0+unknown"
