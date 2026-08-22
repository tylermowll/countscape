from __future__ import annotations

from dataclasses import replace
from math import inf, nan

import pytest

from countscape.errors import DisplayError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor


def _monitor(**overrides: object) -> LogicalMonitor:
    values: dict[str, object] = {
        "x": 0.0,
        "y": 0.0,
        "scale": 1.0,
        "transform": 0,
        "primary": True,
        "connectors": ("EXAMPLE-1",),
        "physical": (PhysicalMonitor("EXAMPLE-1", 1920, 1080),),
    }
    values.update(overrides)
    return LogicalMonitor(**values)  # type: ignore[arg-type]


def test_logical_size_applies_rotation_and_accepts_one_pixel_mirror_tolerance() -> None:
    monitor = _monitor(
        scale=2.0,
        transform=1,
        connectors=("EXAMPLE-1", "EXAMPLE-2"),
        physical=(
            PhysicalMonitor("EXAMPLE-1", 1920, 1080),
            PhysicalMonitor("EXAMPLE-2", 1919, 1080),
        ),
    )

    assert monitor.logical_size == (540, 960)


def test_logical_size_rejects_missing_or_incompatible_physical_monitors() -> None:
    with pytest.raises(DisplayError, match="no physical monitor"):
        _ = _monitor(physical=()).logical_size

    mirrored = _monitor(
        connectors=("EXAMPLE-1", "EXAMPLE-2"),
        physical=(
            PhysicalMonitor("EXAMPLE-1", 1920, 1080),
            PhysicalMonitor("EXAMPLE-2", 1600, 900),
        ),
    )
    with pytest.raises(DisplayError, match="mirrored monitors"):
        _ = mirrored.logical_size


@pytest.mark.parametrize(
    ("monitor", "message"),
    (
        (_monitor(primary=1), "primary status"),
        (_monitor(x=nan), "coordinates"),
        (_monitor(y=1_000_001), "coordinates"),
        (_monitor(scale=inf), "scale"),
        (_monitor(scale=0.09), "scale"),
        (_monitor(transform=True), "transform"),
        (_monitor(transform=8), "transform"),
        (_monitor(connectors=()), "no connectors"),
        (_monitor(connectors=(" ",)), "no connectors"),
        (_monitor(connectors=(1,)), "no connectors"),
        (
            _monitor(physical=(PhysicalMonitor("EXAMPLE-1", True, 1080),)),
            "physical monitor dimensions",
        ),
        (
            _monitor(physical=(PhysicalMonitor("EXAMPLE-1", 100_001, 1080),)),
            "physical monitor dimensions",
        ),
    ),
)
def test_display_layout_rejects_invalid_monitor_invariants(
    monitor: LogicalMonitor,
    message: str,
) -> None:
    with pytest.raises(DisplayError, match=message):
        DisplayLayout(monitors=(monitor,), layout_mode=1, source="test").validate()


def test_display_layout_requires_one_primary_and_integer_layout_mode() -> None:
    with pytest.raises(DisplayError, match="no active"):
        DisplayLayout(monitors=(), layout_mode=1, source="test").validate()
    with pytest.raises(DisplayError, match="layout mode"):
        DisplayLayout(
            monitors=(_monitor(),),
            layout_mode=True,
            source="test",
        ).validate()
    with pytest.raises(DisplayError, match="exactly one primary"):
        DisplayLayout(
            monitors=(_monitor(primary=False),),
            layout_mode=1,
            source="test",
        ).validate()
    with pytest.raises(DisplayError, match="exactly one primary"):
        DisplayLayout(
            monitors=(_monitor(), replace(_monitor(), connectors=("EXAMPLE-2",))),
            layout_mode=1,
            source="test",
        ).validate()


class _DefensiveMonitor:
    x = 0.0
    y = 0.0
    scale = 1.0
    transform = 0
    primary = True
    connectors = ("EXAMPLE-1",)
    physical: tuple[PhysicalMonitor, ...] = ()

    def __init__(self, logical_size: tuple[float, float]) -> None:
        self.logical_size = logical_size


@pytest.mark.parametrize(
    ("size", "message"),
    (((inf, 1.0), "finite"), ((0.0, 1.0), "positive")),
)
def test_display_layout_defensively_checks_resolved_logical_size(
    size: tuple[float, float],
    message: str,
) -> None:
    layout = DisplayLayout(
        monitors=(_DefensiveMonitor(size),),  # type: ignore[arg-type]
        layout_mode=1,
        source="test",
    )
    with pytest.raises(DisplayError, match=message):
        layout.validate()


def test_display_signature_is_deterministic_and_tracks_geometry() -> None:
    monitor = _monitor()
    first = DisplayLayout(monitors=(monitor,), layout_mode=1, source="mutter")
    same_geometry = DisplayLayout(
        monitors=(monitor,),
        layout_mode=1,
        source="profile:desk",
    )
    changed = DisplayLayout(
        monitors=(replace(monitor, x=1.0),),
        layout_mode=1,
        source="mutter",
    )

    assert first.signature == same_geometry.signature
    assert first.signature != changed.signature
    assert len(first.signature) == 64
