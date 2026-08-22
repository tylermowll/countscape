from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_image, write_config
from PIL import Image, ImageChops

from countscape.config import AppConfig, load_config
from countscape.errors import CountdownError, StateError
from countscape.models import (
    DisplayLayout,
    LogicalMonitor,
    PhysicalMonitor,
)
from countscape.mutter import discover_layout
from countscape.render import render_calibration, render_wallpaper
from countscape.state import operation_lock, read_json


def test_render_has_expected_dimensions_and_alternates_photo_specific_uri(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, source = configured_project
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    layout = discover_layout(config.display)
    first = render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    second = render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 1, tzinfo=UTC),
    )
    assert first != second
    for output in (first, second):
        identity = output.stem.removeprefix("wallpaper-")
        assert len(identity) == 24
        assert all(character in "0123456789abcdef" for character in identity)
    with Image.open(second) as image:
        assert image.size == (800, 600)
        assert image.format == "PNG"
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_render_reuses_existing_output_on_a_true_no_op(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    output = render_wallpaper(config, layout, now=now)
    state = config.wallpaper.output_directory / "render-state.json"
    base = config.wallpaper.cache_directory / "base.png"
    metadata = config.wallpaper.cache_directory / "base.json"
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (output, state, base, metadata)
    }

    reused = render_wallpaper(config, layout, now=now + timedelta(seconds=30))

    assert reused == output
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (output, state, base, metadata)
    } == before


def test_post_arrival_poll_is_an_immutable_no_op_until_photo_rotation(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    after_arrival = datetime(2027, 6, 2, 12, 0, tzinfo=UTC)
    output = render_wallpaper(config, layout, now=after_arrival)
    managed_files = tuple(
        sorted(
            (
                *config.wallpaper.output_directory.iterdir(),
                *config.wallpaper.cache_directory.iterdir(),
            )
        )
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in managed_files
        if path.is_file()
    }

    reused = render_wallpaper(
        config,
        layout,
        now=after_arrival + timedelta(minutes=5),
    )

    assert reused == output
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in managed_files
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    (
        "countdown_refresh_seconds",
        "photo_rotation_seconds",
        "countdown_changed",
        "photo_changed",
    ),
    (
        (300, 600, True, False),
        (600, 300, False, True),
    ),
)
def test_countdown_and_photo_buckets_advance_independently(
    tmp_path: Path,
    countdown_refresh_seconds: int,
    photo_rotation_seconds: int,
    countdown_changed: bool,
    photo_changed: bool,
) -> None:
    photo_root = tmp_path / "photos"
    make_image(photo_root / "one.jpg", color=(200, 20, 20))
    make_image(photo_root / "two.jpg", color=(20, 20, 200))
    config = load_config(
        write_config(
            tmp_path,
            countdown_refresh_seconds=countdown_refresh_seconds,
            photo_rotation_seconds=photo_rotation_seconds,
        )
    )
    layout = discover_layout(config.display)
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    first_output = render_wallpaper(config, layout, now=start)
    first_state = read_json(config.wallpaper.output_directory / "render-state.json")
    first_base = read_json(config.wallpaper.cache_directory / "base.json")
    second_output = render_wallpaper(
        config,
        layout,
        now=start + timedelta(minutes=5),
    )
    second_state = read_json(config.wallpaper.output_directory / "render-state.json")
    second_base = read_json(config.wallpaper.cache_directory / "base.json")

    assert first_output != second_output
    assert (
        first_state["render_key"]["countdown_text"]
        != second_state["render_key"]["countdown_text"]
    ) is countdown_changed
    assert (first_state["text_bucket"] != second_state["text_bucket"]) is (
        countdown_changed
    )
    assert (first_state["bucket"] != second_state["bucket"]) is photo_changed
    assert (first_state["photo"] != second_state["photo"]) is photo_changed
    assert (first_base != second_base) is photo_changed


