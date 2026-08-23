from __future__ import annotations

import json
import math
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from countscape.config import (
    CONFIG_SCHEMA_VERSION,
    AppConfig,
    DisplayConfig,
    RuntimeConfig,
    StyleConfig,
    WallpaperConfig,
    default_cache_directory,
    default_config_path,
    default_output_directory,
    default_photo_directory,
    default_state_directory,
    load_config,
    parse_event,
    validate_config_location,
    validate_schedule_interval,
    validate_storage_paths,
    xdg_cache_home,
    xdg_config_home,
    xdg_data_home,
)
from countscape.display import build_canvas_layout
from countscape.errors import ConfigError, IntegrationError, StateError
from countscape.gnome import current_background_paths, restore_background
from countscape.mutter import discover_layout
from countscape.photos import scan_photo_pool
from countscape.render import (
    GENERATED_CALIBRATION_NAME,
    GENERATED_WALLPAPER_NAME,
    resolve_font,
)
from countscape.state import (
    OWNERSHIP_MARKER,
    atomic_write_json,
    atomic_write_text,
    ensure_owned_directory,
    operation_lock,
    read_json_strict,
    validate_owned_directory,
)

SERVICE_NAME = "countscape.service"
TIMER_NAME = "countscape.timer"
INSTALL_MANIFEST_SCHEMA_VERSION = 2
Runner = Callable[..., subprocess.CompletedProcess[str]]
_OUTPUT_RESERVED = frozenset({".countscape.lock", "render-state.json"})
_CACHE_RESERVED = frozenset({"base.png", "base.json"})
_TIMER_WANTS_DIRECTORY = "graphical-session.target.wants"
_UNIT_HEADER = (
    "# Managed by Countscape. Changes will be replaced by `countscape install`."
)
_INSTALL_MANIFEST_KEYS = frozenset(
    {
        "application",
        "schema_version",
        "installation_id",
        "package_version",
        "ownership_id",
        "config_path",
        "runtime_state_directory",
        "unit_directory",
        "unit_link_directory",
        "service_path",
        "timer_path",
        "output_directory",
        "cache_directory",
        "python_executable",
        "service_sha256",
        "timer_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class PackageEnvironment:
    python: Path
    version: str


@dataclass(frozen=True, slots=True)
class InstallManifest:
    installation_id: str
    package_version: str
    ownership_id: str
    config_path: Path
    runtime_state_directory: Path
    unit_directory: Path
    unit_link_directory: Path
    service_path: Path
    timer_path: Path
    output_directory: Path
    cache_directory: Path
    python_executable: Path
    service_sha256: str
    timer_sha256: str

    def as_json(self) -> dict[str, object]:
        return {
            "application": "countscape",
            "schema_version": INSTALL_MANIFEST_SCHEMA_VERSION,
            "installation_id": self.installation_id,
            "package_version": self.package_version,
            "ownership_id": self.ownership_id,
            "config_path": str(self.config_path),
            "runtime_state_directory": str(self.runtime_state_directory),
            "unit_directory": str(self.unit_directory),
            "unit_link_directory": str(self.unit_link_directory),
            "service_path": str(self.service_path),
            "timer_path": str(self.timer_path),
            "output_directory": str(self.output_directory),
            "cache_directory": str(self.cache_directory),
            "python_executable": str(self.python_executable),
            "service_sha256": self.service_sha256,
            "timer_sha256": self.timer_sha256,
        }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def dump_config(config: AppConfig, *, seed: str | None = None) -> str:
    selection_seed = seed or config.wallpaper.selection_seed
    lines = [
        f"schema_version = {CONFIG_SCHEMA_VERSION}",
        "",
        "[runtime]",
        f"state_directory = {_toml_string(str(config.runtime.state_directory))}",
        "",
        "[event]",
        f"label = {_toml_string(config.event.label)}",
        f"target = {_toml_string(config.event.target.isoformat())}",
        f"timezone = {_toml_string(config.event.timezone.key)}",
        "confirmed = true",
        f"after_arrival_message = {_toml_string(config.event.after_arrival_message)}",
        "",
        "[display]",
        f"mode = {_toml_string(config.display.mode)}",
    ]
    if config.display.fallback_profile:
        lines.append(
            f"fallback_profile = {_toml_string(config.display.fallback_profile)}"
        )
    for name, layout in config.display.profiles.items():
        for monitor in layout.monitors:
            if len(monitor.physical) != 1:
                raise ConfigError("configured profiles cannot contain mirrored members")
            physical = monitor.physical[0]
            lines.extend(
                [
                    "",
                    f"[[display.profiles.{_toml_string(name)}.monitors]]",
                    f"connector = {_toml_string(physical.connector)}",
                    f"x = {monitor.x}",
                    f"y = {monitor.y}",
                    f"scale = {monitor.scale}",
                    f"transform = {monitor.transform}",
                    f"primary = {'true' if monitor.primary else 'false'}",
                    f"physical_width = {physical.width}",
                    f"physical_height = {physical.height}",
                ]
            )
    lines.extend(
        [
            "",
            "[wallpaper]",
            (
                "source_directory = "
                f"{_toml_string(str(config.wallpaper.source_directory))}"
            ),
            (
                "output_directory = "
                f"{_toml_string(str(config.wallpaper.output_directory))}"
            ),
            f"cache_directory = {_toml_string(str(config.wallpaper.cache_directory))}",
            f"max_canvas_pixels = {config.wallpaper.max_canvas_pixels}",
            "",
            "[schedule]",
            (
                "countdown_refresh_seconds = "
                f"{config.wallpaper.countdown_refresh_seconds}"
            ),
            f"photo_rotation_seconds = {config.wallpaper.photo_rotation_seconds}",
            "",
            "[selection]",
            f"seed = {_toml_string(selection_seed)}",
            "",
            "[style]",
            (
                f"font = {_toml_string(str(config.style.font))}"
                if config.style.font
                else 'font = ""'
            ),
            f"overlay_position = {_toml_string(config.style.overlay_position)}",
            f"margin_ratio = {config.style.margin_ratio}",
            f"font_ratio = {config.style.font_ratio}",
            f"photo_fit = {_toml_string(config.style.photo_fit)}",
            "",
        ]
    )
    return "\n".join(lines)


def _positive_interval(value: int, name: str) -> int:
    return validate_schedule_interval(value, name)


def initialize_config(
    *,
    target: str,
    timezone: str,
    label: str = "Until the big day",
    after_arrival_message: str = "It's here!",
    source_directory: Path | None = None,
    output_directory: Path | None = None,
    cache_directory: Path | None = None,
    state_directory: Path | None = None,
    countdown_refresh_seconds: int = 60,
    photo_rotation_seconds: int = 600,
    config_path: Path | None = None,
    force: bool = False,
) -> Path:
    path = (config_path or default_config_path()).expanduser().resolve()
    if path.exists() and not force:
        raise ConfigError(f"configuration already exists: {path}; use --force")
    prior_seed: str | None = None
    if path.exists():
        try:
            prior_config = load_config(path)
        except ConfigError:
            prior_config = None
        if prior_config is not None:
            prior_seed = prior_config.wallpaper.selection_seed
            prior_state = prior_config.runtime.state_directory
            integration_paths = (
                prior_state / "install.json",
                prior_state / "gnome-background.json",
                prior_state / "systemd" / SERVICE_NAME,
                prior_state / "systemd" / TIMER_NAME,
            )
            if any(
                candidate.exists() or candidate.is_symlink()
                for candidate in integration_paths
            ):
                raise ConfigError(
                    "configuration has active or unresolved integration state; "
                    "run countscape uninstall before countscape init --force"
                )
    event = parse_event(
        label=label,
        target=target,
        timezone=timezone,
        after_arrival_message=after_arrival_message,
    )
    photos = (source_directory or default_photo_directory()).expanduser().resolve()
    output = (output_directory or default_output_directory()).expanduser().resolve()
    cache = (cache_directory or default_cache_directory()).expanduser().resolve()
    state = (state_directory or default_state_directory()).expanduser().resolve()
    config = AppConfig(
        path=path,
        event=event,
        wallpaper=WallpaperConfig(
            source_directory=photos,
            output_directory=output,
            cache_directory=cache,
            countdown_refresh_seconds=_positive_interval(
                countdown_refresh_seconds, "schedule.countdown_refresh_seconds"
            ),
            photo_rotation_seconds=_positive_interval(
                photo_rotation_seconds, "schedule.photo_rotation_seconds"
            ),
            selection_seed=prior_seed or secrets.token_hex(16),
            max_canvas_pixels=100_000_000,
        ),
        style=StyleConfig(
            font=None,
            overlay_position="bottom",
            margin_ratio=0.05,
            font_ratio=0.055,
            photo_fit="contain",
        ),
        display=DisplayConfig(mode="auto", fallback_profile=None, profiles={}),
        runtime=RuntimeConfig(state_directory=state),
    )
    validate_storage_paths(photos, output, cache, state)
    validate_config_location(path, photos, output, cache, state)
    photos.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, dump_config(config))
    load_config(path)
    return path


def configure_settings(
    config_path: Path,
    *,
    overlay_position: str | None = None,
    photo_fit: str | None = None,
    source_directory: Path | None = None,
    countdown_refresh_seconds: int | None = None,
    photo_rotation_seconds: int | None = None,
    event_label: str | None = None,
    event_target: str | None = None,
    event_timezone: str | None = None,
    after_arrival_message: str | None = None,
) -> Path:
    requested = (
        overlay_position,
        photo_fit,
        source_directory,
        countdown_refresh_seconds,
        photo_rotation_seconds,
        event_label,
        event_target,
        event_timezone,
        after_arrival_message,
    )
    if all(value is None for value in requested):
        raise ConfigError("configure requires at least one setting")
    if overlay_position is not None and overlay_position not in {"center", "bottom"}:
        raise ConfigError("style.overlay_position must be 'center' or 'bottom'")
    if photo_fit is not None and photo_fit not in {"contain", "cover"}:
        raise ConfigError("style.photo_fit must be 'contain' or 'cover'")

    config = load_config(config_path)
    zone = event_timezone or config.event.timezone.key
    if event_target is None:
        try:
            target_zone = ZoneInfo(zone)
        except ZoneInfoNotFoundError as error:
            raise ConfigError(f"unknown event.timezone: {zone}") from error
        target = config.event.target.astimezone(target_zone).isoformat()
    else:
        target = event_target
    event = parse_event(
        label=event_label if event_label is not None else config.event.label,
        target=target,
        timezone=zone,
        after_arrival_message=(
            after_arrival_message
            if after_arrival_message is not None
            else config.event.after_arrival_message
        ),
    )
    wallpaper = replace(
        config.wallpaper,
        source_directory=(
            source_directory.expanduser().resolve()
            if source_directory is not None
            else config.wallpaper.source_directory
        ),
        countdown_refresh_seconds=(
            _positive_interval(
                countdown_refresh_seconds, "schedule.countdown_refresh_seconds"
            )
            if countdown_refresh_seconds is not None
            else config.wallpaper.countdown_refresh_seconds
        ),
        photo_rotation_seconds=(
            _positive_interval(
                photo_rotation_seconds, "schedule.photo_rotation_seconds"
            )
            if photo_rotation_seconds is not None
            else config.wallpaper.photo_rotation_seconds
        ),
    )
    validate_storage_paths(
        wallpaper.source_directory,
        wallpaper.output_directory,
        wallpaper.cache_directory,
        config.runtime.state_directory,
    )
    validate_config_location(
        config.path,
        wallpaper.source_directory,
        wallpaper.output_directory,
        wallpaper.cache_directory,
        config.runtime.state_directory,
    )
    updated = replace(
        config,
        event=event,
        wallpaper=wallpaper,
        style=replace(
            config.style,
            overlay_position=overlay_position or config.style.overlay_position,
            photo_fit=photo_fit or config.style.photo_fit,
        ),
    )
    atomic_write_text(updated.path, dump_config(updated))
    load_config(updated.path)
    return updated.path


def set_overlay_position(config_path: Path, position: str) -> Path:
    return configure_settings(config_path, overlay_position=position)


def _systemd_quote(value: str | Path) -> str:
    raw = str(value)
    if any(character in raw for character in ("\x00", "\n", "\r")):
        raise ConfigError("systemd command paths must not contain control characters")
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "$$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def unit_contents(
    executable: Path,
    config_path: Path,
    *,
    countdown_refresh_seconds: int = 60,
    photo_rotation_seconds: int = 600,
) -> tuple[str, str]:
    countdown_refresh_seconds = _positive_interval(
        countdown_refresh_seconds, "schedule.countdown_refresh_seconds"
    )
    photo_rotation_seconds = _positive_interval(
        photo_rotation_seconds, "schedule.photo_rotation_seconds"
    )
    service = "\n".join(
        [
            _UNIT_HEADER,
            "[Unit]",
            "Description=Countscape photo countdown wallpaper",
            "After=graphical-session.target",
            "PartOf=graphical-session.target",
            "",
            "[Service]",
            "Type=oneshot",
            (
                f"ExecStart={_systemd_quote(executable)} -m countscape apply "
                f"--config {_systemd_quote(config_path)} --retries 3"
            ),
            "",
        ]
    )
    polling_seconds = math.gcd(
        countdown_refresh_seconds,
        photo_rotation_seconds,
    )
    calendar = (
        f"*-*-* *:*:00/{polling_seconds}" if polling_seconds < 60 else "*-*-* *:*:00"
    )
    timer_lines = [
        _UNIT_HEADER,
        "[Unit]",
        "Description=Update Countscape photo countdown wallpaper",
        "After=graphical-session.target",
        "PartOf=graphical-session.target",
        "",
        "[Timer]",
        "OnActiveSec=1s",
        f"OnCalendar={calendar}",
    ]
    timer_lines.extend(
        [
            "AccuracySec=1s",
            "Persistent=true",
            f"Unit={SERVICE_NAME}",
            "",
            "[Install]",
            "WantedBy=graphical-session.target",
            "",
        ]
    )
    return service, "\n".join(timer_lines)


