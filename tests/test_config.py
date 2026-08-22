import tomllib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import write_config

from countscape.config import (
    default_cache_directory,
    default_config_path,
    default_output_directory,
    default_photo_directory,
    default_state_directory,
    load_config,
    parse_event,
    validate_schedule_interval,
    validate_storage_paths,
    xdg_state_home,
)
from countscape.errors import ConfigError, DisplayError


def test_checked_in_example_uses_public_unconfirmed_schema() -> None:
    with Path("config/countscape.example.toml").open("rb") as handle:
        data = tomllib.load(handle)

    assert "paths" not in data
    assert data["schema_version"] == 1
    assert set(data["runtime"]) == {"state_directory"}
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
    assert default_state_directory() == state_home / "countscape"
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
    assert default_state_directory() == home / ".local" / "state" / "countscape"
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
        state="../runtime-state",
    )
    elsewhere = tmp_path / "unrelated-working-directory"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    config = load_config(path)

    assert config.wallpaper.source_directory == (tmp_path / "photos").resolve()
    assert config.wallpaper.output_directory == (tmp_path / "generated").resolve()
    assert config.wallpaper.cache_directory == (tmp_path / "render-cache").resolve()
    assert config.runtime.state_directory == (tmp_path / "runtime-state").resolve()
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


def test_config_read_oserror_is_wrapped_for_cli_privacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_config(tmp_path)
    resolved = path.resolve()
    original_open = Path.open

    def denied_open(candidate: Path, *args: object, **kwargs: object):
        if candidate == resolved:
            raise PermissionError(f"permission denied for {resolved}")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)

    with pytest.raises(ConfigError) as raised:
        load_config(path)

    assert "could not read configuration file" in str(raised.value)
    assert str(resolved) in str(raised.value)