def test_arrival_and_backward_clock_transition_toggle_uri_within_one_bucket(
    tmp_path: Path,
) -> None:
    make_image(tmp_path / "photos" / "photo.jpg")
    config = load_config(
        write_config(
            tmp_path,
            target="2030-01-01T12:02:00+00:00",
            timezone="Etc/UTC",
            after_arrival_message="The observatory opens!",
            countdown_refresh_seconds=300,
            photo_rotation_seconds=600,
        )
    )
    layout = discover_layout(config.display)
    before = datetime(2030, 1, 1, 12, 1, tzinfo=UTC)
    after = datetime(2030, 1, 1, 12, 3, tzinfo=UTC)
    backward = datetime(2030, 1, 1, 12, 1, 30, tzinfo=UTC)

    before_output = render_wallpaper(config, layout, now=before)
    before_state = read_json(config.wallpaper.output_directory / "render-state.json")
    after_output = render_wallpaper(config, layout, now=after)
    after_state = read_json(config.wallpaper.output_directory / "render-state.json")
    backward_output = render_wallpaper(config, layout, now=backward)
    backward_state = read_json(config.wallpaper.output_directory / "render-state.json")

    assert before_state["text_bucket"] == after_state["text_bucket"]
    assert after_state["text_bucket"] == backward_state["text_bucket"]
    assert before_state["bucket"] == after_state["bucket"]
    assert after_state["bucket"] == backward_state["bucket"]
    assert before_state["render_key"]["arrived"] is False
    assert after_state["render_key"]["arrived"] is True
    assert backward_state["render_key"]["arrived"] is False
    assert after_state["render_key"]["countdown_text"] == "The observatory opens!"
    assert (
        backward_state["render_key"]["countdown_text"]
        == before_state["render_key"]["countdown_text"]
    )
    assert before_output != after_output
    assert after_output != backward_output


def test_long_unicode_completion_message_fits_a_small_display(tmp_path: Path) -> None:
    message = "星光庆典现在开始！" * 12
    make_image(tmp_path / "photos" / "photo.jpg", size=(320, 240))
    config = load_config(
        write_config(
            tmp_path,
            label="星空节",
            after_arrival_message=message,
        )
    )
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("small-fixture",),
                physical=(PhysicalMonitor("small-fixture", 320, 240),),
            ),
        ),
        layout_mode=1,
        source="test",
    )

    output = render_wallpaper(
        config,
        layout,
        now=datetime(2027, 6, 2, 12, 0, tzinfo=UTC),
    )

    with Image.open(output) as image:
        assert image.size == (320, 240)
        image.verify()
    state = read_json(config.wallpaper.output_directory / "render-state.json")
    assert state["render_key"]["arrived"] is True
    assert state["render_key"]["countdown_text"] == message


def test_bottom_overlay_stays_in_lower_half(tmp_path: Path) -> None:
    color = (40, 100, 180)
    make_image(tmp_path / "photos" / "photo.png", color=color)
    config = load_config(write_config(tmp_path, overlay_position="bottom"))
    layout = discover_layout(config.display)

    output = render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    with Image.open(output) as image:
        plain_background = Image.new("RGB", image.size, color)
        overlay_bounds = ImageChops.difference(
            image.convert("RGB"),
            plain_background,
        ).getbbox()
        assert overlay_bounds is not None
        assert overlay_bounds[1] > image.height // 2


