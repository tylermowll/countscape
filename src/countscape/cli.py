from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from countscape import installed_version
from countscape.config import CONFIG_SCHEMA_VERSION, default_config_path, load_config
from countscape.countdown import calculate_countdown
from countscape.display import build_canvas_layout
from countscape.errors import ConfigError, CountdownError
from countscape.gnome import apply_wallpaper, protected_output_paths
from countscape.install import (
    configure_settings,
    initialize_config,
    install,
    timer_status,
    uninstall,
)
from countscape.mutter import discover_layout
from countscape.photos import scan_photo_pool
from countscape.render import (
    prune_generated_outputs,
    render_calibration,
    render_metadata,
    render_wallpaper,
    resolve_font,
)
from countscape.state import operation_lock


def _config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="configuration file (default: XDG config directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="countscape",
        description="Turn a photo collection into a live countdown wallpaper.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {installed_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a personal configuration")
    _config_argument(init)
    init.add_argument(
        "--target",
        help="event time as ISO 8601 with an explicit UTC offset",
    )
    init.add_argument("--timezone", help="event IANA zone, such as Europe/London")
    init.add_argument("--label", default="Until the big day")
    init.add_argument("--after-message", default="It's here!")
    init.add_argument("--photos", type=Path, help="directory containing your photos")
    init.add_argument("--output", type=Path, help="directory for generated wallpapers")
    init.add_argument("--cache", type=Path, help="directory for the render cache")
    init.add_argument(
        "--state-directory",
        type=Path,
        help="directory for persistent runtime and integration state",
    )
    init.add_argument("--countdown-refresh-seconds", type=int, default=60)
    init.add_argument("--photo-rotation-seconds", type=int, default=600)
    init.add_argument("--force", action="store_true")

    doctor = subparsers.add_parser("doctor", help="run non-mutating diagnostics")
    _config_argument(doctor)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument(
        "--include-private",
        action="store_true",
        help=(
            "include event, path, font, and display identifiers; review before sharing"
        ),
    )

    render = subparsers.add_parser("render", help="render without changing GNOME")
    _config_argument(render)

    apply = subparsers.add_parser("apply", help="render and apply to GNOME")
    _config_argument(apply)
    apply.add_argument("--retries", type=int, default=1)

    calibrate = subparsers.add_parser(
        "calibrate", help="create a numbered display-layout image"
    )
    _config_argument(calibrate)
    calibrate.add_argument("--apply", action="store_true")

    status = subparsers.add_parser("status", help="show timer and render status")
    _config_argument(status)
    status.add_argument("--json", action="store_true")
    status.add_argument(
        "--include-private",
        action="store_true",
        help="include raw timer and render state; review before sharing",
    )

    configure = subparsers.add_parser(
        "configure", help="update countdown and presentation settings"
    )
    _config_argument(configure)
    configure.add_argument("--overlay-position", choices=("center", "bottom"))
    configure.add_argument("--photo-fit", choices=("contain", "cover"))
    configure.add_argument("--photos", type=Path)
    configure.add_argument("--countdown-refresh-seconds", type=int)
    configure.add_argument("--photo-rotation-seconds", type=int)
    configure.add_argument("--event-label")
    configure.add_argument("--target")
    configure.add_argument("--timezone")
    configure.add_argument("--after-message")

    install_parser = subparsers.add_parser(
        "install", help="install the user-scoped GNOME timer"
    )
    _config_argument(install_parser)
    install_parser.add_argument("--no-start", action="store_true")

    uninstall_parser = subparsers.add_parser(
        "uninstall", help="remove integration and conditionally restore GNOME"
    )
    _config_argument(uninstall_parser)
    uninstall_parser.add_argument(
        "--state-directory",
        type=Path,
        help="recovery override when the final configuration cannot be loaded",
    )
    return parser


