from __future__ import annotations

import math
import os
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from countscape.errors import ConfigError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor

CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class EventConfig:
    label: str
    target: datetime
    timezone: ZoneInfo
    after_arrival_message: str


@dataclass(frozen=True, slots=True)
class WallpaperConfig:
    source_directory: Path
    output_directory: Path
    cache_directory: Path
    countdown_refresh_seconds: int
    photo_rotation_seconds: int
    selection_seed: str
    max_canvas_pixels: int


@dataclass(frozen=True, slots=True)
class StyleConfig:
    font: Path | None
    overlay_position: str
    margin_ratio: float
    font_ratio: float
    photo_fit: str


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    mode: str
    fallback_profile: str | None
    profiles: dict[str, DisplayLayout]


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    state_directory: Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    path: Path
    event: EventConfig
    wallpaper: WallpaperConfig
    style: StyleConfig
    display: DisplayConfig
    runtime: RuntimeConfig


def _xdg_path(variable: str, fallback: Path) -> Path:
    configured = os.environ.get(variable)
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute():
            return candidate.resolve()
    return fallback.expanduser().resolve()


def xdg_config_home() -> Path:
    return _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config")


def xdg_data_home() -> Path:
    return _xdg_path("XDG_DATA_HOME", Path.home() / ".local" / "share")


def xdg_cache_home() -> Path:
    return _xdg_path("XDG_CACHE_HOME", Path.home() / ".cache")


def xdg_state_home() -> Path:
    return _xdg_path("XDG_STATE_HOME", Path.home() / ".local" / "state")


def default_config_path() -> Path:
    return xdg_config_home() / "countscape" / "config.toml"


def default_photo_directory() -> Path:
    return xdg_data_home() / "countscape" / "backgrounds"


def default_output_directory() -> Path:
    return xdg_data_home() / "countscape" / "generated"


def default_cache_directory() -> Path:
    return xdg_cache_home() / "countscape"


def default_state_directory() -> Path:
    return xdg_state_home() / "countscape"


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"missing [{name}] table")
    return value


