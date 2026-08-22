from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from countscape.config import AppConfig, load_config


def make_image(
    path: Path,
    size: tuple[int, int] = (800, 600),
    color: tuple[int, int, int] = (40, 100, 180),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def write_config(
    root: Path,
    *,
    seed: str = "fixture-machine",
    mode: str = "profile",
    output: str | Path | None = None,
    cache: str | Path | None = None,
    state: str | Path | None = None,
    source: str | Path | None = None,
    label: str = "Until the lantern festival",
    target: str = "2027-06-01T12:00:00-04:00",
    timezone: str = "America/New_York",
    after_arrival_message: str = "The celebration begins!",
    confirmed: bool = True,
    max_pixels: int = 100_000_000,
    overlay_position: str = "center",
    photo_fit: str = "contain",
    countdown_refresh_seconds: int = 60,
    photo_rotation_seconds: int = 600,
) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.toml"
    source_path = source if source is not None else root / "photos"
    output_path = output if output is not None else root / "data" / "generated"
    cache_path = cache if cache is not None else root / "cache"
    state_path = state if state is not None else root / "state"
    path.write_text(
        f"""
schema_version = 1

[runtime]
state_directory = {json.dumps(str(state_path))}

[event]
label = {json.dumps(label)}
target = {json.dumps(target)}
timezone = {json.dumps(timezone)}
confirmed = {str(confirmed).lower()}
after_arrival_message = {json.dumps(after_arrival_message)}

[display]
mode = {json.dumps(mode)}
fallback_profile = "fixture"

[[display.profiles.fixture.monitors]]
connector = "fixture-panel"
x = 0
y = 0
scale = 1.0
transform = 0
primary = true
physical_width = 800
physical_height = 600

[wallpaper]
source_directory = {json.dumps(str(source_path))}
output_directory = {json.dumps(str(output_path))}
cache_directory = {json.dumps(str(cache_path))}
max_canvas_pixels = {max_pixels}

[schedule]
countdown_refresh_seconds = {countdown_refresh_seconds}
photo_rotation_seconds = {photo_rotation_seconds}

[selection]
seed = {json.dumps(seed)}

[style]
font = ""
overlay_position = {json.dumps(overlay_position)}
margin_ratio = 0.05
font_ratio = 0.055
photo_fit = {json.dumps(photo_fit)}
""".lstrip(),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def configured_project(tmp_path: Path) -> tuple[AppConfig, Path]:
    photo = make_image(tmp_path / "photos" / "photo.jpg")
    config = load_config(write_config(tmp_path))
    return config, photo
