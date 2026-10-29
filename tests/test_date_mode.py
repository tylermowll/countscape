from __future__ import annotations

import json
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import make_image, write_config

import countscape.cli as cli
from countscape.config import load_config
from countscape.errors import ConfigError
from countscape.install import configure_settings, dump_config, initialize_config


def _set_xdg_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for variable, directory in (
        ("XDG_CONFIG_HOME", "xdg-config"),
        ("XDG_DATA_HOME", "xdg-data"),
        ("XDG_CACHE_HOME", "xdg-cache"),
        ("XDG_STATE_HOME", "xdg-state"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / directory))


def _overlay_config(
    tmp_path: Path,
    overlay: dict[str, object],
    *,
    keep_event: bool = False,
    confirmed: bool = True,
) -> Path:
    path = write_config(tmp_path, confirmed=confirmed)
    text = path.read_text(encoding="utf-8")
    if not keep_event:
        start = text.index("[event]\n")
        stop = text.index("[display]\n", start)
        text = text[:start] + text[stop:]
    text += "\n[overlay]\n" + "\n".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in overlay.items()
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _date_config(tmp_path: Path, *, keep_event: bool = False) -> Path:
    return _overlay_config(
        tmp_path,
        {
            "mode": "date",
            "message": "A good day",
            "timezone": "America/Los_Angeles",
        },
        keep_event=keep_event,
    )


def test_legacy_configuration_still_selects_countdown(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))

    assert config.overlay.mode == "countdown"
    assert config.event is not None
    assert config.event.target.utcoffset() is not None


def test_date_only_configuration_round_trips_without_an_event(tmp_path: Path) -> None:
    path = _date_config(tmp_path)
    config = load_config(path)

    assert config.event is None
    assert config.overlay.mode == "date"
    assert config.overlay.message == "A good day"
    assert config.overlay.timezone == ZoneInfo("America/Los_Angeles")

    serialized = dump_config(config)
    assert "event" not in tomllib.loads(serialized)
    path.write_text(serialized, encoding="utf-8")
    assert load_config(path) == config


@pytest.mark.parametrize("mode", ["", "clock", True])
def test_overlay_rejects_unsupported_modes(tmp_path: Path, mode: object) -> None:
    path = _overlay_config(
        tmp_path,
        {"mode": mode, "message": "A good day", "timezone": "Etc/UTC"},
    )

    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("message", ["", "  ", "x" * 161, "line\nbreak", "bad\0"])
def test_date_message_uses_display_text_validation(
    tmp_path: Path, message: str
) -> None:
    path = _overlay_config(
        tmp_path,
        {"mode": "date", "message": message, "timezone": "Etc/UTC"},
    )

    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("timezone", ["", "Nowhere/Invalid", 123])
def test_date_requires_a_valid_iana_zone(tmp_path: Path, timezone: object) -> None:
    path = _overlay_config(
        tmp_path,
        {"mode": "date", "message": "A good day", "timezone": timezone},
    )

    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("missing", ["message", "timezone"])
def test_date_only_config_requires_message_and_zone(
    tmp_path: Path, missing: str
) -> None:
    overlay = {"mode": "date", "message": "A good day", "timezone": "Etc/UTC"}
    del overlay[missing]

    with pytest.raises(ConfigError):
        load_config(_overlay_config(tmp_path, overlay))


def test_countdown_mode_requires_a_real_event(tmp_path: Path) -> None:
    path = _overlay_config(tmp_path, {"mode": "countdown"})

    with pytest.raises(ConfigError):
        load_config(path)


def test_date_mode_does_not_confirm_a_retained_unconfirmed_target(
    tmp_path: Path,
) -> None:
    path = _overlay_config(
        tmp_path,
        {"mode": "date", "message": "A good day", "timezone": "Etc/UTC"},
        keep_event=True,
        confirmed=False,
    )

    with pytest.raises(ConfigError, match="confirmed"):
        load_config(path)


@pytest.mark.parametrize(
    "message,expected",
    [("  A good day  ", "A good day"), ("❤️ A good day ❤️", "❤️ A good day ❤️")],
)
def test_date_initialization_needs_no_fabricated_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected: str,
) -> None:
    _set_xdg_roots(tmp_path, monkeypatch)
    path = initialize_config(
        mode="date",
        message=message,
        timezone="Etc/UTC",
        target=None,
    )
    config = load_config(path)

    assert config.event is None
    assert config.overlay.message == expected
    assert config.overlay.timezone == ZoneInfo("Etc/UTC")
    assert "event" not in tomllib.loads(path.read_text(encoding="utf-8"))


def test_date_overlay_rejects_unknown_configuration_keys(tmp_path: Path) -> None:
    path = _overlay_config(
        tmp_path,
        {
            "mode": "date",
            "message": "A good day",
            "timezone": "Etc/UTC",
            "timezne": "Etc/UTC",
        },
    )

    with pytest.raises(ConfigError, match="unknown"):
        load_config(path)