def doctor_report(
    config_path: Path,
    *,
    include_private: bool = False,
) -> tuple[dict[str, Any], bool]:
    report: dict[str, Any] = {
        "diagnostic_schema_version": 1,
        "privacy": "contains-private-data" if include_private else "redacted",
        "version": installed_version(),
        "checks": {},
        "tools": {},
        "errors": [],
    }

    def failed(check: str, error: CountdownError) -> None:
        report["checks"][check] = {"ok": False}
        report["errors"].append(
            {
                "check": check,
                "message": str(error) if include_private else f"{check} check failed",
            }
        )

    for tool in ("busctl", "fc-match", "gsettings", "systemctl", "systemd-analyze"):
        path = shutil.which(tool)
        report["tools"][tool] = (
            {"ok": path is not None, "path": path}
            if include_private
            else {"ok": path is not None}
        )
    try:
        config = load_config(config_path)
        report["checks"]["config"] = {
            "ok": True,
            "schema_version": CONFIG_SCHEMA_VERSION,
        }
        if include_private:
            report["checks"]["config"]["path"] = str(config.path)
            report["event"] = {
                "label": config.event.label,
                "target": config.event.target.isoformat(),
                "timezone": config.event.timezone.key,
                "state": calculate_countdown(
                    datetime.now().astimezone(),
                    config.event.target,
                    config.event.after_arrival_message,
                ).text,
            }
            report["paths"] = {
                "photos": str(config.wallpaper.source_directory),
                "output": str(config.wallpaper.output_directory),
                "cache": str(config.wallpaper.cache_directory),
                "state": str(config.runtime.state_directory),
            }
        report["schedule"] = {
            "countdown_refresh_seconds": (config.wallpaper.countdown_refresh_seconds),
            "photo_rotation_seconds": config.wallpaper.photo_rotation_seconds,
        }
        try:
            pool = scan_photo_pool(config.wallpaper.source_directory)
            report["checks"]["photos"] = {"ok": True}
            if include_private:
                report["checks"]["photos"]["count"] = len(pool.photos)
                report["checks"]["photos"]["signature"] = pool.signature
        except CountdownError as error:
            failed("photos", error)
        try:
            font = resolve_font(config.style.font)
            report["checks"]["font"] = {"ok": True}
            if include_private:
                report["checks"]["font"]["path"] = str(font)
        except CountdownError as error:
            failed("font", error)
        try:
            layout = discover_layout(config.display)
            canvas = build_canvas_layout(
                layout,
                max_pixels=config.wallpaper.max_canvas_pixels,
            )
            report["checks"]["display"] = {
                "ok": True,
                "monitor_count": len(layout.monitors),
                "mirrored": any(
                    len(monitor.physical) > 1 for monitor in layout.monitors
                ),
                "scaled": any(monitor.scale != 1 for monitor in layout.monitors),
                "transformed": any(
                    monitor.transform != 0 for monitor in layout.monitors
                ),
            }
            if include_private:
                report["display"] = {
                    "source": layout.source,
                    "layout_mode": layout.layout_mode,
                    "canvas": [canvas.width, canvas.height],
                    "backing_scale": canvas.backing_scale,
                    "regions": [
                        {
                            "connectors": region.connectors,
                            "x": region.x,
                            "y": region.y,
                            "width": region.width,
                            "height": region.height,
                            "primary": region.primary,
                        }
                        for region in canvas.regions
                    ],
                }
        except CountdownError as error:
            failed("display", error)
    except CountdownError as error:
        failed("config", error)
    missing = [tool for tool, result in report["tools"].items() if not result["ok"]]
    if missing:
        report["errors"].append(
            {
                "check": "tools",
                "message": f"missing required host tools: {', '.join(missing)}",
            }
        )
    return report, not report["errors"]


def _print_report(report: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"version: {report['version']}")
    print(f"privacy: {report['privacy']}")
    for name, result in report["checks"].items():
        detail = "ok" if result["ok"] else "failed"
        if name == "display" and result["ok"]:
            detail += f" ({result['monitor_count']} logical)"
        print(f"{name}: {detail}")
    for error in report["errors"]:
        print(f"error [{error['check']}]: {error['message']}", file=sys.stderr)


def _apply_with_retries(config_path: Path, retries: int) -> Path:
    if retries < 1:
        raise CountdownError("retries must be at least 1")
    last_error: CountdownError | None = None
    for attempt in range(1, retries + 1):
        try:
            config = load_config(config_path)
            layout = discover_layout(config.display)
            with operation_lock(config.wallpaper.output_directory):
                output = render_wallpaper(
                    config,
                    layout,
                    acquire_lock=False,
                )
                apply_wallpaper(
                    output,
                    multi_monitor=len(layout.monitors) > 1,
                    state_directory=config.runtime.state_directory,
                )
                prune_generated_outputs(
                    config.wallpaper.output_directory,
                    keep=(
                        output,
                        *protected_output_paths(
                            state_directory=config.runtime.state_directory
                        ),
                    ),
                )
            return output
        except CountdownError as error:
            last_error = error
            if attempt < retries:
                time.sleep(attempt)
    assert last_error is not None
    raise last_error


