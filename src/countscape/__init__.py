"""Countscape photo countdown wallpaper."""

from importlib.metadata import version


def installed_version() -> str:
    """Return the version from the installed distribution metadata."""
    return version("countscape")