def test_countdown_initialization_does_not_invent_a_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_roots(tmp_path, monkeypatch)

    with pytest.raises(ConfigError):
        initialize_config(mode="countdown", timezone="Etc/UTC", target=None)


def test_switching_modes_preserves_event_storage_and_inactive_date_settings(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    before = load_config(path)

    configure_settings(path, mode="date", message="A good day")
    date = load_config(path)

    assert date.event == before.event
    assert date.overlay.mode == "date"
    assert date.overlay.timezone == before.event.timezone
    assert date.wallpaper == before.wallpaper
    assert date.runtime == before.runtime
    assert date.display == before.display

    configure_settings(path, photo_rotation_seconds=120)
    updated = load_config(path)
    assert updated.overlay == date.overlay
    assert updated.wallpaper.photo_rotation_seconds == 120

    configure_settings(path, mode="countdown")
    resumed = load_config(path)
    assert resumed.overlay.mode == "countdown"
    assert resumed.event == before.event
    assert resumed.wallpaper.photo_rotation_seconds == 120


def test_date_timezone_changes_preserve_the_inactive_event(tmp_path: Path) -> None:
    path = _date_config(tmp_path, keep_event=True)
    before = load_config(path)

    configure_settings(path, event_timezone="Europe/Paris")
    after = load_config(path)

    assert after.overlay.timezone == ZoneInfo("Europe/Paris")
    assert after.event == before.event


def test_date_only_switch_to_countdown_requires_a_target_and_is_atomic(
    tmp_path: Path,
) -> None:
    path = _date_config(tmp_path)
    original = path.read_bytes()

    with pytest.raises(ConfigError):
        configure_settings(path, mode="countdown")

    assert path.read_bytes() == original
    assert load_config(path).event is None

    configure_settings(
        path,
        mode="countdown",
        event_target="2030-10-01T09:00:00-04:00",
        event_timezone="America/New_York",
        event_label="Until the garden walk",
        after_arrival_message="A fine day",
    )
    config = load_config(path)
    assert config.overlay.mode == "countdown"
    assert config.event is not None
    assert config.event.target.isoformat() == "2030-10-01T09:00:00-04:00"
    assert config.event.timezone == ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "clock"},
        {"mode": "date", "message": ""},
        {"mode": "date", "message": "x" * 161},
        {"mode": "date", "message": "A good day", "event_timezone": "invalid"},
    ],
)
def test_invalid_date_edits_leave_existing_configuration_untouched(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    path = write_config(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ConfigError):
        configure_settings(path, **changes)

    assert path.read_bytes() == before


def test_cli_date_initialization_does_not_prompt_for_an_event_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_xdg_roots(tmp_path, monkeypatch)

    def unexpected_prompt(_message: str) -> str:
        pytest.fail("complete date-mode arguments must not prompt for a target")

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    assert (
        cli.main(
            [
                "init",
                "--mode",
                "date",
                "--message",
                "A good day",
                "--timezone",
                "Etc/UTC",
            ]
        )
        == 0
    )
    config = load_config()
    assert config.event is None
    assert config.overlay.mode == "date"
    assert config.overlay.message == "A good day"
    assert capsys.readouterr().err == ""


def test_cli_can_toggle_date_mode_without_discarding_the_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path)
    before = load_config(path)

    assert (
        cli.main(
            [
                "configure",
                "--config",
                str(path),
                "--mode",
                "date",
                "--message",
                "A good day",
            ]
        )
        == 0
    )
    assert load_config(path).overlay.mode == "date"
    assert load_config(path).event == before.event
    assert capsys.readouterr().err == ""


def test_date_doctor_stays_read_only_and_redacts_date_message_and_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _date_config(tmp_path)
    config = load_config(path)
    photo = make_image(config.wallpaper.source_directory / "sample.png")
    before = {
        item: (item.read_bytes(), item.stat().st_mtime_ns) for item in (path, photo)
    }
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(
        cli, "resolve_font", lambda _font, **_kwargs: tmp_path / "private-font.ttf"
    )
    monkeypatch.setattr(
        cli, "discover_layout", lambda display: display.profiles["fixture"]
    )

    report, healthy = cli.doctor_report(path)

    assert healthy
    assert report["privacy"] == "redacted"
    encoded = json.dumps(report)
    for private in (
        "A good day",
        "America/Los_Angeles",
        str(tmp_path),
        "fixture-panel",
    ):
        assert private not in encoded
    assert "event" not in report
    assert {
        item: (item.read_bytes(), item.stat().st_mtime_ns) for item in before
    } == before

    private_report, private_healthy = cli.doctor_report(path, include_private=True)
    assert private_healthy
    assert "event" not in private_report
    private_encoded = json.dumps(private_report)
    assert "A good day" in private_encoded
    assert "America/Los_Angeles" in private_encoded