def _reject_unknown_keys(
    data: dict[str, Any],
    allowed: frozenset[str],
    context: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ConfigError(f"{context} contains unknown configuration keys: {names}")


def _string(data: dict[str, Any], name: str, *, allow_empty: bool = False) -> str:
    value = data.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{name} must be a non-empty string")
    return value


def _integer(
    data: dict[str, Any],
    name: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    value = data.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"{name} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must not be greater than {maximum}")
    return value


def validate_schedule_interval(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{name} must be an integer of at least 1")
    aligned = (value < 60 and 60 % value == 0) or (value >= 60 and value % 60 == 0)
    if not aligned:
        raise ConfigError(
            f"{name} must evenly divide one minute or be a whole number of minutes"
        )
    return value


def _schedule_interval(data: dict[str, Any], name: str) -> int:
    return validate_schedule_interval(_integer(data, name), f"schedule.{name}")


def _number(
    data: dict[str, Any],
    name: str,
    *,
    minimum: float = 0,
    maximum: float | None = None,
) -> float:
    value = data.get(name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ConfigError(f"{name} must be a number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= minimum:
        raise ConfigError(f"{name} must be greater than {minimum}")
    if maximum is not None and converted > maximum:
        raise ConfigError(f"{name} must not be greater than {maximum}")
    return converted


def _coordinate(data: dict[str, Any], name: str) -> float:
    value = data.get(name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ConfigError(f"{name} must be a number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ConfigError(f"{name} must be finite")
    return converted


def _boolean(data: dict[str, Any], name: str) -> bool:
    value = data.get(name)
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _resolve(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _display_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > 160:
        raise ConfigError(f"{name} must be at most 160 characters")
    if any(unicodedata.category(character) == "Cc" for character in cleaned):
        raise ConfigError(f"{name} must not contain control characters or newlines")
    return cleaned


def validate_storage_paths(
    source: Path,
    output: Path,
    cache: Path,
    state: Path,
) -> None:
    paths = {
        "photo": source.resolve(),
        "output": output.resolve(),
        "cache": cache.resolve(),
        "state": state.resolve(),
    }
    home = Path.home().resolve()
    for name in ("output", "cache", "state"):
        path = paths[name]
        if path == Path(path.anchor) or path == home:
            raise ConfigError(f"{name} directory must be a dedicated subdirectory")
    pairs = (
        ("photo", "output"),
        ("photo", "cache"),
        ("photo", "state"),
        ("output", "cache"),
        ("output", "state"),
        ("cache", "state"),
    )
    for first_name, second_name in pairs:
        first = paths[first_name]
        second = paths[second_name]
        if (
            first == second
            or first.is_relative_to(second)
            or second.is_relative_to(first)
        ):
            raise ConfigError(
                f"{first_name} and {second_name} directories must not overlap"
            )


def validate_config_location(
    config_path: Path,
    source: Path,
    output: Path,
    cache: Path,
    state: Path,
) -> None:
    path = config_path.resolve()
    config_directory = path.parent
    for name, directory in (
        ("photo", source),
        ("output", output),
        ("cache", cache),
        ("state", state),
    ):
        root = directory.resolve()
        if (
            config_directory == root
            or config_directory.is_relative_to(root)
            or root.is_relative_to(config_directory)
        ):
            raise ConfigError(f"configuration and {name} directories must not overlap")


def parse_event(
    *,
    label: str,
    target: str | datetime,
    timezone: str | ZoneInfo,
    after_arrival_message: str,
) -> EventConfig:
    clean_label = _display_text(label, "event.label")
    clean_message = _display_text(after_arrival_message, "event.after_arrival_message")

    if isinstance(target, str):
        try:
            parsed = datetime.fromisoformat(target)
        except ValueError as error:
            raise ConfigError(f"invalid event.target: {error}") from error
    elif isinstance(target, datetime):
        parsed = target
    else:
        raise ConfigError("event.target must be an ISO 8601 datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfigError("event.target must include an explicit UTC offset")

    if isinstance(timezone, ZoneInfo):
        zone = timezone
    elif isinstance(timezone, str) and timezone.strip():
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as error:
            raise ConfigError(f"unknown event.timezone: {timezone}") from error
    else:
        raise ConfigError("event.timezone must be a non-empty IANA zone")

    zoned = parsed.astimezone(zone)
    if zoned.replace(tzinfo=None) != parsed.replace(tzinfo=None):
        raise ConfigError("event.target wall time does not agree with event.timezone")
    if zoned.utcoffset() != parsed.utcoffset():
        raise ConfigError("event.target offset does not agree with event.timezone")
    return EventConfig(
        label=clean_label,
        target=zoned,
        timezone=zone,
        after_arrival_message=clean_message,
    )


def _load_event(data: dict[str, Any]) -> EventConfig:
    event = _table(data, "event")
    _reject_unknown_keys(
        event,
        frozenset(
            {
                "label",
                "target",
                "timezone",
                "confirmed",
                "after_arrival_message",
            }
        ),
        "[event]",
    )
    if event.get("confirmed") is not True:
        raise ConfigError("event.confirmed must be true for the configured target")
    return parse_event(
        label=_string(event, "label"),
        target=_string(event, "target"),
        timezone=_string(event, "timezone"),
        after_arrival_message=_string(event, "after_arrival_message"),
    )


def _load_profile(name: str, raw_monitors: object) -> DisplayLayout:
    if not isinstance(raw_monitors, list) or not raw_monitors:
        raise ConfigError(f"display.profiles.{name}.monitors must be a non-empty list")
    monitors: list[LogicalMonitor] = []
    for index, raw in enumerate(raw_monitors):
        if not isinstance(raw, dict):
            raise ConfigError(f"profile {name} monitor {index} must be a table")
        _reject_unknown_keys(
            raw,
            frozenset(
                {
                    "connector",
                    "x",
                    "y",
                    "scale",
                    "transform",
                    "primary",
                    "physical_width",
                    "physical_height",
                }
            ),
            f"display profile {name} monitor {index}",
        )
        connector = _string(raw, "connector")
        scale = _number(raw, "scale", minimum=0.1, maximum=16)
        transform = _integer(raw, "transform", minimum=0)
        if transform > 7:
            raise ConfigError(
                f"profile {name} monitor transform must be between 0 and 7"
            )
        monitor = LogicalMonitor(
            x=_coordinate(raw, "x"),
            y=_coordinate(raw, "y"),
            scale=scale,
            transform=transform,
            primary=_boolean(raw, "primary"),
            connectors=(connector,),
            physical=(
                PhysicalMonitor(
                    connector=connector,
                    width=_integer(raw, "physical_width", maximum=100_000),
                    height=_integer(raw, "physical_height", maximum=100_000),
                ),
            ),
        )
        monitors.append(monitor)
    layout = DisplayLayout(
        monitors=tuple(monitors), layout_mode=1, source=f"profile:{name}"
    )
    layout.validate()
    return layout


def _load_display(data: dict[str, Any]) -> DisplayConfig:
    display = _table(data, "display")
    _reject_unknown_keys(
        display,
        frozenset({"mode", "fallback_profile", "profiles"}),
        "[display]",
    )
    mode = _string(display, "mode")
    if mode not in {"auto", "profile"}:
        raise ConfigError("display.mode must be 'auto' or 'profile'")
    fallback = display.get("fallback_profile")
    if fallback is not None and (not isinstance(fallback, str) or not fallback.strip()):
        raise ConfigError("display.fallback_profile must be a non-empty string")
    raw_profiles = display.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ConfigError("display.profiles must be a table")
    profiles: dict[str, DisplayLayout] = {}
    for name, profile in raw_profiles.items():
        if not isinstance(profile, dict):
            raise ConfigError(f"display profile {name} must be a table")
        _reject_unknown_keys(
            profile,
            frozenset({"monitors"}),
            f"display profile {name}",
        )
        profiles[name] = _load_profile(name, profile.get("monitors"))
    if mode == "profile" and (not fallback or fallback not in profiles):
        raise ConfigError("profile mode requires a valid fallback_profile")
    if fallback and fallback not in profiles:
        raise ConfigError(f"unknown display fallback profile: {fallback}")
    return DisplayConfig(mode=mode, fallback_profile=fallback, profiles=profiles)


def load_config(path: Path | None = None) -> AppConfig:
    requested_path = (path or default_config_path()).expanduser()
    try:
        config_path = requested_path.resolve()
    except OSError as error:
        raise ConfigError(
            f"could not resolve configuration file {requested_path}: {error}"
        ) from error
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(
            f"configuration file does not exist: {config_path}; run countscape init"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error
    except OSError as error:
        raise ConfigError(
            f"could not read configuration file {config_path}: {error}"
        ) from error

    schema_version = data.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != CONFIG_SCHEMA_VERSION
    ):
        raise ConfigError(
            "configuration uses an unsupported schema; "
            "run countscape init --force to replace the pre-release configuration"
        )

    _reject_unknown_keys(
        data,
        frozenset(
            {
                "schema_version",
                "runtime",
                "event",
                "display",
                "wallpaper",
                "schedule",
                "selection",
                "style",
            }
        ),
        "configuration root",
    )

    wallpaper = _table(data, "wallpaper")
    runtime = _table(data, "runtime")
    schedule = _table(data, "schedule")
    selection = _table(data, "selection")
    style = _table(data, "style")
    _reject_unknown_keys(
        wallpaper,
        frozenset(
            {
                "source_directory",
                "output_directory",
                "cache_directory",
                "max_canvas_pixels",
            }
        ),
        "[wallpaper]",
    )
    _reject_unknown_keys(
        runtime,
        frozenset({"state_directory"}),
        "[runtime]",
    )
    _reject_unknown_keys(
        schedule,
        frozenset({"countdown_refresh_seconds", "photo_rotation_seconds"}),
        "[schedule]",
    )
    _reject_unknown_keys(selection, frozenset({"seed"}), "[selection]")
    _reject_unknown_keys(
        style,
        frozenset(
            {"font", "overlay_position", "margin_ratio", "font_ratio", "photo_fit"}
        ),
        "[style]",
    )
    root = config_path.parent
    source_directory = _resolve(root, _string(wallpaper, "source_directory"))
    output_directory = _resolve(root, _string(wallpaper, "output_directory"))
    cache_directory = _resolve(root, _string(wallpaper, "cache_directory"))
    state_directory = _resolve(root, _string(runtime, "state_directory"))
    validate_storage_paths(
        source_directory,
        output_directory,
        cache_directory,
        state_directory,
    )
    validate_config_location(
        config_path,
        source_directory,
        output_directory,
        cache_directory,
        state_directory,
    )

    overlay_position = _string(style, "overlay_position")
    if overlay_position not in {"center", "bottom"}:
        raise ConfigError("style.overlay_position must be 'center' or 'bottom'")
    photo_fit = _string(style, "photo_fit")
    if photo_fit not in {"contain", "cover"}:
        raise ConfigError("style.photo_fit must be 'contain' or 'cover'")
    raw_font = style.get("font")
    if not isinstance(raw_font, str):
        raise ConfigError("style.font must be a string")

    return AppConfig(
        path=config_path,
        event=_load_event(data),
        wallpaper=WallpaperConfig(
            source_directory=source_directory,
            output_directory=output_directory,
            cache_directory=cache_directory,
            countdown_refresh_seconds=_schedule_interval(
                schedule, "countdown_refresh_seconds"
            ),
            photo_rotation_seconds=_schedule_interval(
                schedule, "photo_rotation_seconds"
            ),
            selection_seed=_string(selection, "seed"),
            max_canvas_pixels=_integer(
                wallpaper,
                "max_canvas_pixels",
                maximum=100_000_000,
            ),
        ),
        style=StyleConfig(
            font=_resolve(root, raw_font) if raw_font else None,
            overlay_position=overlay_position,
            margin_ratio=_number(style, "margin_ratio", maximum=0.25),
            font_ratio=_number(style, "font_ratio", maximum=0.5),
            photo_fit=photo_fit,
        ),
        display=_load_display(data),
        runtime=RuntimeConfig(state_directory=state_directory),
    )
