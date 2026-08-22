from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from math import isfinite

from countscape.errors import DisplayError

ROTATED_TRANSFORMS = frozenset({1, 3, 5, 7})
VALID_TRANSFORMS = frozenset(range(8))


@dataclass(frozen=True, slots=True)
class PhysicalMonitor:
    connector: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class LogicalMonitor:
    x: float
    y: float
    scale: float
    transform: int
    primary: bool
    connectors: tuple[str, ...]
    physical: tuple[PhysicalMonitor, ...]

    @property
    def logical_size(self) -> tuple[float, float]:
        if not self.physical:
            raise DisplayError("logical monitor has no physical monitor")
        sizes: list[tuple[float, float]] = []
        for monitor in self.physical:
            width = monitor.width / self.scale
            height = monitor.height / self.scale
            if self.transform in ROTATED_TRANSFORMS:
                width, height = height, width
            sizes.append((width, height))
        first = sizes[0]
        for size in sizes[1:]:
            if abs(size[0] - first[0]) > 1 or abs(size[1] - first[1]) > 1:
                raise DisplayError(
                    "mirrored monitors do not resolve to one logical size"
                )
        return first


@dataclass(frozen=True, slots=True)
class DisplayLayout:
    monitors: tuple[LogicalMonitor, ...]
    layout_mode: int
    source: str

    def validate(self) -> None:
        if not self.monitors:
            raise DisplayError("display layout has no active logical monitors")
        if type(self.layout_mode) is not int or self.layout_mode != 1:
            raise DisplayError(f"unsupported Mutter layout mode: {self.layout_mode}")
        if any(type(monitor.primary) is not bool for monitor in self.monitors):
            raise DisplayError("monitor primary status must be boolean")
        primary_count = sum(monitor.primary for monitor in self.monitors)
        if primary_count != 1:
            raise DisplayError(
                "display layout must contain exactly one primary monitor"
            )
        for monitor in self.monitors:
            if (
                not isfinite(monitor.x)
                or not isfinite(monitor.y)
                or abs(monitor.x) > 1_000_000
                or abs(monitor.y) > 1_000_000
            ):
                raise DisplayError("monitor coordinates must be finite and reasonable")
            if (
                not isfinite(monitor.scale)
                or monitor.scale < 0.1
                or monitor.scale > 16
            ):
                raise DisplayError("monitor scale must be between 0.1 and 16")
            if (
                type(monitor.transform) is not int
                or monitor.transform not in VALID_TRANSFORMS
            ):
                raise DisplayError(f"unknown monitor transform: {monitor.transform}")
            if not monitor.connectors or any(
                not isinstance(connector, str) or not connector.strip()
                for connector in monitor.connectors
            ):
                raise DisplayError("logical monitor has no connectors")
            for physical in monitor.physical:
                if (
                    type(physical.width) is not int
                    or type(physical.height) is not int
                    or physical.width < 1
                    or physical.height < 1
                    or physical.width > 100_000
                    or physical.height > 100_000
                ):
                    raise DisplayError(
                        "physical monitor dimensions must be between 1 and 100000"
                    )
            width, height = monitor.logical_size
            if not isfinite(width) or not isfinite(height):
                raise DisplayError("logical monitor dimensions must be finite")
            if width <= 0 or height <= 0:
                raise DisplayError("logical monitor dimensions must be positive")

    @property
    def signature(self) -> str:
        payload = [
            {
                "x": monitor.x,
                "y": monitor.y,
                "scale": monitor.scale,
                "transform": monitor.transform,
                "primary": monitor.primary,
                "connectors": monitor.connectors,
                "physical": [
                    (physical.connector, physical.width, physical.height)
                    for physical in monitor.physical
                ],
            }
            for monitor in self.monitors
        ]
        text = dumps(
            {"layout_mode": self.layout_mode, "monitors": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(text.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CanvasRegion:
    connectors: tuple[str, ...]
    x: int
    y: int
    width: int
    height: int
    primary: bool


@dataclass(frozen=True, slots=True)
class CanvasLayout:
    width: int
    height: int
    backing_scale: float
    regions: tuple[CanvasRegion, ...]
    display_signature: str
    source: str
