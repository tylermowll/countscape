from __future__ import annotations

from math import isfinite

from countscape.errors import DisplayError
from countscape.models import CanvasLayout, CanvasRegion, DisplayLayout


def build_canvas_layout(
    layout: DisplayLayout,
    *,
    max_pixels: int,
) -> CanvasLayout:
    layout.validate()
    logical_bounds: list[tuple[float, float, float, float]] = []
    for monitor in layout.monitors:
        width, height = monitor.logical_size
        bounds = (monitor.x, monitor.y, monitor.x + width, monitor.y + height)
        if not all(isfinite(value) for value in bounds):
            raise DisplayError("display bounds must be finite")
        logical_bounds.append(bounds)

    min_x = min(bound[0] for bound in logical_bounds)
    min_y = min(bound[1] for bound in logical_bounds)
    max_x = max(bound[2] for bound in logical_bounds)
    max_y = max(bound[3] for bound in logical_bounds)
    backing_scale = max(monitor.scale for monitor in layout.monitors)

    def edge(value: float, origin: float) -> int:
        return round((value - origin) * backing_scale)

    canvas_width = edge(max_x, min_x)
    canvas_height = edge(max_y, min_y)
    if canvas_width <= 0 or canvas_height <= 0:
        raise DisplayError("normalized canvas dimensions must be positive")
    if canvas_width * canvas_height > max_pixels:
        raise DisplayError(
            f"canvas {canvas_width}x{canvas_height} exceeds "
            f"the {max_pixels:,}-pixel safety limit"
        )

    regions: list[CanvasRegion] = []
    for monitor, bounds in zip(layout.monitors, logical_bounds, strict=True):
        left = edge(bounds[0], min_x)
        top = edge(bounds[1], min_y)
        right = edge(bounds[2], min_x)
        bottom = edge(bounds[3], min_y)
        region = CanvasRegion(
            connectors=monitor.connectors,
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
            primary=monitor.primary,
        )
        if (
            region.width <= 0
            or region.height <= 0
            or region.x < 0
            or region.y < 0
            or region.x + region.width > canvas_width
            or region.y + region.height > canvas_height
        ):
            raise DisplayError(f"invalid normalized region: {region}")
        regions.append(region)

    for index, first in enumerate(regions):
        for second in regions[index + 1 :]:
            overlaps = (
                first.x < second.x + second.width
                and first.x + first.width > second.x
                and first.y < second.y + second.height
                and first.y + first.height > second.y
            )
            if overlaps:
                raise DisplayError(
                    "normalized logical monitor regions overlap: "
                    f"{first.connectors} and {second.connectors}"
                )

    return CanvasLayout(
        width=canvas_width,
        height=canvas_height,
        backing_scale=backing_scale,
        regions=tuple(regions),
        display_signature=layout.signature,
        source=layout.source,
    )
