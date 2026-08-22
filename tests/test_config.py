import tomllib
from pathlib import Path

import pytest
from conftest import write_config

from countscape.config import (
    default_cache_directory,
    default_config_path,
    default_output_directory,
    default_photo_directory,
    load_config,
    parse_event,
    xdg_state_home,
)
from countscape.errors import ConfigError, DisplayError


def test_checked_in_example_uses_public_unconfirmed_schema() -> None:
    with Path("config/countscape.example.toml").open("rb") as handle:
        data = tomllib.load(handle)

    assert "paths" not in data
    assert set(data["event"]) == {
        "label",
        "target",
        "timezone",
        "confirmed",
        "after_arrival_message",
    }
    assert data["event"]["confirmed"] is False
    assert set(data["wallpaper"]) == {
        "source_directory",
        "output_directory",
        "cache_directory",
        "max_canvas_pixels",
    }
    assert data["schedule"] == {
        "countdown_refresh_seconds": 60,
        "photo_rotation_seconds": 600,
    }


def test_xdg_defaults_are_independent_of_a_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_home = tmp_path / "configuration"
    data_home = tmp_path / "data"
    cache_home = tmp_path / "cache"
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    assert default_config_path() == config_home / "countscape" / "config.toml"
    assert default_photo_directory() == data_home / "countscape" / "backgrounds"
    assert default_output_directory() == data_home / "countscape" / "generated"
    assert default_cache_directory() == cache_home / "countscape"
    assert xdg_state_home() == state_home


@pytest.mark.parametrize("xdg_value", ("", "relative/xdg-root"))
def test_empty_or_relative_xdg_values_use_home_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    xdg_value: str,
) -> None:
    home = tmp_path / "fixture-home"
    monkeypatch.setenv("HOME", str(home))
    for variable in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    ):
        monkeypatch.setenv(variable, xdg_value)

    assert default_config_path() == home / ".config" / "countscape" / "config.toml"
    assert default_photo_directory() == (
        home / ".local" / "share" / "countscape" / "backgrounds"
    )
    assert default_output_directory() == (
        home / ".local" / "share" / "countscape" / "generated"
    )
    assert default_cache_directory() == home / ".cache" / "countscape"
    assert xdg_state_home() == home / ".local" / "state"


def test_relative_paths_resolve_from_config_not_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_config(
        tmp_path,
        source="../photos",
        output="../generated",
        cache="../render-cache",
    )
    elsewhere = tmp_path / "unrelated-working-directory"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    config = load_config(path)

    assert config.wallpaper.source_directory == (tmp_path / "photos").resolve()
    assert config.wallpaper.output_directory == (tmp_path / "generated").resolve()
    assert config.wallpaper.cache_directory == (tmp_path / "render-cache").resolve()
    assert not hasattr(config, "repository_root")


def test_configurable_event_and_independent_intervals(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        label="Until the neighborhood picnic",
        target="2030-07-04T15:30:00-04:00",
        after_arrival_message="Picnic time!",
        countdown_refresh_seconds=300,
        photo_rotation_seconds=900,
    )

    config = load_config(path)

    assert config.event.label == "Until the neighborhood picnic"
    assert config.event.target.isoformat() == "2030-07-04T15:30:00-04:00"
    assert config.event.after_arrival_message == "Picnic time!"
    assert config.wallpaper.countdown_refresh_seconds == 300
    assert config.wallpaper.photo_rotation_seconds == 900


def test_missing_config_points_to_init(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="run countscape init"):
        load_config(tmp_path / "missing.toml")


def test_target_requires_explicit_offset(tmp_path: Path) -> None:
    path = write_config(tmp_path, target="2027-06-01T12:00:00")
    with pytest.raises(ConfigError, match="explicit UTC offset"):
        load_config(path)


def test_target_offset_must_match_zone(tmp_path: Path) -> None:
    path = write_config(tmp_path, target="2027-06-01T12:00:00-05:00")
    with pytest.raises(ConfigError, match="wall time does not agree|offset"):
        load_config(path)


def test_bad_timezone_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, timezone="Mars/Olympus")
    with pytest.raises(ConfigError, match="unknown event.timezone"):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("label", "Until the\nfestival", "control characters"),
        ("after_arrival_message", "Ready\x00now", "control characters"),
        ("label", "界" * 161, "at most 160"),
        ("after_arrival_message", "✨" * 161, "at most 160"),
    ],
)
def test_event_display_text_rejects_controls_and_overlong_values(
    field: str,
    value: str,
    message: str,
) -> None:
    arguments = {
        "label": "Until the makers fair",
        "target": "2030-01-01T12:00:00+00:00",
        "timezone": "Etc/UTC",
        "after_arrival_message": "The fair begins!",
        field: value,
    }

    with pytest.raises(ConfigError, match=message):
        parse_event(**arguments)  # type: ignore[arg-type]


def test_target_must_be_confirmed(tmp_path: Path) -> None:
    path = write_config(tmp_path, confirmed=False)
    with pytest.raises(ConfigError, match="confirmed"):
        load_config(path)


