from __future__ import annotations

from dataclasses import dataclass
from math import inf

import pytest

from countscape.display import build_canvas_layout
from countscape.errors import DisplayError


@dataclass(frozen=True)
class _RawMonitor:
    x: float
    y: float
    scale: float
    connectors: tuple[str, ...]
    primary: bool
    logical_size: tuple[float, float]


@dataclass(frozen=True)
class _RawLayout:
    monitors: tuple[_RawMonitor, ...]
    signature: str = "synthetic-signature"
    source: str = "synthetic"

    def validate(self) -> None:
        """Let this test exercise build_canvas_layout's defensive checks."""


def _monitor(
    *,
    x: float = 0,
    width: float = 100,
    height: float = 100,
    connector: str = "EXAMPLE-1",
    primary: bool = True,
) -> _RawMonitor:
    return _RawMonitor(
        x=x,
        y=0,
        scale=1,
        connectors=(connector,),
        primary=primary,
        logical_size=(width, height),
    )


def test_canvas_rejects_nonfinite_bounds_even_after_adapter_validation() -> None:
    layout = _RawLayout(monitors=(_monitor(width=inf),))

    with pytest.raises(DisplayError, match="bounds must be finite"):
        build_canvas_layout(layout, max_pixels=1_000_000)  # type: ignore[arg-type]


def test_canvas_rejects_geometry_that_rounds_to_an_empty_canvas() -> None:
    layout = _RawLayout(monitors=(_monitor(width=0.1, height=0.1),))

    with pytest.raises(DisplayError, match="canvas dimensions must be positive"):
        build_canvas_layout(layout, max_pixels=1_000_000)  # type: ignore[arg-type]


def test_canvas_rejects_a_region_that_rounds_to_zero_inside_valid_bounds() -> None:
    layout = _RawLayout(
        monitors=(
            _monitor(width=0.1),
            _monitor(x=1, width=100, connector="EXAMPLE-2", primary=False),
        )
    )

    with pytest.raises(DisplayError, match="invalid normalized region"):
        build_canvas_layout(layout, max_pixels=1_000_000)  # type: ignore[arg-type]
