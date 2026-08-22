class CountdownError(Exception):
    """Expected configuration or runtime failure."""


class ConfigError(CountdownError):
    """Invalid configuration."""


class DisplayError(CountdownError):
    """Display discovery or layout failure."""


class PhotoError(CountdownError):
    """Invalid or unavailable photo pool."""


class IntegrationError(CountdownError):
    """GNOME or systemd integration failure."""


class StateError(CountdownError):
    """Missing integrity in a safety-critical state file."""