def test_seed_is_validated(tmp_path: Path) -> None:
    path = write_config(tmp_path, seed="")
    with pytest.raises(ConfigError, match="seed"):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("countdown_refresh_seconds", {"countdown_refresh_seconds": 0}),
        ("photo_rotation_seconds", {"photo_rotation_seconds": 0}),
    ],
)
def test_schedule_intervals_must_be_positive(
    tmp_path: Path,
    field: str,
    kwargs: dict[str, int],
) -> None:
    path = write_config(tmp_path, **kwargs)
    with pytest.raises(ConfigError, match=field):
        load_config(path)


@pytest.mark.parametrize("interval", (7, 90))
@pytest.mark.parametrize(
    "field",
    ("countdown_refresh_seconds", "photo_rotation_seconds"),
)
def test_schedule_intervals_must_align_to_the_wall_clock(
    tmp_path: Path,
    field: str,
    interval: int,
) -> None:
    path = write_config(tmp_path, **{field: interval})
    with pytest.raises(ConfigError, match="evenly divide|whole number of minutes"):
        load_config(path)


@pytest.mark.parametrize("managed", ("output", "cache"))
def test_managed_directories_must_not_be_inside_photo_bank(
    tmp_path: Path,
    managed: str,
) -> None:
    photos = tmp_path / "photos"
    kwargs = {
        "source": photos,
        managed: photos / "managed",
    }
    path = write_config(tmp_path, **kwargs)
    with pytest.raises(ConfigError, match="photo bank|directories must not overlap"):
        load_config(path)


def test_output_and_cache_must_be_different(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    path = write_config(tmp_path, output=shared, cache=shared)
    with pytest.raises(ConfigError, match="must be different|must not overlap"):
        load_config(path)


@pytest.mark.parametrize("managed", ("photo", "output", "cache"))
def test_configuration_must_not_live_inside_a_managed_directory(
    tmp_path: Path,
    managed: str,
) -> None:
    field = "source" if managed == "photo" else managed
    path = write_config(tmp_path, **{field: tmp_path / "config"})

    with pytest.raises(ConfigError, match=f"inside the {managed} directory"):
        load_config(path)


def test_configuration_rejects_symlink_alias_inside_photo_directory(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "photos-alias"
    alias.symlink_to(tmp_path / "config", target_is_directory=True)
    path = write_config(tmp_path, source=alias)

    with pytest.raises(ConfigError, match="inside the photo directory"):
        load_config(path)


@pytest.mark.parametrize(
    "relationship",
    (
        "photo-inside-output",
        "photo-inside-cache",
        "output-inside-cache",
        "cache-inside-output",
    ),
)
def test_storage_paths_reject_reverse_and_managed_nesting(
    tmp_path: Path,
    relationship: str,
) -> None:
    source = tmp_path / "photos"
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    if relationship == "photo-inside-output":
        source = output / "photos"
    elif relationship == "photo-inside-cache":
        source = cache / "photos"
    elif relationship == "output-inside-cache":
        output = cache / "generated"
    else:
        cache = output / "cache"

    path = write_config(tmp_path, source=source, output=output, cache=cache)
    with pytest.raises(ConfigError, match="directories must not overlap"):
        load_config(path)


@pytest.mark.parametrize(
    ("coordinate", "value"),
    (("x", "nan"), ("x", "-inf"), ("y", "inf")),
)
def test_display_profile_coordinates_must_be_finite(
    tmp_path: Path,
    coordinate: str,
    value: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace(f"{coordinate} = 0\n", f"{coordinate} = {value}\n"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=f"{coordinate} must be finite"):
        load_config(path)


@pytest.mark.parametrize("max_pixels", (0, 100_000_001))
def test_max_canvas_pixels_is_bounded(tmp_path: Path, max_pixels: int) -> None:
    path = write_config(tmp_path, max_pixels=max_pixels)

    with pytest.raises(ConfigError, match="max_canvas_pixels"):
        load_config(path)


@pytest.mark.parametrize(
    ("old", "new", "error", "message"),
    (
        ("x = 0\n", "x = 1000001\n", DisplayError, "reasonable"),
        ("scale = 1.0\n", "scale = 16.1\n", ConfigError, "greater than 16"),
        (
            "physical_width = 800\n",
            "physical_width = 100001\n",
            ConfigError,
            "greater than 100000",
        ),
    ),
)
def test_extreme_display_profile_values_are_rejected(
    tmp_path: Path,
    old: str,
    new: str,
    error: type[Exception],
    message: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace(old, new), encoding="utf-8")

    with pytest.raises(error, match=message):
        load_config(path)


def test_photo_fit_is_validated_and_defaults_to_contain(tmp_path: Path) -> None:
    invalid = write_config(tmp_path / "invalid", photo_fit="stretch")
    with pytest.raises(ConfigError, match="photo_fit"):
        load_config(invalid)

    defaulted = write_config(tmp_path / "defaulted")
    contents = defaulted.read_text(encoding="utf-8")
    defaulted.write_text(
        contents.replace('photo_fit = "contain"\n', ""),
        encoding="utf-8",
    )
    assert load_config(defaulted).style.photo_fit == "contain"