def test_all_regions_contain_entire_photo_with_black_padding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "photos" / "photo.png"
    source.parent.mkdir(parents=True)
    source_image = Image.new("RGB", (1600, 900), (40, 180, 80))
    source_image.paste((200, 40, 40), (0, 0, 320, 900))
    source_image.paste((40, 80, 200), (1280, 0, 1600, 900))
    source_image.save(source)
    config = load_config(write_config(tmp_path, photo_fit="contain"))
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=False,
                connectors=("portrait",),
                physical=(
                    PhysicalMonitor(
                        connector="portrait",
                        width=600,
                        height=800,
                    ),
                ),
            ),
            LogicalMonitor(
                x=600,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("landscape",),
                physical=(
                    PhysicalMonitor(
                        connector="landscape",
                        width=800,
                        height=600,
                    ),
                ),
            ),
        ),
        layout_mode=1,
        source="test",
    )
    before = source.read_bytes()

    render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    with Image.open(config.wallpaper.cache_directory / "base.png") as base:
        assert base.getpixel((300, 0)) == (0, 0, 0)
        assert base.getpixel((300, 200)) == (0, 0, 0)
        assert base.getpixel((0, 400)) == (200, 40, 40)
        assert base.getpixel((300, 400)) == (40, 180, 80)
        assert base.getpixel((599, 400)) == (40, 80, 200)
        assert base.getpixel((300, 600)) == (0, 0, 0)
        assert base.getpixel((1000, 0)) == (0, 0, 0)
        assert base.getpixel((600, 300)) == (200, 40, 40)
        assert base.getpixel((1000, 300)) == (40, 180, 80)
        assert base.getpixel((1399, 300)) == (40, 80, 200)
        assert base.getpixel((1000, 599)) == (0, 0, 0)
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    ("source_size", "expected_photo_bounds"),
    (
        ((800, 600), (100, 700)),
        ((400, 600), (250, 550)),
    ),
)
def test_landscape_region_pads_taller_photos_without_cropping(
    tmp_path: Path,
    source_size: tuple[int, int],
    expected_photo_bounds: tuple[int, int],
) -> None:
    color = (160, 70, 30)
    source = make_image(
        tmp_path / "photos" / "photo.png",
        size=source_size,
        color=color,
    )
    config = load_config(write_config(tmp_path, photo_fit="contain"))
    layout = DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("landscape",),
                physical=(
                    PhysicalMonitor(
                        connector="landscape",
                        width=800,
                        height=450,
                    ),
                ),
            ),
        ),
        layout_mode=1,
        source="test",
    )
    before = source.read_bytes()

    render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    left, right = expected_photo_bounds
    with Image.open(config.wallpaper.cache_directory / "base.png") as base:
        assert base.size == (800, 450)
        assert base.getpixel((0, 225)) == (0, 0, 0)
        assert base.getpixel((left + 10, 0)) == color
        assert base.getpixel((400, 225)) == color
        assert base.getpixel((right - 10, 449)) == color
        assert base.getpixel((799, 225)) == (0, 0, 0)
    assert source.read_bytes() == before


def test_cover_fit_is_opt_in_and_invalidates_contain_cache(tmp_path: Path) -> None:
    color = (70, 150, 40)
    make_image(
        tmp_path / "photos" / "photo.png",
        size=(1600, 900),
        color=color,
    )
    config = load_config(write_config(tmp_path, photo_fit="contain"))
    layout = discover_layout(config.display)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    render_wallpaper(config, layout, now=now)
    contain_key = read_json(config.wallpaper.cache_directory / "base.json")
    with Image.open(config.wallpaper.cache_directory / "base.png") as base:
        assert base.getpixel((400, 0)) == (0, 0, 0)

    cover_config = replace(
        config,
        style=replace(config.style, photo_fit="cover"),
    )
    render_wallpaper(cover_config, layout, now=now + timedelta(minutes=1))
    cover_key = read_json(config.wallpaper.cache_directory / "base.json")

    assert contain_key["photo_fit"] == "contain"
    assert cover_key["photo_fit"] == "cover"
    assert contain_key != cover_key
    with Image.open(config.wallpaper.cache_directory / "base.png") as base:
        assert base.getpixel((400, 0)) == color
        assert base.getpixel((400, 599)) == color


def test_photo_base_changes_only_at_bucket_boundary(tmp_path: Path) -> None:
    photo_root = tmp_path / "photos"
    make_image(photo_root / "one.jpg", color=(200, 20, 20))
    make_image(photo_root / "two.jpg", color=(20, 20, 200))
    config = load_config(write_config(tmp_path))
    layout = discover_layout(config.display)
    start = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    first_output = render_wallpaper(config, layout, now=start)
    first = read_json(config.wallpaper.cache_directory / "base.json")
    first_render = read_json(config.wallpaper.output_directory / "render-state.json")
    render_wallpaper(config, layout, now=start + timedelta(minutes=1))
    same = read_json(config.wallpaper.cache_directory / "base.json")
    changed_output = render_wallpaper(
        config,
        layout,
        now=start + timedelta(minutes=10),
    )
    changed = read_json(config.wallpaper.cache_directory / "base.json")
    changed_render = read_json(config.wallpaper.output_directory / "render-state.json")
    assert first == same
    assert changed_render["bucket"] == first_render["bucket"] + 1
    assert changed["selected"] != first["selected"]
    assert changed_output != first_output