@pytest.mark.parametrize("version", (None, 0, 2, True))
def test_config_requires_final_schema_version(
    tmp_path: Path,
    version: int | bool | None,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    replacement = (
        "" if version is None else f"schema_version = {str(version).lower()}\n"
    )
    path.write_text(
        contents.replace("schema_version = 1\n", replacement),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="init --force"):
        load_config(path)


@pytest.mark.parametrize(
    ("anchor", "addition", "context"),
    (
        ("schema_version = 1\n", "preview_option = true\n", "root"),
        ("[runtime]\n", "preview_option = true\n", "runtime"),
        ("[event]\n", "preview_option = true\n", "event"),
        ("[display]\n", "preview_option = true\n", "display"),
        ("[wallpaper]\n", "preview_option = true\n", "wallpaper"),
        ("[schedule]\n", "preview_option = true\n", "schedule"),
        ("[selection]\n", "preview_option = true\n", "selection"),
        ("[style]\n", "preview_option = true\n", "style"),
        (
            "[[display.profiles.fixture.monitors]]\n",
            "preview_option = true\n",
            "monitor",
        ),
    ),
)
def test_config_rejects_unknown_schema_keys(
    tmp_path: Path,
    anchor: str,
    addition: str,
    context: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace(anchor, f"{anchor}{addition}", 1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=f"{context}.*unknown"):
        load_config(path)


def test_config_rejects_unknown_display_profile_keys(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    monitor = "[[display.profiles.fixture.monitors]]\n"
    path.write_text(
        contents.replace(
            monitor,
            "[display.profiles.fixture]\npreview_option = true\n\n" + monitor,
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="profile fixture.*unknown"):
        load_config(path)


def test_display_profile_coordinates_are_required(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace("x = 0\n", "", 1), encoding="utf-8")

    with pytest.raises(ConfigError, match="x must be a number"):
        load_config(path)


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


@pytest.mark.parametrize("managed", ("output", "cache", "state"))
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


@pytest.mark.parametrize("managed", ("photo", "output", "cache", "state"))
def test_configuration_must_not_live_inside_a_managed_directory(
    tmp_path: Path,
    managed: str,
) -> None:
    field = "source" if managed == "photo" else managed
    path = write_config(tmp_path, **{field: tmp_path / "config"})

    with pytest.raises(
        ConfigError,
        match="configuration and .* directories must not overlap",
    ):
        load_config(path)


def test_configuration_rejects_symlink_alias_inside_photo_directory(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "photos-alias"
    alias.symlink_to(tmp_path / "config", target_is_directory=True)
    path = write_config(tmp_path, source=alias)

    with pytest.raises(ConfigError, match="configuration and photo directories"):
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


def test_photo_fit_is_required_and_validated(tmp_path: Path) -> None:
    invalid = write_config(tmp_path / "invalid", photo_fit="stretch")
    with pytest.raises(ConfigError, match="photo_fit"):
        load_config(invalid)

    defaulted = write_config(tmp_path / "defaulted")
    contents = defaulted.read_text(encoding="utf-8")
    defaulted.write_text(
        contents.replace('photo_fit = "contain"\n', ""),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="photo_fit"):
        load_config(defaulted)


def _replace_fixture_monitor_section(path: Path, replacement: str) -> None:
    contents = path.read_text(encoding="utf-8")
    start = contents.index("[[display.profiles.fixture.monitors]]")
    end = contents.index("\n[wallpaper]", start)
    path.write_text(
        contents[:start] + replacement.rstrip() + "\n" + contents[end:],
        encoding="utf-8",
    )


def test_config_rejects_missing_required_table(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents[: contents.index("\n[style]")], encoding="utf-8")

    with pytest.raises(ConfigError, match=r"missing \[style\] table"):
        load_config(path)


@pytest.mark.parametrize("value", (0, True, "60"))
def test_schedule_validator_rejects_non_positive_and_non_integer_values(
    value: object,
) -> None:
    with pytest.raises(ConfigError, match="integer of at least 1"):
        validate_schedule_interval(value, "synthetic interval")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "message"),
    (("true", "must be a number"), ("0", "greater than 0"), ("nan", "greater than 0")),
)
def test_style_ratios_reject_non_numeric_non_positive_and_non_finite_values(
    tmp_path: Path,
    value: str,
    message: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace("margin_ratio = 0.05", f"margin_ratio = {value}"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_profile_primary_requires_a_boolean(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace("primary = true", 'primary = "yes"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="primary must be a boolean"):
        load_config(path)


@pytest.mark.parametrize("label", ("", object()))
def test_parse_event_rejects_empty_or_non_string_display_text(label: object) -> None:
    with pytest.raises(ConfigError, match="event.label must be a non-empty string"):
        parse_event(
            label=label,  # type: ignore[arg-type]
            target="2030-01-01T12:00:00+00:00",
            timezone="Etc/UTC",
            after_arrival_message="Arrived",
        )


def test_managed_storage_rejects_filesystem_root(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="output directory must be a dedicated"):
        validate_storage_paths(
            tmp_path / "photos",
            Path("/"),
            tmp_path / "cache",
            tmp_path / "state",
        )


def test_parse_event_accepts_aware_datetime_and_zoneinfo_objects() -> None:
    target = datetime(2030, 1, 1, 12, tzinfo=UTC)

    event = parse_event(
        label="Synthetic milestone",
        target=target,
        timezone=ZoneInfo("Etc/UTC"),
        after_arrival_message="Arrived",
    )

    assert event.target == target
    assert event.timezone.key == "Etc/UTC"


@pytest.mark.parametrize(
    ("target", "message"),
    (("not-a-datetime", "invalid event.target"), (object(), "must be an ISO 8601")),
)
def test_parse_event_rejects_invalid_target_types_and_values(
    target: object,
    message: str,
) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_event(
            label="Synthetic milestone",
            target=target,  # type: ignore[arg-type]
            timezone="Etc/UTC",
            after_arrival_message="Arrived",
        )


@pytest.mark.parametrize("timezone", ("", object()))
def test_parse_event_rejects_empty_or_non_string_timezone(timezone: object) -> None:
    with pytest.raises(ConfigError, match="non-empty IANA zone"):
        parse_event(
            label="Synthetic milestone",
            target="2030-01-01T12:00:00+00:00",
            timezone=timezone,  # type: ignore[arg-type]
            after_arrival_message="Arrived",
        )


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ("[display.profiles.fixture]\nmonitors = []", "non-empty list"),
        ("[display.profiles.fixture]\nmonitors = [1]", "monitor 0 must be a table"),
    ),
)
def test_profile_monitors_require_nonempty_tables(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    path = write_config(tmp_path)
    _replace_fixture_monitor_section(path, replacement)

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_profile_transform_is_bounded(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace("transform = 0", "transform = 8"), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="transform must be between 0 and 7"):
        load_config(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ('mode = "profile"', 'mode = "automatic"', "display.mode"),
        (
            'fallback_profile = "fixture"',
            'fallback_profile = ""',
            "fallback_profile must be a non-empty string",
        ),
    ),
)
def test_display_mode_and_fallback_are_strict(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace(old, new), encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(path)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ("profiles = []", "display.profiles must be a table"),
        ("profiles = { fixture = 1 }", "display profile fixture must be a table"),
    ),
)
def test_display_profiles_require_a_table_of_profile_tables(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    path = write_config(tmp_path)
    _replace_fixture_monitor_section(path, replacement)

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_profile_mode_requires_a_named_existing_fallback(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(
        contents.replace('fallback_profile = "fixture"\n', ""),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="requires a valid fallback_profile"):
        load_config(path)


def test_auto_mode_rejects_unknown_optional_fallback(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    contents = contents.replace('mode = "profile"', 'mode = "auto"')
    contents = contents.replace(
        'fallback_profile = "fixture"', 'fallback_profile = "missing"'
    )
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown display fallback profile"):
        load_config(path)


def test_invalid_toml_is_reported_as_configuration_error(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    path.write_text("schema_version = [", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_configuration_path_resolution_failure_is_translated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = tmp_path / "unresolvable.toml"
    original_resolve = Path.resolve

    def fail_requested_path(path: Path, *args: object, **kwargs: object) -> Path:
        if path == requested:
            raise OSError("synthetic resolution failure")
        return original_resolve(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fail_requested_path)

    with pytest.raises(ConfigError, match="could not resolve configuration file"):
        load_config(requested)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            'overlay_position = "center"',
            'overlay_position = "left"',
            "overlay_position",
        ),
        ('font = ""', "font = 42", "style.font must be a string"),
    ),
)
def test_style_enum_and_font_type_are_strict(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = write_config(tmp_path)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace(old, new), encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(path)
