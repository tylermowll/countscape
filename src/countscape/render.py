from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from countscape.config import AppConfig
from countscape.countdown import CountdownState, calculate_countdown
from countscape.display import build_canvas_layout
from countscape.errors import CountdownError
from countscape.models import CanvasLayout, CanvasRegion, DisplayLayout
from countscape.photos import (
    PhotoPool,
    photo_bucket,
    scan_photo_pool,
    select_photo,
)
from countscape.state import (
    atomic_write_json,
    ensure_owned_directory,
    operation_lock,
    read_json,
)

FONT_COMMAND = (
    "fc-match",
    "-f",
    "%{file}",
    "sans-serif:style=Bold",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]
GENERATED_WALLPAPER_NAME = re.compile(r"wallpaper-[0-9a-f]{24}\.png")
GENERATED_CALIBRATION_NAME = re.compile(r"calibration-[0-9a-f]{24}\.png")
_OUTPUT_RESERVED = frozenset({"render-state.json", "calibration.png"})
_CACHE_RESERVED = frozenset({"base.png", "base.json"})


def resolve_font(
    configured: Path | None,
    *,
    runner: Runner = subprocess.run,
) -> Path:
    if configured:
        if configured.is_file():
            return configured
        raise CountdownError(f"configured font does not exist: {configured}")
    try:
        result = runner(
            FONT_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CountdownError(f"font discovery failed: {error}") from error
    path = Path(result.stdout.strip())
    if result.returncode != 0 or not path.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or "no font returned"
        raise CountdownError(f"font discovery failed: {detail}")
    return path


def _fit_photo(
    path: Path,
    size: tuple[int, int],
    *,
    fit: str,
) -> Image.Image:
    width, height = size
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert("RGBA")
        if fit == "contain":
            fitted = ImageOps.contain(
                rgba,
                size,
                method=Image.Resampling.LANCZOS,
            )
        elif fit == "cover":
            fitted = ImageOps.fit(
                rgba,
                size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
        else:
            raise CountdownError(f"unsupported photo fit: {fit}")
        photo = Image.new("RGBA", fitted.size, (20, 20, 20, 255))
        photo.alpha_composite(fitted)
        background = Image.new("RGB", size, (0, 0, 0))
        background.paste(
            photo.convert("RGB"),
            (
                (width - fitted.width) // 2,
                (height - fitted.height) // 2,
            ),
        )
        return background


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if draw.textlength(word, font=font) <= max_width:
            current = word
            continue
        chunk = ""
        for character in word:
            candidate = chunk + character
            if chunk and draw.textlength(candidate, font=font) > max_width:
                lines.append(chunk)
                chunk = character
            else:
                chunk = candidate
        current = chunk
    if current:
        lines.append(current)
    return "\n".join(lines)


def _text_metrics(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    spacing: int,
    stroke_width: int,
) -> tuple[int, int, int, int]:
    return draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing,
        align="center",
        stroke_width=stroke_width,
    )


def _draw_overlay(
    canvas: Image.Image,
    region: CanvasRegion,
    state: CountdownState,
    label: str,
    font_path: Path,
    *,
    font_ratio: float,
    margin_ratio: float,
    position: str,
) -> None:
    short_edge = min(region.width, region.height)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(short_edge * margin_ratio)
    available_width = region.width - 2 * margin
    available_height = region.height - 2 * margin
    fitted: tuple[
        ImageFont.FreeTypeFont,
        ImageFont.FreeTypeFont,
        str,
        str,
        tuple[int, int, int, int],
        tuple[int, int, int, int],
        int,
        int,
        int,
        int,
        int,
    ] | None = None
    initial_size = min(512, max(24, round(short_edge * font_ratio)))
    for main_size in range(initial_size, 9, -2):
        label_size = max(10, round(main_size * 0.42))
        main_font = ImageFont.truetype(str(font_path), main_size)
        label_font = ImageFont.truetype(str(font_path), label_size)
        gap = max(6, round(main_size * 0.22))
        padding_x = max(10, round(main_size * 0.42))
        padding_y = max(8, round(main_size * 0.32))
        content_width = available_width - 2 * padding_x
        if content_width <= 0:
            continue
        shadow = max(1, round(main_size * 0.025))
        main_spacing = max(2, round(main_size * 0.16))
        label_spacing = max(2, round(label_size * 0.16))
        main_text = _wrap_text(draw, state.text, main_font, content_width)
        label_text = _wrap_text(draw, label, label_font, content_width)
        main_bounds = _text_metrics(
            draw,
            main_text,
            main_font,
            spacing=main_spacing,
            stroke_width=shadow,
        )
        label_bounds = _text_metrics(
            draw,
            label_text,
            label_font,
            spacing=label_spacing,
            stroke_width=shadow,
        )
        main_width = main_bounds[2] - main_bounds[0]
        main_height = main_bounds[3] - main_bounds[1]
        label_width = label_bounds[2] - label_bounds[0]
        label_height = label_bounds[3] - label_bounds[1]
        box_width = max(main_width, label_width) + 2 * padding_x
        box_height = main_height + label_height + gap + 2 * padding_y
        if box_width <= available_width and box_height <= available_height:
            fitted = (
                main_font,
                label_font,
                main_text,
                label_text,
                main_bounds,
                label_bounds,
                main_spacing,
                label_spacing,
                shadow,
                box_width,
                box_height,
            )
            break
    if fitted is None:
        raise CountdownError(f"overlay does not fit display region {region.connectors}")
    (
        main_font,
        label_font,
        main_text,
        label_text,
        main_bounds,
        label_bounds,
        main_spacing,
        label_spacing,
        shadow,
        box_width,
        box_height,
    ) = fitted
    main_width = main_bounds[2] - main_bounds[0]
    main_height = main_bounds[3] - main_bounds[1]
    label_width = label_bounds[2] - label_bounds[0]
    label_height = label_bounds[3] - label_bounds[1]
    padding_y = max(8, round(main_font.size * 0.32))
    gap = max(6, round(main_font.size * 0.22))
    left = region.x + (region.width - box_width) // 2
    if position == "bottom":
        top = region.y + region.height - margin - box_height
    elif position == "center":
        top = region.y + (region.height - box_height) // 2
    else:
        raise CountdownError(f"unsupported overlay position: {position}")
    right = left + box_width
    bottom = top + box_height
    radius = max(8, round(main_font.size * 0.3))
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=radius,
        fill=(0, 0, 0, 150),
        outline=(255, 255, 255, 80),
        width=shadow,
    )
    label_x = left + (box_width - label_width) // 2 - label_bounds[0]
    label_y = top + padding_y - label_bounds[1]
    main_x = left + (box_width - main_width) // 2 - main_bounds[0]
    main_y = top + padding_y + label_height + gap - main_bounds[1]
    draw.multiline_text(
        (label_x, label_y),
        label_text,
        font=label_font,
        fill=(255, 255, 255, 235),
        spacing=label_spacing,
        align="center",
        stroke_width=shadow,
        stroke_fill=(0, 0, 0, 210),
    )
    draw.multiline_text(
        (main_x, main_y),
        main_text,
        font=main_font,
        fill=(255, 255, 255, 255),
        spacing=main_spacing,
        align="center",
        stroke_width=shadow,
        stroke_fill=(0, 0, 0, 230),
    )


