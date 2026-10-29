from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import make_image, write_config
from PIL import Image, ImageChops, ImageFont

from countscape.config import AppConfig, OverlayConfig, load_config
from countscape.date_display import current_date_state
from countscape.errors import ConfigError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor
from countscape.mutter import discover_layout
from countscape.render import render_wallpaper, resolve_font
from countscape.state import read_json


def _date_config(root: Path, zone: str = "America/New_York", **settings) -> AppConfig:
    make_image(root / "photos" / "one.png", color=(40, 100, 180))
    config = load_config(write_config(root, **settings))
    return replace(
        config,
        event=None,
        overlay=OverlayConfig(
            mode="date", message="A good day", timezone=ZoneInfo(zone)
        ),
    )


def _metadata(config: AppConfig) -> dict:
    return read_json(config.wallpaper.output_directory / "render-state.json")


@pytest.mark.parametrize(
    "instant,zone,expected",
    [
        ("2026-01-02T00:30:00+00:00", "America/New_York", "Thursday, January 1, 2026"),
        ("2026-01-01T18:15:00+00:00", "Asia/Kathmandu", "Friday, January 2, 2026"),
        ("2026-10-29T12:00:00+00:00", "Etc/UTC", "Thursday, October 29, 2026"),
    ],
)
def test_current_date_uses_the_instant_in_the_iana_zone(
    instant: str, zone: str, expected: str
) -> None:
    state = current_date_state(datetime.fromisoformat(instant), ZoneInfo(zone))
    assert state.text == expected


def test_current_date_rejects_naive_time_and_missing_iana_zone() -> None:
    with pytest.raises(ConfigError, match="timezone-aware"):
        current_date_state(datetime(2026, 1, 1), ZoneInfo("Etc/UTC"))
    with pytest.raises(ConfigError, match="IANA timezone"):
        current_date_state(datetime(2026, 1, 1, tzinfo=UTC), None)


def test_local_midnight_updates_within_a_single_utc_refresh_bucket(
    tmp_path: Path,
) -> None:
    config = _date_config(
        tmp_path,
        zone="Asia/Kathmandu",
        countdown_refresh_seconds=3600,
        photo_rotation_seconds=86400,
    )
    layout = discover_layout(config.display)
    before = datetime(2026, 1, 1, 18, 14, 59, tzinfo=UTC)
    first = render_wallpaper(config, layout, now=before)
    first_state = _metadata(config)
    second = render_wallpaper(config, layout, now=before + timedelta(seconds=1))
    second_state = _metadata(config)

    assert first != second
    assert first_state["text_bucket"] == second_state["text_bucket"]
    assert first_state["bucket"] == second_state["bucket"]
    assert first_state["render_key"]["overlay"]["date"] == "2026-01-01"
    assert second_state["render_key"]["overlay"]["date"] == "2026-01-02"
    assert "event" not in second_state["render_key"]


@pytest.mark.parametrize(
    "before,after",
    [
        ("2026-03-08T06:59:00+00:00", "2026-03-08T07:01:00+00:00"),
        ("2026-11-01T05:59:00+00:00", "2026-11-01T06:01:00+00:00"),
    ],
)
def test_dst_clock_changes_within_the_date_reuse_rendered_output(
    tmp_path: Path, before: str, after: str
) -> None:
    config = _date_config(tmp_path, photo_rotation_seconds=86400)
    layout = discover_layout(config.display)
    first = render_wallpaper(config, layout, now=datetime.fromisoformat(before))
    state_file = config.wallpaper.output_directory / "render-state.json"
    saved = (state_file.read_bytes(), state_file.stat().st_mtime_ns)

    assert render_wallpaper(config, layout, now=datetime.fromisoformat(after)) == first
    assert (state_file.read_bytes(), state_file.stat().st_mtime_ns) == saved


def test_date_render_recovers_from_suspend_and_backward_clock_changes(
    tmp_path: Path,
) -> None:
    config = _date_config(tmp_path)
    layout = discover_layout(config.display)
    start = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    first = render_wallpaper(config, layout, now=start)
    later = render_wallpaper(config, layout, now=start + timedelta(days=3))
    assert first != later
    assert _metadata(config)["render_key"]["overlay"]["date"] == "2026-06-04"
    restored = render_wallpaper(config, layout, now=start)
    assert restored == first
    assert _metadata(config)["render_key"]["overlay"]["date"] == "2026-06-01"


