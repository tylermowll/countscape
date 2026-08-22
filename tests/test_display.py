from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from countscape.config import DisplayConfig
from countscape.display import build_canvas_layout
from countscape.errors import DisplayError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor
from countscape.mutter import (
    DISPLAY_SIGNATURE,
    discover_layout,
    parse_current_state,
)


def _mode(
    mode_id: str,
    width: int,
    height: int,
    *,
    current: bool = True,
) -> list[object]:
    properties = {"is-current": {"type": "b", "data": True}} if current else {}
    return [mode_id, width, height, 60.0, 1.0, [1.0, 2.0], properties]


def _monitor(connector: str, width: int, height: int) -> list[object]:
    spec = [connector, "vendor", "product", "serial"]
    return [spec, [_mode(f"{width}x{height}", width, height)], {}]


def _payload(
    monitors: list[object],
    logical: list[object],
    *,
    signature: str = DISPLAY_SIGNATURE,
) -> str:
    return json.dumps(
        {
            "type": signature,
            "data": [
                1,
                monitors,
                logical,
                {"layout-mode": {"type": "u", "data": 1}},
            ],
        }
    )


def test_parse_verified_single_display_shape() -> None:
    payload = Path("tests/fixtures/mutter-single-display.json").read_text(
        encoding="utf-8"
    )
    layout = parse_current_state(payload)
    canvas = build_canvas_layout(layout, max_pixels=100_000_000)
    assert layout.source == "mutter"
    assert (canvas.width, canvas.height) == (1920, 1080)
    assert canvas.regions[0].connectors == ("Virtual-1",)


def test_mixed_rotated_negative_layout_and_shared_edges() -> None:
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=-1200,
                y=0,
                scale=1,
                transform=1,
                primary=False,
                connectors=("portrait",),
                physical=(PhysicalMonitor("portrait", 1920, 1200),),
            ),
            LogicalMonitor(
                x=0,
                y=240,
                scale=1,
                transform=0,
                primary=True,
                connectors=("landscape",),
                physical=(PhysicalMonitor("landscape", 2560, 1440),),
            ),
        ),
        layout_mode=1,
        source="test",
    )
    canvas = build_canvas_layout(layout, max_pixels=100_000_000)
    assert (canvas.width, canvas.height) == (3760, 1920)
    assert canvas.regions[0].width == 1200
    assert canvas.regions[0].height == 1920
    assert canvas.regions[1].x == 1200


def test_mirrored_members_share_one_region() -> None:
    payload = _payload(
        [_monitor("HDMI-1", 1920, 1080), _monitor("DP-1", 1920, 1080)],
        [
            [
                0,
                0,
                1.0,
                0,
                True,
                [
                    ["HDMI-1", "v", "p", "a"],
                    ["DP-1", "v", "p", "b"],
                ],
                {},
            ]
        ],
    )
    canvas = build_canvas_layout(
        parse_current_state(payload),
        max_pixels=100_000_000,
    )
    assert len(canvas.regions) == 1
    assert canvas.regions[0].connectors == ("HDMI-1", "DP-1")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "invalid JSON"),
        (_payload([], [], signature="wrong"), "unexpected"),
        (_payload([], []), "no active"),
    ],
)
def test_bad_mutter_state_is_rejected(payload: str, message: str) -> None:
    with pytest.raises(DisplayError, match=message):
        parse_current_state(payload)


def test_canvas_pixel_guard() -> None:
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=2,
                transform=0,
                primary=True,
                connectors=("panel",),
                physical=(PhysicalMonitor("panel", 3840, 2160),),
            ),
        ),
        layout_mode=1,
        source="test",
    )
    with pytest.raises(DisplayError, match="safety limit"):
        build_canvas_layout(layout, max_pixels=1_000_000)


def test_unknown_layout_mode_and_overlaps_are_rejected() -> None:
    monitor = LogicalMonitor(
        x=0,
        y=0,
        scale=1,
        transform=0,
        primary=True,
        connectors=("one",),
        physical=(PhysicalMonitor("one", 100, 100),),
    )
    with pytest.raises(DisplayError, match="layout mode"):
        build_canvas_layout(
            DisplayLayout(monitors=(monitor,), layout_mode=99, source="test"),
            max_pixels=1_000_000,
        )
    second = LogicalMonitor(
        x=50,
        y=0,
        scale=1,
        transform=0,
        primary=False,
        connectors=("two",),
        physical=(PhysicalMonitor("two", 100, 100),),
    )
    with pytest.raises(DisplayError, match="overlap"):
        build_canvas_layout(
            DisplayLayout(
                monitors=(monitor, second),
                layout_mode=1,
                source="test",
            ),
            max_pixels=1_000_000,
        )


def test_non_graphical_session_uses_fallback() -> None:
    fallback = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("fallback",),
                physical=(PhysicalMonitor("fallback", 800, 600),),
            ),
        ),
        layout_mode=1,
        source="profile:fallback",
    )

    def failed_runner(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "no session bus")

    layout = discover_layout(
        DisplayConfig(
            mode="auto",
            fallback_profile="fallback",
            profiles={"fallback": fallback},
        ),
        runner=failed_runner,
    )
    assert layout.source == "profile:fallback"
    with pytest.raises(DisplayError, match="no session bus"):
        discover_layout(
            DisplayConfig(
                mode="auto",
                fallback_profile=None,
                profiles={},
            ),
            runner=failed_runner,
        )