def _atomic_save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".png",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        # Low lossless compression keeps minute-level 4K refreshes inexpensive.
        image.save(temporary, format="PNG", compress_level=1)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _base_key(
    canvas: CanvasLayout,
    pool: PhotoPool,
    selected: Path,
    photo_fit: str,
) -> dict[str, Any]:
    return {
        "version": 5,
        "display_signature": canvas.display_signature,
        "pool_signature": pool.signature,
        "selected": selected.relative_to(pool.root).as_posix(),
        "canvas": [canvas.width, canvas.height],
        "photo_fit": photo_fit,
    }


def _load_or_build_base(
    config: AppConfig,
    canvas: CanvasLayout,
    pool: PhotoPool,
    selected: Path,
) -> Image.Image:
    base_path = config.wallpaper.cache_directory / "base.png"
    metadata_path = config.wallpaper.cache_directory / "base.json"
    key = _base_key(
        canvas,
        pool,
        selected,
        config.style.photo_fit,
    )
    if read_json(metadata_path) == key and base_path.is_file():
        try:
            with Image.open(base_path) as cached:
                cached.load()
                if cached.size == (canvas.width, canvas.height):
                    return cached.convert("RGB")
        except OSError:
            pass

    base = Image.new("RGB", (canvas.width, canvas.height), (12, 12, 12))
    for region in canvas.regions:
        fitted = _fit_photo(
            selected,
            (region.width, region.height),
            fit=config.style.photo_fit,
        )
        base.paste(fitted, (region.x, region.y))
    _atomic_save(base, base_path)
    atomic_write_json(metadata_path, key)
    return base