def test_date_render_and_base_are_immutable_on_an_unchanged_poll(
    tmp_path: Path,
) -> None:
    config = _date_config(tmp_path)
    source = config.wallpaper.source_directory / "one.png"
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
    layout = discover_layout(config.display)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    first = render_wallpaper(config, layout, now=now)
    paths = (
        first,
        config.wallpaper.output_directory / "render-state.json",
        config.wallpaper.cache_directory / "base.png",
        config.wallpaper.cache_directory / "base.json",
    )
    saved = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

    assert render_wallpaper(config, layout, now=now + timedelta(minutes=1)) == first
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    } == saved
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before


def test_photo_rotates_independently_while_the_displayed_date_is_unchanged(
    tmp_path: Path,
) -> None:
    config = _date_config(tmp_path, photo_rotation_seconds=120)
    make_image(tmp_path / "photos" / "two.png", color=(180, 100, 40))
    layout = discover_layout(config.display)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    first = render_wallpaper(config, layout, now=now)
    first_state = _metadata(config)
    second = render_wallpaper(config, layout, now=now + timedelta(minutes=2))
    second_state = _metadata(config)

    assert first != second
    assert first_state["photo"] != second_state["photo"]
    assert first_state["render_key"]["overlay"] == second_state["render_key"]["overlay"]


def test_date_cache_tracks_message_and_zone_but_ignores_inactive_event(
    configured_project: tuple[AppConfig, Path],
) -> None:
    legacy, _source = configured_project
    config = replace(
        legacy,
        overlay=OverlayConfig("date", "A good day", ZoneInfo("Etc/UTC")),
    )
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    layout = discover_layout(config.display)
    first = render_wallpaper(config, layout, now=now)
    inactive_change = replace(config, event=replace(config.event, label="Unused label"))
    assert render_wallpaper(inactive_change, layout, now=now) == first
    changed_message = replace(
        config, overlay=replace(config.overlay, message="Welcome")
    )
    assert render_wallpaper(changed_message, layout, now=now) != first
    changed_zone = replace(
        config, overlay=replace(config.overlay, timezone=ZoneInfo("UTC"))
    )
    assert render_wallpaper(changed_zone, layout, now=now) != first
    assert render_wallpaper(legacy, layout, now=now) != first


def test_unicode_message_and_date_fit_portrait_and_landscape_regions(
    tmp_path: Path,
) -> None:
    config = _date_config(tmp_path)
    config = replace(
        config,
        overlay=replace(config.overlay, message="❤️ Welcome ❤️ " * 10),
    )
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("portrait-fixture",),
                physical=(PhysicalMonitor("portrait-fixture", 320, 480),),
            ),
            LogicalMonitor(
                x=320,
                y=0,
                scale=1,
                transform=0,
                primary=False,
                connectors=("landscape-fixture",),
                physical=(PhysicalMonitor("landscape-fixture", 640, 480),),
            ),
        ),
        layout_mode=1,
        source="fixture",
    )
    output = render_wallpaper(
        config, layout, now=datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    )
    with Image.open(output) as image:
        assert image.size == (960, 480)
        for box in ((0, 0, 320, 480), (320, 0, 960, 480)):
            region = image.crop(box)
            assert (
                ImageChops.difference(
                    region, Image.new("RGB", region.size, (40, 100, 180))
                ).getbbox()
                is not None
            )


def test_default_font_selection_can_render_a_unicode_heart() -> None:
    font = ImageFont.truetype(
        str(resolve_font(None, text="❤️ Welcome ❤️ Thursday, October 29, 2026")),
        40,
    )
    assert bytes(font.getmask("❤️")) != bytes(font.getmask("\U0010ffff"))


def test_font_query_requests_visible_unicode_characters_only() -> None:
    discovered = resolve_font(None)
    commands = []

    def fontconfig(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, str(discovered), "")

    assert resolve_font(None, runner=fontconfig, text="❤️ Welcome ❤️") == discovered
    charset = commands[0][-1].split(":charset=", 1)[1].split()
    assert "2764" in charset
    assert "fe0f" not in charset