def test_photo_base_supports_five_second_bucket_boundary(tmp_path: Path) -> None:
    photo_root = tmp_path / "photos"
    make_image(photo_root / "one.jpg", color=(200, 20, 20))
    make_image(photo_root / "two.jpg", color=(20, 20, 200))
    config = load_config(write_config(tmp_path, photo_rotation_seconds=5))
    layout = discover_layout(config.display)
    start = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    render_wallpaper(config, layout, now=start)
    first = read_json(config.wallpaper.cache_directory / "base.json")
    first_render = read_json(config.wallpaper.output_directory / "render-state.json")
    render_wallpaper(config, layout, now=start + timedelta(seconds=4))
    same = read_json(config.wallpaper.cache_directory / "base.json")
    render_wallpaper(config, layout, now=start + timedelta(seconds=5))
    changed = read_json(config.wallpaper.cache_directory / "base.json")
    changed_render = read_json(config.wallpaper.output_directory / "render-state.json")

    assert first == same
    assert changed_render["bucket"] == first_render["bucket"] + 1
    assert changed["selected"] != first["selected"]


def test_rotation_continues_after_arrival(tmp_path: Path) -> None:
    photo_root = tmp_path / "photos"
    make_image(photo_root / "one.jpg", color=(200, 20, 20))
    make_image(photo_root / "two.jpg", color=(20, 20, 200))
    config = load_config(write_config(tmp_path))
    layout = discover_layout(config.display)
    after = datetime(2027, 6, 20, 12, 0, tzinfo=UTC)
    render_wallpaper(config, layout, now=after)
    first = read_json(config.wallpaper.output_directory / "render-state.json")
    render_wallpaper(config, layout, now=after + timedelta(minutes=10))
    second = read_json(config.wallpaper.output_directory / "render-state.json")
    assert first["photo"] != second["photo"]


def test_calibration_does_not_need_photo_pool(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    output = render_calibration(config, discover_layout(config.display))
    with Image.open(output) as image:
        assert image.size == (800, 600)


def test_corrupt_cache_is_rebuilt(configured_project: tuple[AppConfig, Path]) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    render_wallpaper(config, layout, now=now)
    base = config.wallpaper.cache_directory / "base.png"
    base.write_text("corrupt", encoding="utf-8")
    render_wallpaper(config, layout, now=now + timedelta(minutes=1))
    with Image.open(base) as image:
        assert image.size == (800, 600)


def test_pre_release_render_state_schema_is_rejected(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    state_path = config.wallpaper.output_directory / "render-state.json"
    render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    state_path.write_text('{"version": 1}\n', encoding="utf-8")

    with pytest.raises(StateError, match="unsupported schema"):
        render_wallpaper(
            config,
            layout,
            now=datetime(2026, 8, 1, 12, 1, tzinfo=UTC),
        )

    assert state_path.read_text(encoding="utf-8") == '{"version": 1}\n'


def test_failed_save_keeps_previous_output(
    configured_project: tuple[AppConfig, Path],
    monkeypatch,
) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    first = render_wallpaper(config, layout, now=now)
    before = first.read_bytes()

    def failed_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(Image.Image, "save", failed_save)
    with pytest.raises(OSError, match="simulated write failure"):
        render_wallpaper(config, layout, now=now + timedelta(minutes=1))
    assert first.read_bytes() == before
    assert not tuple(config.wallpaper.output_directory.glob(".*.png"))


def test_concurrent_render_is_rejected(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, _source = configured_project
    layout = discover_layout(config.display)
    render_wallpaper(
        config,
        layout,
        now=datetime(2026, 8, 1, 11, 59, tzinfo=UTC),
    )
    with (
        operation_lock(config.wallpaper.output_directory),
        pytest.raises(CountdownError, match="already running"),
    ):
        render_wallpaper(
            config,
            layout,
            now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        )


def test_render_refuses_preexisting_output_lock_sentinel(
    configured_project: tuple[AppConfig, Path],
) -> None:
    config, _source = configured_project
    output = config.wallpaper.output_directory
    output.mkdir(parents=True)
    sentinel = output / ".countscape.lock"
    sentinel.write_text("user lock sentinel\n", encoding="utf-8")

    with pytest.raises(StateError, match="unowned.*reserved files"):
        render_wallpaper(
            config,
            discover_layout(config.display),
            now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        )

    assert sentinel.read_text(encoding="utf-8") == "user lock sentinel\n"
    assert not (output / ".countscape-owned.json").exists()