def _prompt(value: str | None, message: str) -> str:
    if value:
        return value
    try:
        entered = input(message).strip()
    except EOFError as error:
        raise ConfigError(
            "missing required init value; pass it as an option"
        ) from error
    if not entered:
        raise ConfigError("a value is required")
    return entered


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            target = _prompt(args.target, "Target (ISO 8601 with UTC offset): ")
            timezone = _prompt(args.timezone, "IANA timezone: ")
            path = initialize_config(
                target=target,
                timezone=timezone,
                label=args.label,
                after_arrival_message=args.after_message,
                source_directory=args.photos,
                output_directory=args.output,
                cache_directory=args.cache,
                state_directory=args.state_directory,
                countdown_refresh_seconds=args.countdown_refresh_seconds,
                photo_rotation_seconds=args.photo_rotation_seconds,
                config_path=args.config,
                force=args.force,
            )
            print(path)
            return 0
        if args.command == "doctor":
            if args.include_private:
                print(
                    "WARNING: private diagnostics include event details, "
                    "absolute paths, "
                    "font paths, and display identifiers. Review before sharing.",
                    file=sys.stderr,
                )
            report, healthy = doctor_report(
                args.config,
                include_private=args.include_private,
            )
            _print_report(report, json_output=args.json)
            return 0 if healthy else 1
        if args.command == "render":
            config = load_config(args.config)
            output = render_wallpaper(config, discover_layout(config.display))
            print(output)
            return 0
        if args.command == "apply":
            print(_apply_with_retries(args.config, args.retries))
            return 0
        if args.command == "calibrate":
            config = load_config(args.config)
            layout = discover_layout(config.display)
            if args.apply:
                with operation_lock(config.wallpaper.output_directory):
                    output = render_calibration(
                        config,
                        layout,
                        acquire_lock=False,
                    )
                    apply_wallpaper(
                        output,
                        multi_monitor=len(layout.monitors) > 1,
                        state_directory=config.runtime.state_directory,
                    )
                    prune_generated_outputs(
                        config.wallpaper.output_directory,
                        keep=(
                            output,
                            *protected_output_paths(
                                state_directory=config.runtime.state_directory
                            ),
                        ),
                    )
            else:
                output = render_calibration(config, layout)
            print(output)
            return 0
        if args.command == "status":
            if args.include_private:
                print(
                    "WARNING: private status includes raw timer diagnostics and "
                    "render state, which may expose paths, photo names, display "
                    "identifiers, and timestamps. Review before sharing.",
                    file=sys.stderr,
                )
            try:
                config = load_config(args.config)
                timer = timer_status(
                    state_directory=config.runtime.state_directory,
                )
                try:
                    render = render_metadata(config)
                except OSError, json.JSONDecodeError:
                    render = None
            except CountdownError:
                if args.include_private:
                    raise
                print("countscape: status check failed", file=sys.stderr)
                return 1
            report: dict[str, Any] = {
                "privacy": (
                    "contains-private-data" if args.include_private else "redacted"
                ),
                "timer": timer if args.include_private else {"active": timer["active"]},
                "render": (
                    render
                    if args.include_private
                    else {"available": render is not None}
                ),
            }
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"privacy: {report['privacy']}")
                if args.include_private:
                    print(f"timer: {timer['detail']}")
                    print(f"last render: {render or 'none'}")
                else:
                    print(f"timer: {'active' if timer['active'] else 'inactive'}")
                    print(f"last render: {'available' if render else 'none'}")
            return 0 if timer["active"] else 1
        if args.command == "configure":
            print(
                configure_settings(
                    args.config,
                    overlay_position=args.overlay_position,
                    photo_fit=args.photo_fit,
                    source_directory=args.photos,
                    countdown_refresh_seconds=args.countdown_refresh_seconds,
                    photo_rotation_seconds=args.photo_rotation_seconds,
                    event_label=args.event_label,
                    event_target=args.target,
                    event_timezone=args.timezone,
                    after_arrival_message=args.after_message,
                )
            )
            return 0
        if args.command == "install":
            print(install(config_path=args.config, start=not args.no_start))
            return 0
        if args.command == "uninstall":
            restored = uninstall(
                config_path=None if args.state_directory else args.config,
                state_directory=args.state_directory,
            )
            print(
                "integration removed; "
                + ("previous wallpaper restored" if restored else "wallpaper unchanged")
            )
            return 0
    except CountdownError as error:
        print(f"countscape: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 2