def _systemctl(
    arguments: list[str],
    *,
    runner: Runner = subprocess.run,
    tolerate_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            ["systemctl", "--user", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if tolerate_failure:
            return subprocess.CompletedProcess(arguments, 1, "", str(error))
        raise IntegrationError(f"systemctl failed: {error}") from error
    if result.returncode != 0 and not tolerate_failure:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise IntegrationError(f"systemctl {' '.join(arguments)} failed: {detail}")
    return result


def _required_manifest_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise IntegrationError(f"Countscape install manifest has invalid {key}")
    return value


def _manifest_path(
    data: dict[str, object],
    key: str,
    *,
    resolve_symlinks: bool = True,
) -> Path:
    raw = _required_manifest_string(data, key)
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise IntegrationError(f"Countscape install manifest {key} must be absolute")
    normalized = (
        candidate.resolve() if resolve_symlinks else Path(os.path.abspath(candidate))
    )
    if str(normalized) != raw:
        raise IntegrationError(f"Countscape install manifest {key} is not normalized")
    return normalized


def _manifest_digest(data: dict[str, object], key: str) -> str:
    value = _required_manifest_string(data, key)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise IntegrationError(f"Countscape install manifest has invalid {key}")
    return value


def _parse_manifest(data: dict[str, object]) -> InstallManifest:
    if (
        set(data) != _INSTALL_MANIFEST_KEYS
        or data.get("application") != "countscape"
        or not isinstance(data.get("schema_version"), int)
        or isinstance(data.get("schema_version"), bool)
        or data.get("schema_version") != INSTALL_MANIFEST_SCHEMA_VERSION
    ):
        raise IntegrationError(
            "Countscape install manifest uses an unsupported schema; "
            "pre-release install state is not migrated"
        )
    installation_id = _required_manifest_string(data, "installation_id")
    if len(installation_id) != 32 or any(
        character not in "0123456789abcdef" for character in installation_id
    ):
        raise IntegrationError(
            "Countscape install manifest has invalid installation_id"
        )
    runtime_state_directory = _manifest_path(data, "runtime_state_directory")
    unit_directory = _manifest_path(data, "unit_directory")
    unit_link_directory = _manifest_path(
        data,
        "unit_link_directory",
        resolve_symlinks=False,
    )
    service_path = _manifest_path(data, "service_path")
    timer_path = _manifest_path(data, "timer_path")
    if service_path != unit_directory / SERVICE_NAME:
        raise IntegrationError("Countscape install manifest has invalid service_path")
    if timer_path != unit_directory / TIMER_NAME:
        raise IntegrationError("Countscape install manifest has invalid timer_path")
    if unit_directory != runtime_state_directory / "systemd":
        raise IntegrationError("Countscape install manifest has invalid unit_directory")
    if (
        unit_link_directory.name != "user"
        or unit_link_directory.parent.name != "systemd"
        or unit_link_directory == Path.home().resolve()
    ):
        raise IntegrationError(
            "Countscape install manifest has invalid unit_link_directory"
        )
    return InstallManifest(
        installation_id=installation_id,
        package_version=_required_manifest_string(data, "package_version"),
        ownership_id=_required_manifest_string(data, "ownership_id"),
        config_path=_manifest_path(data, "config_path"),
        runtime_state_directory=runtime_state_directory,
        unit_directory=unit_directory,
        unit_link_directory=unit_link_directory,
        service_path=service_path,
        timer_path=timer_path,
        output_directory=_manifest_path(data, "output_directory"),
        cache_directory=_manifest_path(data, "cache_directory"),
        python_executable=_manifest_path(
            data,
            "python_executable",
            resolve_symlinks=False,
        ),
        service_sha256=_manifest_digest(data, "service_sha256"),
        timer_sha256=_manifest_digest(data, "timer_sha256"),
    )


def _read_manifest(path: Path) -> InstallManifest | None:
    try:
        data = read_json_strict(path)
    except StateError as error:
        raise IntegrationError(str(error)) from error
    return _parse_manifest(data) if data is not None else None


def _content_digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def _validate_unit_ownership(
    path: Path,
    expected_digest: object,
) -> None:
    if path.is_symlink():
        raise IntegrationError(f"refusing symbolic-link systemd unit: {path}")
    if not path.exists():
        return
    try:
        contents = path.read_bytes()
    except OSError as error:
        raise IntegrationError(
            f"could not inspect systemd unit {path}: {error}"
        ) from error
    digest = sha256(contents).hexdigest()
    if (
        not contents.startswith(b"# Managed by Countscape.")
        or digest != expected_digest
    ):
        raise IntegrationError(f"systemd unit is not owned by this install: {path}")


def _manager_unit_path(
    unit_name: str,
    *,
    runner: Runner,
) -> Path | None:
    properties = ("LoadState", "FragmentPath", "Names", "DropInPaths")
    result = _systemctl(
        [
            "show",
            "--all",
            *(f"--property={name}" for name in properties),
            unit_name,
        ],
        runner=runner,
        tolerate_failure=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise IntegrationError(
            f"could not query systemd user unit {unit_name}: {detail}"
        )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            raise IntegrationError(
                f"systemd returned malformed unit metadata for {unit_name}"
            )
        key, value = line.split("=", 1)
        if key not in properties or key in values:
            raise IntegrationError(
                f"systemd returned unexpected unit metadata for {unit_name}"
            )
        values[key] = value
    if set(values) != set(properties):
        raise IntegrationError(
            f"systemd returned incomplete unit metadata for {unit_name}"
        )
    if values["DropInPaths"].strip():
        raise IntegrationError(f"systemd unit {unit_name} has unsupported drop-ins")
    names = frozenset(values["Names"].split())
    if names - {unit_name}:
        raise IntegrationError(f"systemd unit {unit_name} has unsupported aliases")
    if names != {unit_name}:
        raise IntegrationError(f"systemd unit {unit_name} has invalid names")
    load_state = values["LoadState"].strip()
    raw = values["FragmentPath"].strip()
    if load_state == "not-found":
        if raw:
            raise IntegrationError(
                f"systemd unit {unit_name} has inconsistent not-found metadata"
            )
        return None
    if load_state != "loaded":
        raise IntegrationError(
            f"systemd unit {unit_name} has unsupported load state: "
            f"{load_state or 'empty'}"
        )
    if not raw:
        raise IntegrationError(
            f"systemd unit {unit_name} has inconsistent loaded metadata"
        )
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise IntegrationError(
            f"systemd returned a non-absolute unit path for {unit_name}"
        )
    return candidate.resolve()


def _validate_manager_unit(
    unit_name: str,
    expected_path: Path,
    *,
    runner: Runner,
    allow_missing: bool,
) -> bool:
    actual = _manager_unit_path(unit_name, runner=runner)
    if actual is None:
        if allow_missing:
            return False
        raise IntegrationError(f"systemd did not load the linked unit {unit_name}")
    if actual != expected_path.resolve():
        raise IntegrationError(
            f"systemd unit {unit_name} is linked to a foreign path: {actual}"
        )
    return True


def _unit_link_spec(
    unit_link_directory: Path,
    service_path: Path,
    timer_path: Path,
) -> tuple[tuple[Path, Path], ...]:
    return (
        (
            unit_link_directory / _TIMER_WANTS_DIRECTORY / TIMER_NAME,
            timer_path,
        ),
        (unit_link_directory / TIMER_NAME, timer_path),
        (unit_link_directory / SERVICE_NAME, service_path),
    )


def _effective_user_unit_roots(
    recorded_root: Path,
    *,
    runner: Runner,
) -> tuple[Path, ...]:
    command = ["systemd-analyze", "--user", "unit-paths"]
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntegrationError(
            f"could not discover systemd user-unit paths: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise IntegrationError(f"could not discover systemd user-unit paths: {detail}")
    roots: list[Path] = []
    home = _resolved_link(Path.home(), description="home directory")

    def append_root(candidate: Path, *, display: str) -> None:
        normalized = Path(os.path.abspath(candidate))
        if (
            not candidate.is_absolute()
            or candidate != normalized
            or str(normalized) != display
        ):
            raise IntegrationError(
                f"systemd returned an unsafe user-unit path: {display}"
            )
        resolved = _resolved_link(candidate, description="systemd user-unit root")
        if resolved in {Path(resolved.anchor), home}:
            raise IntegrationError(
                f"systemd returned an unsafe user-unit path: {display}"
            )
        if resolved not in roots:
            roots.append(resolved)

    for line in result.stdout.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if raw != line:
            raise IntegrationError(f"systemd returned an unsafe user-unit path: {raw}")
        append_root(Path(raw), display=raw)
    if not roots:
        raise IntegrationError("systemd returned no user-unit paths")
    append_root(recorded_root, display=str(recorded_root))
    return tuple(roots)


def _resolved_link(path: Path, *, description: str) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as error:
        raise IntegrationError(
            f"could not inspect {description} {path}: {error}"
        ) from error


def _validate_unit_link_topology(
    unit_link_directory: Path,
    service_path: Path,
    timer_path: Path,
    *,
    service_linked: bool | None,
    timer_linked: bool | None,
    runner: Runner,
) -> tuple[tuple[Path, Path], ...]:
    spec = _unit_link_spec(unit_link_directory, service_path, timer_path)
    recorded_scan_root = _resolved_link(
        unit_link_directory,
        description="recorded systemd user-unit root",
    )
    allowed_scan_paths = {
        recorded_scan_root / path.relative_to(unit_link_directory)
        for path, _target in spec
    }
    managed_unit_names = {SERVICE_NAME, TIMER_NAME}
    managed_drop_in_names = {f"{name}.d" for name in managed_unit_names}
    managed_sources = {service_path.resolve(), timer_path.resolve()}
    captured: list[tuple[Path, Path]] = []
    for path, expected_target in spec:
        if path.is_symlink():
            actual = _resolved_link(path, description="systemd user-unit link")
            if actual != expected_target.resolve():
                raise IntegrationError(
                    f"systemd user-unit link has a foreign target: {path}"
                )
            captured.append((path, expected_target))
        elif path.exists():
            raise IntegrationError(f"systemd user-unit link is not symbolic: {path}")

    for root in _effective_user_unit_roots(unit_link_directory, runner=runner):
        try:
            root.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise IntegrationError(
                f"could not inspect systemd user-unit topology {root}: {error}"
            ) from error
        scan_errors: list[OSError] = []
        try:
            candidates = tuple(
                Path(directory) / name
                for directory, directories, filenames in os.walk(
                    root,
                    followlinks=False,
                    onerror=scan_errors.append,
                )
                for name in (*directories, *filenames)
            )
        except OSError as error:
            raise IntegrationError(
                f"could not inspect systemd user-unit topology {root}: {error}"
            ) from error
        if scan_errors:
            error = scan_errors[0]
            raise IntegrationError(
                f"could not inspect systemd user-unit topology {root}: {error}"
            ) from error
        for candidate in candidates:
            if candidate in allowed_scan_paths:
                continue
            if candidate.name in managed_unit_names:
                raise IntegrationError(
                    f"unsupported external Countscape systemd unit: {candidate}"
                )
            if candidate.name in managed_drop_in_names:
                raise IntegrationError(
                    f"unsupported Countscape systemd drop-in topology: {candidate}"
                )
            if not candidate.is_symlink():
                continue
            target = _resolved_link(candidate, description="systemd user-unit link")
            if target in managed_sources:
                raise IntegrationError(
                    f"unsupported Countscape systemd alias or runtime link: {candidate}"
                )

    captured_paths = {path for path, _target in captured}
    direct_service = unit_link_directory / SERVICE_NAME
    direct_timer = unit_link_directory / TIMER_NAME
    wants_timer = unit_link_directory / _TIMER_WANTS_DIRECTORY / TIMER_NAME
    if service_linked is not None and service_linked != (
        direct_service in captured_paths
    ):
        raise IntegrationError("unsupported Countscape service link topology")
    if timer_linked is not None and timer_linked != (direct_timer in captured_paths):
        raise IntegrationError("unsupported Countscape timer link topology")
    if wants_timer in captured_paths and direct_timer not in captured_paths:
        raise IntegrationError("unsupported Countscape timer enablement topology")
    return tuple(captured)


def _unlink_unit_links(links: tuple[tuple[Path, Path], ...]) -> None:
    for path, expected_target in links:
        if not path.is_symlink():
            raise IntegrationError(
                f"systemd user-unit link changed during lifecycle operation: {path}"
            )
        actual = _resolved_link(path, description="systemd user-unit link")
        if actual != expected_target.resolve():
            raise IntegrationError(
                f"systemd user-unit link changed to a foreign target: {path}"
            )
        _unlink_managed_file(path)


def _remove_exact_file(
    path: Path,
    expected: bytes,
    *,
    description: str,
) -> str | None:
    """Remove a file created by this transaction only when it is unchanged."""
    if path.is_symlink():
        return f"preserved symbolic-link {description}: {path}"
    try:
        contents = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        return f"could not inspect {description} {path}: {error}"
    if contents != expected:
        return f"preserved changed {description}: {path}"
    try:
        path.unlink()
    except OSError as error:
        return f"could not remove {description} {path}: {error}"
    return None


def _read_managed_text(path: Path, *, description: str) -> str | None:
    if path.is_symlink():
        raise IntegrationError(f"refusing symbolic-link {description}: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise IntegrationError(
            f"could not read {description} {path}: {error}"
        ) from error


def _restore_prior_generation(
    files: tuple[tuple[Path, str | None, str, str], ...],
) -> list[str]:
    """Restore exact prior text without overwriting a concurrent change."""
    failures: list[str] = []
    for path, prior, published, description in reversed(files):
        if path.is_symlink():
            failures.append(f"preserved symbolic-link {description}: {path}")
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        except (OSError, UnicodeError) as error:
            failures.append(f"could not inspect {description} {path}: {error}")
            continue
        if current == prior:
            continue
        if current != published:
            failures.append(f"preserved changed {description}: {path}")
            continue
        try:
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, prior)
        except OSError as error:
            failures.append(f"could not restore {description} {path}: {error}")
    return failures


def _rollback_first_install(
    *,
    manifest_path: Path,
    manifest_data: dict[str, object],
    unit_link_directory: Path,
    service_path: Path,
    service: str,
    timer_path: Path,
    timer: str,
    newly_linked_candidates: tuple[tuple[str, Path], ...],
    runner: Runner,
) -> list[str]:
    """Best-effort rollback without removing files not created by this attempt."""
    failures: list[str] = []
    linked_units: list[tuple[str, Path]] = []
    for unit_name, expected_path in newly_linked_candidates:
        try:
            linked = _validate_manager_unit(
                unit_name,
                expected_path,
                runner=runner,
                allow_missing=True,
            )
        except IntegrationError as error:
            failures.append(str(error))
            continue
        if linked:
            linked_units.append((unit_name, expected_path))

    if newly_linked_candidates:
        try:
            captured_links = _validate_unit_link_topology(
                unit_link_directory,
                service_path,
                timer_path,
                service_linked=None,
                timer_linked=None,
                runner=runner,
            )
        except IntegrationError as error:
            failures.append(str(error))
            return failures
        linked_names = {unit_name for unit_name, _path in linked_units}
        for unit_name in (TIMER_NAME, SERVICE_NAME):
            if unit_name not in linked_names:
                continue
            stopped = _systemctl(
                ["stop", unit_name],
                runner=runner,
                tolerate_failure=True,
            )
            if stopped.returncode != 0:
                detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
                failures.append(f"could not stop new user unit {unit_name}: {detail}")
        if failures:
            return failures
        try:
            _unlink_unit_links(captured_links)
        except IntegrationError as error:
            failures.append(str(error))
            return failures
        reloaded = _systemctl(["daemon-reload"], runner=runner, tolerate_failure=True)
        if reloaded.returncode != 0:
            detail = reloaded.stderr.strip() or f"exit {reloaded.returncode}"
            failures.append(f"could not reload systemd during rollback: {detail}")
            return failures

    links_remaining = False
    for unit_name, expected_path in newly_linked_candidates:
        try:
            linked = _validate_manager_unit(
                unit_name,
                expected_path,
                runner=runner,
                allow_missing=True,
            )
        except IntegrationError as error:
            failures.append(str(error))
            links_remaining = True
        else:
            if linked:
                failures.append(f"new user-unit link remains loaded: {unit_name}")
                links_remaining = True

    # Keep the source files and manifest together if systemd still references them.
    if links_remaining:
        return failures

    file_failures = [
        failure
        for failure in (
            _remove_exact_file(
                service_path,
                service.encode(),
                description="service source",
            ),
            _remove_exact_file(
                timer_path,
                timer.encode(),
                description="timer source",
            ),
        )
        if failure is not None
    ]
    failures.extend(file_failures)
    if not file_failures:
        manifest_text = json.dumps(manifest_data, indent=2, sort_keys=True) + "\n"
        manifest_failure = _remove_exact_file(
            manifest_path,
            manifest_text.encode(),
            description="install manifest",
        )
        if manifest_failure is not None:
            failures.append(manifest_failure)
    return failures


def _installed_package_environment() -> PackageEnvironment:
    try:
        installed = distribution("countscape")
    except PackageNotFoundError as error:
        raise IntegrationError(
            "install requires Countscape to be installed with `uv tool install`"
        ) from error
    direct_url = installed.read_text("direct_url.json")
    if direct_url:
        try:
            metadata = json.loads(direct_url)
        except json.JSONDecodeError as error:
            raise IntegrationError(
                "installed Countscape has invalid direct URL metadata"
            ) from error
        if not isinstance(metadata, dict):
            raise IntegrationError(
                "installed Countscape has invalid direct URL metadata"
            )
        directory = metadata.get("dir_info")
        if isinstance(directory, dict) and directory.get("editable") is True:
            raise IntegrationError(
                "install refuses an editable or source-checkout environment; "
                "install Countscape with `uv tool install`"
            )

    environment = Path(sys.prefix).expanduser().absolute()
    python = Path(sys.executable).expanduser().absolute()
    configured_tool_directory = os.environ.get("UV_TOOL_DIR")
    tool_directory = (
        Path(configured_tool_directory).expanduser().absolute()
        if configured_tool_directory
        else xdg_data_home() / "uv" / "tools"
    )
    configured_cache_directory = os.environ.get("UV_CACHE_DIR")
    cache_directory = (
        Path(configured_cache_directory).expanduser().absolute()
        if configured_cache_directory
        else xdg_cache_home() / "uv"
    )
    if environment == cache_directory or environment.is_relative_to(cache_directory):
        raise IntegrationError(
            "install refuses an ephemeral `uvx` environment; "
            "install Countscape with `uv tool install`"
        )
    if environment.parent != tool_directory:
        raise IntegrationError(
            "install requires a durable `uv tool install` environment; "
            "the active environment is outside the uv tool directory"
        )
    receipt = environment / "uv-receipt.toml"
    if receipt.is_symlink() or not receipt.is_file():
        raise IntegrationError(
            "install requires a durable `uv tool install` environment; "
            "editable checkouts and ephemeral `uvx` environments are unsupported"
        )
    if not python.is_relative_to(environment) or not python.is_file():
        raise IntegrationError(
            "installed Python executable is outside the durable tool environment"
        )
    package_location = Path(installed.locate_file("")).expanduser().absolute()
    if not package_location.is_relative_to(environment):
        raise IntegrationError(
            "installed Countscape package is outside the durable tool environment"
        )
    if not isinstance(installed.version, str) or not installed.version:
        raise IntegrationError("installed Countscape has no package version")
    return PackageEnvironment(python=python, version=installed.version)


def _runtime_state_directory(
    requested: Path,
    *,
    config: AppConfig | None = None,
) -> Path:
    path = requested.expanduser().resolve()
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise IntegrationError(
            f"runtime state must use a dedicated subdirectory: {path}"
        )
    if config is not None:
        for name, managed in (
            ("photo", config.wallpaper.source_directory),
            ("output", config.wallpaper.output_directory),
            ("cache", config.wallpaper.cache_directory),
        ):
            directory = managed.resolve()
            if (
                path == directory
                or path.is_relative_to(directory)
                or directory.is_relative_to(path)
            ):
                raise IntegrationError(
                    f"runtime state and {name} directories must not overlap"
                )
        if config.path == path or config.path.is_relative_to(path):
            raise IntegrationError(
                "configuration must not be stored inside the runtime state directory"
            )
    return path


def install(
    *,
    config_path: Path | None = None,
    start: bool = True,
    runner: Runner = subprocess.run,
    _environment: PackageEnvironment | None = None,
) -> Path:
    config = load_config(config_path)

    # Preflight before changing user integration.
    scan_photo_pool(config.wallpaper.source_directory)
    layout = discover_layout(config.display)
    build_canvas_layout(layout, max_pixels=config.wallpaper.max_canvas_pixels)
    resolve_font(config.style.font)
    environment = _environment or _installed_package_environment()
    python = environment.python.expanduser().absolute()
    if not python.is_file():
        raise IntegrationError(f"installed Python executable is missing: {python}")

    state_dir = _runtime_state_directory(config.runtime.state_directory, config=config)
    manifest_path = state_dir / "install.json"
    prior_manifest = _read_manifest(manifest_path)
    first_install = prior_manifest is None
    prior_service: str | None = None
    prior_timer: str | None = None
    prior_manifest_text: str | None = None
    current_unit_link_directory = xdg_config_home() / "systemd" / "user"
    if prior_manifest is None:
        unit_dir = state_dir / "systemd"
        unit_link_directory = current_unit_link_directory
        service_path = unit_dir / SERVICE_NAME
        timer_path = unit_dir / TIMER_NAME
        for path in (service_path, timer_path):
            if path.exists() or path.is_symlink():
                raise IntegrationError(
                    f"refusing to replace foreign systemd unit: {path}"
                )
        installation_id = secrets.token_hex(16)
    else:
        if prior_manifest.runtime_state_directory != state_dir:
            raise IntegrationError(
                "existing install uses a different runtime state directory"
            )
        expected_identity = (
            ("configuration", prior_manifest.config_path, config.path),
            (
                "output directory",
                prior_manifest.output_directory,
                config.wallpaper.output_directory,
            ),
            (
                "cache directory",
                prior_manifest.cache_directory,
                config.wallpaper.cache_directory,
            ),
        )
        for name, installed_value, requested_value in expected_identity:
            if installed_value != requested_value:
                raise IntegrationError(
                    f"existing install uses a different {name}; "
                    "uninstall it before changing installation ownership"
                )
        if prior_manifest.ownership_id != config.wallpaper.selection_seed:
            raise IntegrationError(
                "existing install belongs to a different configuration identity"
            )
        unit_dir = prior_manifest.unit_directory
        unit_link_directory = prior_manifest.unit_link_directory
        service_path = prior_manifest.service_path
        timer_path = prior_manifest.timer_path
        _validate_unit_ownership(
            service_path,
            prior_manifest.service_sha256,
        )
        _validate_unit_ownership(
            timer_path,
            prior_manifest.timer_sha256,
        )
        prior_service = _read_managed_text(
            service_path,
            description="service source",
        )
        prior_timer = _read_managed_text(
            timer_path,
            description="timer source",
        )
        prior_manifest_text = _read_managed_text(
            manifest_path,
            description="install manifest",
        )
        if prior_manifest_text is None:
            raise IntegrationError("Countscape install manifest disappeared")
        installation_id = prior_manifest.installation_id

    ownership_id = config.wallpaper.selection_seed
    # Reconcile a prior interrupted link rollback before inspecting manager state.
    _systemctl(["daemon-reload"], runner=runner)
    service_linked = _validate_manager_unit(
        SERVICE_NAME,
        service_path,
        runner=runner,
        allow_missing=True,
    )
    timer_linked = _validate_manager_unit(
        TIMER_NAME,
        timer_path,
        runner=runner,
        allow_missing=True,
    )
    captured_links = _validate_unit_link_topology(
        unit_link_directory,
        service_path,
        timer_path,
        service_linked=service_linked,
        timer_linked=timer_linked,
        runner=runner,
    )
    missing_links = tuple(
        (unit_name, path)
        for unit_name, path, linked in (
            (SERVICE_NAME, service_path, service_linked),
            (TIMER_NAME, timer_path, timer_linked),
        )
        if not linked
    )
    wants_link = unit_link_directory / _TIMER_WANTS_DIRECTORY / TIMER_NAME
    captured_paths = {path for path, _target in captured_links}
    if (missing_links or (start and wants_link not in captured_paths)) and (
        unit_link_directory != current_unit_link_directory
    ):
        raise IntegrationError(
            "existing install uses a different persistent systemd user-unit root; "
            "rerun with its original XDG_CONFIG_HOME"
        )
    ensure_owned_directory(
        config.wallpaper.output_directory,
        kind="output",
        ownership_id=ownership_id,
        reserved_names=_OUTPUT_RESERVED,
        reserved_patterns=(GENERATED_WALLPAPER_NAME, GENERATED_CALIBRATION_NAME),
    )
    ensure_owned_directory(
        config.wallpaper.cache_directory,
        kind="cache",
        ownership_id=ownership_id,
        reserved_names=_CACHE_RESERVED,
    )
    service, timer = unit_contents(
        python,
        config.path,
        countdown_refresh_seconds=config.wallpaper.countdown_refresh_seconds,
        photo_rotation_seconds=config.wallpaper.photo_rotation_seconds,
    )
    manifest_data = InstallManifest(
        installation_id=installation_id,
        package_version=environment.version,
        ownership_id=ownership_id,
        config_path=config.path,
        runtime_state_directory=state_dir,
        unit_directory=unit_dir,
        unit_link_directory=unit_link_directory,
        service_path=service_path,
        timer_path=timer_path,
        output_directory=config.wallpaper.output_directory,
        cache_directory=config.wallpaper.cache_directory,
        python_executable=python,
        service_sha256=_content_digest(service),
        timer_sha256=_content_digest(timer),
    ).as_json()
    manifest_text = json.dumps(manifest_data, indent=2, sort_keys=True) + "\n"
    prior_generation = (
        (service_path, prior_service, service, "service source"),
        (timer_path, prior_timer, timer, "timer source"),
        (manifest_path, prior_manifest_text, manifest_text, "install manifest"),
    )
    publication_complete = False
    try:
        atomic_write_text(service_path, service)
        atomic_write_text(timer_path, timer)
        atomic_write_json(manifest_path, manifest_data)
        publication_complete = True
        if missing_links:
            _systemctl(
                ["link", *(str(path) for _name, path in missing_links)],
                runner=runner,
            )
        _systemctl(["daemon-reload"], runner=runner)
        for unit_name, path in (
            (SERVICE_NAME, service_path),
            (TIMER_NAME, timer_path),
        ):
            _validate_manager_unit(
                unit_name,
                path,
                runner=runner,
                allow_missing=False,
            )
        if start:
            if wants_link not in captured_paths:
                _systemctl(["enable", TIMER_NAME], runner=runner)
            _systemctl(["restart", TIMER_NAME], runner=runner)
        _validate_unit_link_topology(
            unit_link_directory,
            service_path,
            timer_path,
            service_linked=True,
            timer_linked=True,
            runner=runner,
        )
    except Exception as error:
        if not first_install:
            if publication_complete:
                raise IntegrationError(
                    "Countscape integration regeneration failed after publishing a "
                    "consistent unit generation; correct the systemd error and retry: "
                    f"{error}"
                ) from error
            rollback_failures = _restore_prior_generation(prior_generation)
            if rollback_failures:
                detail = (
                    "Countscape integration regeneration failed while publishing "
                    f"unit state; prior-generation recovery was incomplete: {error}; "
                    + "; ".join(rollback_failures)
                )
            else:
                detail = (
                    "Countscape integration regeneration failed while publishing "
                    f"unit state; the prior generation was restored: {error}"
                )
            raise IntegrationError(detail) from error
        rollback_failures = _rollback_first_install(
            manifest_path=manifest_path,
            manifest_data=manifest_data,
            unit_link_directory=unit_link_directory,
            service_path=service_path,
            service=service,
            timer_path=timer_path,
            timer=timer,
            newly_linked_candidates=missing_links if publication_complete else (),
            runner=runner,
        )
        if rollback_failures:
            detail = (
                f"Countscape installation failed: {error}; rollback incomplete: "
                + "; ".join(rollback_failures)
            )
        else:
            detail = f"Countscape installation failed and was rolled back: {error}"
        raise IntegrationError(detail) from error
    return config.path


def _owned_directory_from_state(
    manifest: InstallManifest,
    path: Path,
    kind: str,
    *,
    allow_finalized: bool = False,
) -> Path | None:
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise IntegrationError(f"refusing unsafe managed directory: {path}")
    if not path.exists():
        return None
    try:
        owned = validate_owned_directory(
            path,
            kind=kind,
            ownership_id=manifest.ownership_id,
        )
    except StateError as error:
        raise IntegrationError(str(error)) from error
    if owned is None:
        # A prior attempt can have removed this marker only after manager and
        # source teardown. With no marker, preserve the directory untouched.
        marker = path / OWNERSHIP_MARKER
        if allow_finalized and not (marker.exists() or marker.is_symlink()):
            return None
        raise IntegrationError(f"managed directory ownership is invalid: {path}")
    return owned


def _unlink_managed_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise IntegrationError(
            f"could not remove managed file {path}: {error}; "
            "the lifecycle operation can be retried"
        ) from error


def _remove_ownership_marker(
    manifest: InstallManifest,
    path: Path,
    kind: str,
) -> None:
    owned = _owned_directory_from_state(
        manifest,
        path,
        kind,
        allow_finalized=True,
    )
    if owned is None:
        return
    _unlink_managed_file(owned / OWNERSHIP_MARKER)


def _require_background_restored(state_directory: Path) -> None:
    gnome_state = state_directory / "gnome-background.json"
    if gnome_state.exists() or gnome_state.is_symlink():
        raise IntegrationError(
            "wallpaper restoration is unresolved; choose another wallpaper "
            "and run uninstall again"
        )


def uninstall(
    *,
    config_path: Path | None = None,
    state_directory: Path | None = None,
    runner: Runner = subprocess.run,
) -> bool:
    config: AppConfig | None = None
    if state_directory is None:
        config = load_config(config_path)
        state_dir = _runtime_state_directory(
            config.runtime.state_directory,
            config=config,
        )
    else:
        state_dir = _runtime_state_directory(state_directory)
    manifest_path = state_dir / "install.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        restored = restore_background(runner=runner, state_directory=state_dir)
        _require_background_restored(state_dir)
        return restored
    if manifest.runtime_state_directory != state_dir:
        raise IntegrationError(
            "Countscape install manifest belongs to a different runtime state directory"
        )
    if config is not None:
        expected_identity = (
            ("configuration path", manifest.config_path, config.path),
            (
                "selection ownership",
                manifest.ownership_id,
                config.wallpaper.selection_seed,
            ),
            (
                "output directory",
                manifest.output_directory,
                config.wallpaper.output_directory,
            ),
            (
                "cache directory",
                manifest.cache_directory,
                config.wallpaper.cache_directory,
            ),
        )
        for name, installed_value, configured_value in expected_identity:
            if installed_value != configured_value:
                raise IntegrationError(
                    f"installed {name} does not match this configuration; "
                    "use the installed configuration or the explicit "
                    "--state-directory recovery override"
                )

    service_path = manifest.service_path
    timer_path = manifest.timer_path
    _validate_unit_ownership(service_path, manifest.service_sha256)
    _validate_unit_ownership(timer_path, manifest.timer_sha256)
    # Reconcile any prior exact-link removal whose reload was interrupted before
    # deciding which managed links still need teardown.
    _systemctl(["daemon-reload"], runner=runner)
    timer_linked = _validate_manager_unit(
        TIMER_NAME,
        timer_path,
        runner=runner,
        allow_missing=True,
    )
    service_linked = _validate_manager_unit(
        SERVICE_NAME,
        service_path,
        runner=runner,
        allow_missing=True,
    )
    captured_links = _validate_unit_link_topology(
        manifest.unit_link_directory,
        service_path,
        timer_path,
        service_linked=service_linked,
        timer_linked=timer_linked,
        runner=runner,
    )
    systemd_already_removed = (
        not timer_linked
        and not service_linked
        and not (service_path.exists() or service_path.is_symlink())
        and not (timer_path.exists() or timer_path.is_symlink())
    )
    output = _owned_directory_from_state(
        manifest,
        manifest.output_directory,
        "output",
        allow_finalized=systemd_already_removed,
    )
    cache = _owned_directory_from_state(
        manifest,
        manifest.cache_directory,
        "cache",
        allow_finalized=systemd_already_removed,
    )

    if timer_linked:
        stopped = _systemctl(
            ["stop", TIMER_NAME],
            runner=runner,
            tolerate_failure=True,
        )
        if stopped.returncode != 0:
            detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
            raise IntegrationError(f"could not stop Countscape timer: {detail}")
    if service_linked:
        stopped = _systemctl(
            ["stop", SERVICE_NAME],
            runner=runner,
            tolerate_failure=True,
        )
        if stopped.returncode != 0:
            detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
            raise IntegrationError(f"could not stop Countscape service: {detail}")

    # Keep all source, manifest, marker, and generated-data evidence until the
    # user manager has accepted link removal and proves both names absent.
    _unlink_unit_links(captured_links)
    _systemctl(["daemon-reload"], runner=runner)
    for name, expected_path in (
        (SERVICE_NAME, service_path),
        (TIMER_NAME, timer_path),
    ):
        if _validate_manager_unit(
            name,
            expected_path,
            runner=runner,
            allow_missing=True,
        ):
            raise IntegrationError(
                f"could not remove Countscape user-unit link for {name}"
            )

    lock = operation_lock(output) if output is not None else nullcontext()
    with lock:
        if output is not None:
            _owned_directory_from_state(manifest, output, "output")
        if cache is not None:
            _owned_directory_from_state(manifest, cache, "cache")
        restored = restore_background(runner=runner, state_directory=state_dir)
        _require_background_restored(state_dir)
        referenced = {
            path.resolve() for path in current_background_paths(runner=runner)
        }
        if cache is not None:
            cached_base = cache / "base.png"
            if (
                cached_base.exists() or cached_base.is_symlink()
            ) and cached_base.resolve() in referenced:
                raise IntegrationError(
                    "a Countscape cache image remains referenced by GNOME; "
                    "choose another wallpaper and run uninstall again"
                )
        if output is not None:
            generated_references = [
                path
                for path in output.iterdir()
                if (
                    GENERATED_WALLPAPER_NAME.fullmatch(path.name)
                    or GENERATED_CALIBRATION_NAME.fullmatch(path.name)
                )
                and path.resolve() in referenced
            ]
            if generated_references:
                raise IntegrationError(
                    "a generated Countscape output remains referenced by GNOME; "
                    "choose another wallpaper and run uninstall again"
                )
            for path in output.iterdir():
                if (
                    GENERATED_WALLPAPER_NAME.fullmatch(path.name)
                    or GENERATED_CALIBRATION_NAME.fullmatch(path.name)
                ) and path.resolve() not in referenced:
                    _unlink_managed_file(path)
            _unlink_managed_file(output / "render-state.json")
        if cache is not None:
            for name in ("base.png", "base.json"):
                _unlink_managed_file(cache / name)
    if output is not None:
        _owned_directory_from_state(manifest, output, "output")
        _unlink_managed_file(output / ".countscape.lock")

    # Manager teardown has committed. Keep the manifest and directory markers
    # while removing the now-unreferenced source files.
    _validate_unit_ownership(service_path, manifest.service_sha256)
    _validate_unit_ownership(timer_path, manifest.timer_sha256)
    _unlink_managed_file(service_path)
    _unlink_managed_file(timer_path)
    _remove_ownership_marker(manifest, manifest.output_directory, "output")
    _remove_ownership_marker(manifest, manifest.cache_directory, "cache")
    _unlink_managed_file(manifest_path)
    return restored


def timer_status(
    *,
    state_directory: Path,
    runner: Runner = subprocess.run,
) -> dict[str, str | bool]:
    state_dir = _runtime_state_directory(state_directory)
    manifest = _read_manifest(state_dir / "install.json")
    if manifest is None:
        return {"active": False, "detail": "not installed"}
    if manifest.runtime_state_directory != state_dir:
        raise IntegrationError(
            "Countscape install manifest belongs to a different runtime state directory"
        )
    result = _systemctl(
        ["is-active", TIMER_NAME],
        runner=runner,
        tolerate_failure=True,
    )
    return {
        "active": result.returncode == 0,
        "detail": result.stdout.strip() or result.stderr.strip() or "unknown",
    }
