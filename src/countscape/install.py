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
INSTALL_MANIFEST_SCHEMA_VERSION = 1
Runner = Callable[..., subprocess.CompletedProcess[str]]
_OUTPUT_RESERVED = frozenset({"render-state.json"})
_CACHE_RESERVED = frozenset({"base.png", "base.json"})
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
    service_path = _manifest_path(data, "service_path")
    timer_path = _manifest_path(data, "timer_path")
    if service_path != unit_directory / SERVICE_NAME:
        raise IntegrationError("Countscape install manifest has invalid service_path")
    if timer_path != unit_directory / TIMER_NAME:
        raise IntegrationError("Countscape install manifest has invalid timer_path")
    if unit_directory != runtime_state_directory / "systemd":
        raise IntegrationError("Countscape install manifest has invalid unit_directory")
    return InstallManifest(
        installation_id=installation_id,
        package_version=_required_manifest_string(data, "package_version"),
        ownership_id=_required_manifest_string(data, "ownership_id"),
        config_path=_manifest_path(data, "config_path"),
        runtime_state_directory=runtime_state_directory,
        unit_directory=unit_directory,
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
    result = _systemctl(
        ["show", "--property=FragmentPath", "--value", unit_name],
        runner=runner,
        tolerate_failure=True,
    )
    raw = result.stdout.strip()
    if result.returncode != 0 or not raw:
        return None
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


def _rollback_first_install(
    *,
    manifest_path: Path,
    manifest_data: dict[str, object],
    service_path: Path,
    service: str,
    timer_path: Path,
    timer: str,
    newly_linked_candidates: tuple[tuple[str, Path], ...],
    runner: Runner,
) -> list[str]:
    """Best-effort rollback without removing files not created by this attempt."""
    failures: list[str] = []
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
        if not linked:
            continue
        disabled = _systemctl(
            ["disable", "--now", unit_name],
            runner=runner,
            tolerate_failure=True,
        )
        if disabled.returncode != 0:
            detail = disabled.stderr.strip() or f"exit {disabled.returncode}"
            failures.append(
                f"could not remove new user-unit link {unit_name}: {detail}"
            )

    if newly_linked_candidates:
        reloaded = _systemctl(["daemon-reload"], runner=runner, tolerate_failure=True)
        if reloaded.returncode != 0:
            detail = reloaded.stderr.strip() or f"exit {reloaded.returncode}"
            failures.append(f"could not reload systemd during rollback: {detail}")

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
    if prior_manifest is None:
        unit_dir = state_dir / "systemd"
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
        installation_id = prior_manifest.installation_id

    ownership_id = config.wallpaper.selection_seed
    missing_links = tuple(
        (unit_name, path)
        for unit_name, path in (
            (SERVICE_NAME, service_path),
            (TIMER_NAME, timer_path),
        )
        if not _validate_manager_unit(
            unit_name,
            path,
            runner=runner,
            allow_missing=True,
        )
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
        service_path=service_path,
        timer_path=timer_path,
        output_directory=config.wallpaper.output_directory,
        cache_directory=config.wallpaper.cache_directory,
        python_executable=python,
        service_sha256=_content_digest(service),
        timer_sha256=_content_digest(timer),
    ).as_json()
    try:
        atomic_write_text(service_path, service)
        atomic_write_text(timer_path, timer)
        atomic_write_json(manifest_path, manifest_data)
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
            _systemctl(["enable", TIMER_NAME], runner=runner)
            _systemctl(["restart", TIMER_NAME], runner=runner)
    except Exception as error:
        if not first_install:
            raise
        rollback_failures = _rollback_first_install(
            manifest_path=manifest_path,
            manifest_data=manifest_data,
            service_path=service_path,
            service=service,
            timer_path=timer_path,
            timer=timer,
            newly_linked_candidates=missing_links,
            runner=runner,
        )
        detail = f"Countscape installation failed and was rolled back: {error}"
        if rollback_failures:
            detail += "; rollback incomplete: " + "; ".join(rollback_failures)
        raise IntegrationError(detail) from error
    return config.path


def _owned_directory_from_state(
    manifest: InstallManifest,
    path: Path,
    kind: str,
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
        raise IntegrationError(f"managed directory ownership is invalid: {path}")
    return owned


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
    output = _owned_directory_from_state(
        manifest,
        manifest.output_directory,
        "output",
    )
    cache = _owned_directory_from_state(
        manifest,
        manifest.cache_directory,
        "cache",
    )

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

    if timer_linked:
        disabled = _systemctl(
            ["disable", "--now", TIMER_NAME],
            runner=runner,
            tolerate_failure=True,
        )
        if disabled.returncode != 0:
            detail = disabled.stderr.strip() or f"exit {disabled.returncode}"
            raise IntegrationError(f"could not disable Countscape timer: {detail}")
    if service_linked:
        stopped = _systemctl(
            ["stop", SERVICE_NAME],
            runner=runner,
            tolerate_failure=True,
        )
        if stopped.returncode != 0:
            detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
            raise IntegrationError(f"could not stop Countscape service: {detail}")
        disabled = _systemctl(
            ["disable", SERVICE_NAME],
            runner=runner,
            tolerate_failure=True,
        )
        if disabled.returncode != 0:
            detail = disabled.stderr.strip() or f"exit {disabled.returncode}"
            raise IntegrationError(f"could not disable Countscape service: {detail}")

    lock = operation_lock(output) if output is not None else nullcontext()
    with lock:
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
                    path.unlink(missing_ok=True)
            (output / "render-state.json").unlink(missing_ok=True)
            (output / OWNERSHIP_MARKER).unlink(missing_ok=True)
        if cache is not None:
            for name in ("base.png", "base.json", OWNERSHIP_MARKER):
                (cache / name).unlink(missing_ok=True)
    if output is not None:
        (output / ".countscape.lock").unlink(missing_ok=True)
    service_path.unlink(missing_ok=True)
    timer_path.unlink(missing_ok=True)
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
    manifest_path.unlink(missing_ok=True)
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
