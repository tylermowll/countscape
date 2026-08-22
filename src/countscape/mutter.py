from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from countscape.config import DisplayConfig
from countscape.errors import DisplayError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor

DISPLAY_SIGNATURE = "ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv}"
BUSCTL_COMMAND = (
    "busctl",
    "--user",
    "--json=short",
    "call",
    "org.gnome.Mutter.DisplayConfig",
    "/org/gnome/Mutter/DisplayConfig",
    "org.gnome.Mutter.DisplayConfig",
    "GetCurrentState",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _variant(properties: dict[str, Any], name: str, default: Any = None) -> Any:
    value = properties.get(name, default)
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def parse_current_state(payload: str) -> DisplayLayout:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise DisplayError(f"Mutter returned invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise DisplayError("Mutter GetCurrentState response must be an object")
    if document.get("type") != DISPLAY_SIGNATURE:
        raise DisplayError(
            f"unexpected Mutter GetCurrentState signature: {document.get('type')!r}"
        )
    try:
        _serial, raw_monitors, raw_logical, properties = document["data"]
    except (KeyError, TypeError, ValueError) as error:
        raise DisplayError("incomplete Mutter GetCurrentState payload") from error

    try:
        active: dict[str, PhysicalMonitor] = {}
        for raw_monitor in raw_monitors:
            spec, modes, _monitor_properties = raw_monitor
            connector = spec[0]
            current = next(
                (mode for mode in modes if _variant(mode[6], "is-current") is True),
                None,
            )
            if current is not None:
                active[connector] = PhysicalMonitor(
                    connector=connector,
                    width=int(current[1]),
                    height=int(current[2]),
                )

        monitors: list[LogicalMonitor] = []
        for raw in raw_logical:
            x, y, scale, transform, primary, raw_specs, _logical_properties = raw
            if type(primary) is not bool:
                raise DisplayError("Mutter primary status must be boolean")
            connectors = tuple(spec[0] for spec in raw_specs)
            try:
                physical = tuple(active[connector] for connector in connectors)
            except KeyError as error:
                raise DisplayError(
                    "logical monitor references connector without an active mode: "
                    f"{error}"
                ) from error
            monitors.append(
                LogicalMonitor(
                    x=float(x),
                    y=float(y),
                    scale=float(scale),
                    transform=int(transform),
                    primary=primary,
                    connectors=connectors,
                    physical=physical,
                )
            )
    except DisplayError:
        raise
    except (
        AttributeError,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise DisplayError(f"invalid Mutter monitor data: {error}") from error
    try:
        layout_mode = int(_variant(properties, "layout-mode", -1))
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise DisplayError(f"invalid Mutter layout mode: {error}") from error
    layout = DisplayLayout(
        monitors=tuple(monitors),
        layout_mode=layout_mode,
        source="mutter",
    )
    layout.validate()
    return layout


def discover_layout(
    display: DisplayConfig,
    *,
    runner: Runner = subprocess.run,
    command: Sequence[str] = BUSCTL_COMMAND,
) -> DisplayLayout:
    if display.mode == "profile":
        assert display.fallback_profile is not None
        return display.profiles[display.fallback_profile]
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit {result.returncode}"
            raise DisplayError(f"Mutter display discovery failed: {detail}")
        return parse_current_state(result.stdout)
    except (OSError, subprocess.TimeoutExpired, DisplayError) as error:
        if display.fallback_profile:
            return display.profiles[display.fallback_profile]
        if isinstance(error, DisplayError):
            raise
        raise DisplayError(f"Mutter display discovery failed: {error}") from error