def _next_output(
    directory: Path,
    render_key: dict[str, Any],
) -> Path:
    identity = sha256(
        json.dumps(
            render_key,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:24]
    # An immutable content identity gives every changed render a new URI while
    # a true no-op reuses the existing file without touching GNOME.
    return directory / f"wallpaper-{identity}.png"


def prune_generated_outputs(
    directory: Path,
    *,
    keep: tuple[Path, ...],
    retain: int = 2,
) -> None:
    if retain < 1:
        raise ValueError("retain must be at least 1")
    protected = {path.resolve() for path in keep}
    candidates = sorted(
        (
            path
            for path in directory.iterdir()
            if (
                GENERATED_WALLPAPER_NAME.fullmatch(path.name)
                or GENERATED_CALIBRATION_NAME.fullmatch(path.name)
            )
            and path.is_file()
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    retained = 0
    for path in candidates:
        if path.resolve() in protected or retained < retain:
            retained += 1
            continue
        path.unlink(missing_ok=True)


def _render_key(
    config: AppConfig,
    canvas: CanvasLayout,
    pool: PhotoPool,
    selected: Path,
    countdown: CountdownState,
) -> dict[str, Any]:
    return {
        "version": 1,
        "countdown_text": countdown.text,
        "arrived": countdown.arrived,
        "pool_signature": pool.signature,
        "selected": selected.relative_to(pool.root).as_posix(),
        "display_signature": canvas.display_signature,
        "canvas": [canvas.width, canvas.height],
        "event": {
            "label": config.event.label,
            "target": config.event.target.isoformat(),
            "timezone": config.event.timezone.key,
            "after_arrival_message": config.event.after_arrival_message,
        },
        "style": {
            "font": str(config.style.font or ""),
            "overlay_position": config.style.overlay_position,
            "margin_ratio": config.style.margin_ratio,
            "font_ratio": config.style.font_ratio,
            "photo_fit": config.style.photo_fit,
        },
    }


def _reusable_output(
    directory: Path,
    state: dict[str, Any],
    key: dict[str, Any],
) -> Path | None:
    if state.get("render_key") != key:
        return None
    name = state.get("output")
    if not isinstance(name, str) or Path(name).name != name:
        return None
    output = directory / name
    return output if output.is_file() else None


def render_wallpaper(
    config: AppConfig,
    layout: DisplayLayout,
    *,
    now: datetime | None = None,
    runner: Runner = subprocess.run,
    acquire_lock: bool = True,
) -> Path:
    current = now or datetime.now().astimezone()
    pool = scan_photo_pool(config.wallpaper.source_directory)
    photo_bucket_value = photo_bucket(
        current,
        config.wallpaper.photo_rotation_seconds,
    )
    text_bucket = int(current.timestamp()) // (
        config.wallpaper.countdown_refresh_seconds
    )
    selected = select_photo(
        pool,
        photo_bucket_value,
        config.wallpaper.selection_seed,
    )
    canvas = build_canvas_layout(
        layout,
        max_pixels=config.wallpaper.max_canvas_pixels,
    )
    output_directory = config.wallpaper.output_directory
    current_countdown = calculate_countdown(
        current,
        config.event.target,
        config.event.after_arrival_message,
    )
    if current_countdown.arrived:
        countdown = current_countdown
    else:
        countdown = calculate_countdown(
            datetime.fromtimestamp(
                text_bucket * config.wallpaper.countdown_refresh_seconds,
                tz=UTC,
            ),
            config.event.target,
            config.event.after_arrival_message,
        )
    render_key = _render_key(
        config,
        canvas,
        pool,
        selected,
        countdown,
    )
    ensure_owned_directory(
        output_directory,
        kind="output",
        ownership_id=config.wallpaper.selection_seed,
        reserved_names=_OUTPUT_RESERVED,
        reserved_patterns=(GENERATED_WALLPAPER_NAME, GENERATED_CALIBRATION_NAME),
    )
    ensure_owned_directory(
        config.wallpaper.cache_directory,
        kind="cache",
        ownership_id=config.wallpaper.selection_seed,
        reserved_names=_CACHE_RESERVED,
    )

    lock = operation_lock(output_directory) if acquire_lock else nullcontext()
    with lock:
        state_path = output_directory / "render-state.json"
        prior_state = read_json(state_path)
        reusable = _reusable_output(output_directory, prior_state, render_key)
        if reusable is not None:
            return reusable
        font = resolve_font(config.style.font, runner=runner)
        base = _load_or_build_base(
            config,
            canvas,
            pool,
            selected,
        )
        final = base.copy()
        for region in canvas.regions:
            _draw_overlay(
                final,
                region,
                countdown,
                config.event.label,
                font,
                font_ratio=config.style.font_ratio,
                margin_ratio=config.style.margin_ratio,
                position=config.style.overlay_position,
            )
        output = _next_output(output_directory, render_key)
        _atomic_save(final, output)
        atomic_write_json(
            state_path,
            {
                "output": output.name,
                "bucket": photo_bucket_value,
                "text_bucket": text_bucket,
                "photo": selected.relative_to(pool.root).as_posix(),
                "layout_source": layout.source,
                "rendered_at": current.isoformat(),
                "render_key": render_key,
            },
        )
        return output


def render_calibration(
    config: AppConfig,
    layout: DisplayLayout,
    *,
    acquire_lock: bool = True,
) -> Path:
    canvas = build_canvas_layout(
        layout,
        max_pixels=config.wallpaper.max_canvas_pixels,
    )
    colors = (
        (171, 50, 50),
        (50, 110, 171),
        (62, 145, 86),
        (142, 78, 161),
    )
    calibration_key = {
        "version": 1,
        "display_signature": canvas.display_signature,
        "canvas": [canvas.width, canvas.height],
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
    identity = sha256(
        json.dumps(calibration_key, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    output = config.wallpaper.output_directory / f"calibration-{identity}.png"
    ensure_owned_directory(
        config.wallpaper.output_directory,
        kind="output",
        ownership_id=config.wallpaper.selection_seed,
        reserved_names=_OUTPUT_RESERVED,
        reserved_patterns=(GENERATED_WALLPAPER_NAME, GENERATED_CALIBRATION_NAME),
    )
    lock = (
        operation_lock(config.wallpaper.output_directory)
        if acquire_lock
        else nullcontext()
    )
    with lock:
        if output.is_file():
            return output
        image = Image.new("RGB", (canvas.width, canvas.height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for index, region in enumerate(canvas.regions, start=1):
            color = colors[(index - 1) % len(colors)]
            bounds = (
                region.x,
                region.y,
                region.x + region.width - 1,
                region.y + region.height - 1,
            )
            draw.rectangle(bounds, fill=color, outline=(255, 255, 255), width=8)
            text = f"{index}: {', '.join(region.connectors)}"
            draw.text((region.x + 32, region.y + 32), text, fill=(255, 255, 255))
            draw.line(
                (
                    region.x,
                    region.y,
                    region.x + region.width,
                    region.y + region.height,
                ),
                fill=(255, 255, 255),
                width=6,
            )
            draw.line(
                (
                    region.x + region.width,
                    region.y,
                    region.x,
                    region.y + region.height,
                ),
                fill=(255, 255, 255),
                width=6,
            )
        _atomic_save(image, output)
    return output


def render_metadata(config: AppConfig) -> dict[str, Any]:
    path = config.wallpaper.output_directory / "render-state.json"
    return json.loads(path.read_text(encoding="utf-8"))
