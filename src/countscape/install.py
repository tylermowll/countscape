from __future__ import annotations

import json
import math
import secrets
import subprocess
import sys
from collections.abc import Callable
from contextlib import nullcontext, suppress
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from countscape.config import (
    AppConfig,
    DisplayConfig,
    StyleConfig,
    WallpaperConfig,
    default_cache_directory,
    default_config_path,
    default_output_directory,
    default_photo_directory,
    load_config,
    parse_event,
    validate_config_location,
    validate_schedule_interval,
    validate_storage_paths,
    xdg_config_home,
    xdg_state_home,
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
Runner = Callable[..., subprocess.CompletedProcess[str]]
_OUTPUT_RESERVED = frozenset({"render-state.json", "calibration.png"})
_CACHE_RESERVED = frozenset({"base.png", "base.json"})
_UNIT_HEADER = (
    "# Managed by Countscape. Changes will be replaced by "
    "`countscape install`."
)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def dump_config(config: AppConfig, *, seed: str | None = None) -> str:
    selection_seed = seed or config.wallpaper.selection_seed
    lines = [
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
        with suppress(ConfigError):
            prior_seed = load_config(path).wallpaper.selection_seed
    event = parse_event(
        label=label,
        target=target,
        timezone=timezone,
        after_arrival_message=after_arrival_message,
    )
    photos = (source_directory or default_photo_directory()).expanduser().resolve()
    output = (output_directory or default_output_directory()).expanduser().resolve()
    cache = (cache_directory or default_cache_directory()).expanduser().resolve()
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
    )
    validate_storage_paths(photos, output, cache)
    validate_config_location(path, photos, output, cache)
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
    )
    validate_config_location(
        config.path,
        wallpaper.source_directory,
        wallpaper.output_directory,
        wallpaper.cache_directory,
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
        f"*-*-* *:*:00/{polling_seconds}"
        if polling_seconds < 60
        else "*-*-* *:*:00"
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


def _read_manifest(path: Path) -> dict[str, object] | None:
    try:
        return read_json_strict(path)
    except StateError as error:
        raise IntegrationError(str(error)) from error


def _validate_manifest(manifest: dict[str, object]) -> None:
    required_strings = (
        "installation_id",
        "ownership_id",
        "config",
        "service",
        "timer",
        "output_directory",
        "cache_directory",
        "python",
        "service_sha256",
        "timer_sha256",
    )
    if manifest.get("application") != "countscape" or not all(
        isinstance(manifest.get(key), str) and manifest.get(key)
        for key in required_strings
    ):
        raise IntegrationError("Countscape install manifest is invalid")


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


def _editable_install() -> bool:
    try:
        direct_url = distribution("countscape").read_text("direct_url.json")
    except PackageNotFoundError:
        return False
    if not direct_url:
        return False
    try:
        metadata = json.loads(direct_url)
    except json.JSONDecodeError:
        return False
    directory = metadata.get("dir_info")
    return isinstance(directory, dict) and directory.get("editable") is True


def install(
    *,
    config_path: Path | None = None,
    executable: Path | None = None,
    start: bool = True,
    runner: Runner = subprocess.run,
) -> Path:
    config = load_config(config_path)

    # Preflight before changing user integration.
    scan_photo_pool(config.wallpaper.source_directory)
    layout = discover_layout(config.display)
    build_canvas_layout(layout, max_pixels=config.wallpaper.max_canvas_pixels)
    resolve_font(config.style.font)
    python = (executable or Path(sys.executable)).expanduser().resolve()
    if not python.is_file():
        raise IntegrationError(f"installed Python executable is missing: {python}")
    if executable is None and _editable_install():
        raise IntegrationError(
            "install requires a persistent package environment; install Countscape "
            "with `uv tool install` instead of running from an editable checkout"
        )

    unit_dir = xdg_config_home() / "systemd" / "user"
    service_path = unit_dir / SERVICE_NAME
    timer_path = unit_dir / TIMER_NAME
    state_dir = xdg_state_home() / "countscape"
    manifest_path = state_dir / "install.json"
    prior_manifest = _read_manifest(manifest_path)
    if prior_manifest is None:
        for path in (service_path, timer_path):
            if path.exists() or path.is_symlink():
                raise IntegrationError(
                    f"refusing to replace foreign systemd unit: {path}"
                )
        installation_id = secrets.token_hex(16)
    else:
        _validate_manifest(prior_manifest)
        _validate_unit_ownership(
            service_path,
            prior_manifest["service_sha256"],
        )
        _validate_unit_ownership(
            timer_path,
            prior_manifest["timer_sha256"],
        )
        installation_id = str(prior_manifest["installation_id"])

    ownership_id = config.wallpaper.selection_seed
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
    atomic_write_text(service_path, service)
    atomic_write_text(timer_path, timer)
    atomic_write_json(
        manifest_path,
        {
            "application": "countscape",
            "installation_id": installation_id,
            "ownership_id": ownership_id,
            "config": str(config.path),
            "service": str(service_path),
            "timer": str(timer_path),
            "output_directory": str(config.wallpaper.output_directory),
            "cache_directory": str(config.wallpaper.cache_directory),
            "python": str(python),
            "service_sha256": _content_digest(service),
            "timer_sha256": _content_digest(timer),
        },
    )
    _systemctl(["daemon-reload"], runner=runner)
    if start:
        _systemctl(["enable", TIMER_NAME], runner=runner)
        _systemctl(["restart", TIMER_NAME], runner=runner)
    return config.path


def _owned_directory_from_state(
    manifest: dict[str, object],
    key: str,
    kind: str,
) -> Path | None:
    ownership_id = manifest.get("ownership_id")
    raw = manifest.get(key)
    if not isinstance(ownership_id, str) or not isinstance(raw, str):
        raise IntegrationError("Countscape install manifest is missing ownership data")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise IntegrationError("managed directories in install state must be absolute")
    path = candidate.resolve()
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise IntegrationError(f"refusing unsafe managed directory: {path}")
    if not path.exists():
        return None
    try:
        owned = validate_owned_directory(
            path,
            kind=kind,
            ownership_id=ownership_id,
        )
    except StateError as error:
        raise IntegrationError(str(error)) from error
    if owned is None:
        raise IntegrationError(f"managed directory ownership is invalid: {path}")
    return owned


def uninstall(*, runner: Runner = subprocess.run) -> bool:
    state_dir = xdg_state_home() / "countscape"
    manifest_path = state_dir / "install.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return restore_background(runner=runner, state_directory=state_dir)
    _validate_manifest(manifest)

    unit_dir = xdg_config_home() / "systemd" / "user"
    service_path = unit_dir / SERVICE_NAME
    timer_path = unit_dir / TIMER_NAME
    if Path(str(manifest["service"])) != service_path or Path(
        str(manifest["timer"])
    ) != timer_path:
        raise IntegrationError("Countscape install manifest has unexpected unit paths")
    _validate_unit_ownership(service_path, manifest["service_sha256"])
    _validate_unit_ownership(timer_path, manifest["timer_sha256"])
    output = _owned_directory_from_state(manifest, "output_directory", "output")
    cache = _owned_directory_from_state(manifest, "cache_directory", "cache")

    disabled = _systemctl(
        ["disable", "--now", TIMER_NAME],
        runner=runner,
        tolerate_failure=True,
    )
    if disabled.returncode != 0:
        detail = disabled.stderr.strip() or f"exit {disabled.returncode}"
        raise IntegrationError(f"could not disable Countscape timer: {detail}")
    stopped = _systemctl(
        ["stop", SERVICE_NAME],
        runner=runner,
        tolerate_failure=True,
    )
    if stopped.returncode != 0:
        detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
        raise IntegrationError(f"could not stop Countscape service: {detail}")

    lock = operation_lock(output) if output is not None else nullcontext()
    with lock:
        restored = restore_background(runner=runner, state_directory=state_dir)
        gnome_state = state_dir / "gnome-background.json"
        if gnome_state.exists() or gnome_state.is_symlink():
            raise IntegrationError(
                "wallpaper restoration is unresolved; choose another wallpaper "
                "and run uninstall again"
            )
        referenced = {
            path.resolve() for path in current_background_paths(runner=runner)
        }
        if output is not None:
            for path in output.iterdir():
                if (
                    GENERATED_WALLPAPER_NAME.fullmatch(path.name)
                    or GENERATED_CALIBRATION_NAME.fullmatch(path.name)
                    or path.name == "calibration.png"
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
    _systemctl(["daemon-reload"], runner=runner, tolerate_failure=True)
    manifest_path.unlink(missing_ok=True)
    return restored


def timer_status(*, runner: Runner = subprocess.run) -> dict[str, str | bool]:
    result = _systemctl(
        ["is-active", TIMER_NAME],
        runner=runner,
        tolerate_failure=True,
    )
    return {
        "active": result.returncode == 0,
        "detail": result.stdout.strip() or result.stderr.strip() or "unknown",
    }
