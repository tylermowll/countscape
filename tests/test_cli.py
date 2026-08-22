from pathlib import Path

import pytest
from conftest import write_config

import countscape.cli as cli
from countscape.config import load_config


def _set_xdg_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    roots = {
        "config": tmp_path / "xdg-config",
        "data": tmp_path / "xdg-data",
        "cache": tmp_path / "xdg-cache",
        "state": tmp_path / "xdg-state",
    }
    monkeypatch.setenv("XDG_CONFIG_HOME", str(roots["config"]))
    monkeypatch.setenv("XDG_DATA_HOME", str(roots["data"]))
    monkeypatch.setenv("XDG_CACHE_HOME", str(roots["cache"]))
    monkeypatch.setenv("XDG_STATE_HOME", str(roots["state"]))
    return roots


def test_doctor_is_non_mutating_and_has_no_repository_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "photos").mkdir()
    config_path = write_config(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    report, healthy = cli.doctor_report(config_path)

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert not healthy
    assert any("no JPG" in error for error in report["errors"])
    assert report["paths"] == {
        "photos": str((tmp_path / "photos").resolve()),
        "output": str((tmp_path / "data" / "generated").resolve()),
        "cache": str((tmp_path / "cache").resolve()),
    }
    assert "repository_root" not in report["paths"]
    assert before == after


def test_init_uses_xdg_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _set_xdg_roots(tmp_path, monkeypatch)

    assert (
        cli.main(
            [
                "init",
                "--target",
                "2032-04-10T09:15:00-04:00",
                "--timezone",
                "America/New_York",
            ]
        )
        == 0
    )

    path = roots["config"] / "countscape" / "config.toml"
    config = load_config(path)
    assert config.wallpaper.source_directory == (
        roots["data"] / "countscape" / "backgrounds"
    )
    assert config.wallpaper.output_directory == (
        roots["data"] / "countscape" / "generated"
    )
    assert config.wallpaper.cache_directory == roots["cache"] / "countscape"
    assert config.wallpaper.source_directory.is_dir()


def test_init_supports_custom_values_and_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    roots = _set_xdg_roots(tmp_path, monkeypatch)
    photos = tmp_path / "festival photos"
    output = tmp_path / "wallpaper output"
    cache = tmp_path / "render cache"
    arguments = [
        "init",
        "--target",
        "2031-12-15T18:30:00+01:00",
        "--timezone",
        "Europe/Paris",
        "--label",
        "Until the winter market",
        "--after-message",
        "The market is open!",
        "--photos",
        str(photos),
        "--output",
        str(output),
        "--cache",
        str(cache),
        "--countdown-refresh-seconds",
        "300",
        "--photo-rotation-seconds",
        "900",
    ]

    assert cli.main(arguments) == 0
    path = roots["config"] / "countscape" / "config.toml"
    config = load_config(path)
    assert config.event.label == "Until the winter market"
    assert config.event.after_arrival_message == "The market is open!"
    assert config.event.target.isoformat() == "2031-12-15T18:30:00+01:00"
    assert config.wallpaper.source_directory == photos.resolve()
    assert config.wallpaper.output_directory == output.resolve()
    assert config.wallpaper.cache_directory == cache.resolve()
    assert config.wallpaper.countdown_refresh_seconds == 300
    assert config.wallpaper.photo_rotation_seconds == 900
    ownership_seed = config.wallpaper.selection_seed

    assert cli.main(arguments) == 1
    assert "use --force" in capsys.readouterr().err
    assert cli.main([*arguments, "--force"]) == 0
    assert load_config(path).wallpaper.selection_seed == ownership_seed


def test_configure_updates_all_public_settings(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, seed="stable-machine")
    before = load_config(config_path)
    photos = tmp_path / "new photo bank"

    assert (
        cli.main(
            [
                "configure",
                "--config",
                str(config_path),
                "--event-label",
                "Until the community concert",
                "--target",
                "2031-12-15T18:30:00+01:00",
                "--timezone",
                "Europe/Paris",
                "--after-message",
                "Music starts now!",
                "--photos",
                str(photos),
                "--countdown-refresh-seconds",
                "120",
                "--photo-rotation-seconds",
                "420",
                "--photo-fit",
                "cover",
                "--overlay-position",
                "bottom",
            ]
        )
        == 0
    )

    after = load_config(config_path)
    assert after.event.label == "Until the community concert"
    assert after.event.target.isoformat() == "2031-12-15T18:30:00+01:00"
    assert after.event.timezone.key == "Europe/Paris"
    assert after.event.after_arrival_message == "Music starts now!"
    assert after.wallpaper.source_directory == photos.resolve()
    assert after.wallpaper.countdown_refresh_seconds == 120
    assert after.wallpaper.photo_rotation_seconds == 420
    assert after.style.photo_fit == "cover"
    assert after.style.overlay_position == "bottom"
    assert after.wallpaper.output_directory == before.wallpaper.output_directory
    assert after.wallpaper.cache_directory == before.wallpaper.cache_directory
    assert after.wallpaper.selection_seed == "stable-machine"
    assert after.display == before.display
    assert not tuple(config_path.parent.glob(f".{config_path.name}.*.tmp"))


def test_configure_requires_a_setting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_config(tmp_path)

    assert cli.main(["configure", "--config", str(config_path)]) == 1
    assert "requires at least one setting" in capsys.readouterr().err


def test_configure_rejects_photo_directory_containing_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_config(tmp_path)
    before = config_path.read_bytes()

    assert (
        cli.main(
            [
                "configure",
                "--config",
                str(config_path),
                "--photos",
                str(config_path.parent),
            ]
        )
        == 1
    )

    assert "inside the photo directory" in capsys.readouterr().err
    assert config_path.read_bytes() == before


def test_configure_timezone_only_preserves_target_instant(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    before = load_config(config_path)

    assert (
        cli.main(
            [
                "configure",
                "--config",
                str(config_path),
                "--timezone",
                "Europe/Paris",
            ]
        )
        == 0
    )

    after = load_config(config_path)
    assert after.event.timezone.key == "Europe/Paris"
    assert after.event.target.isoformat() == "2027-06-01T18:00:00+02:00"
    assert after.event.target.timestamp() == before.event.target.timestamp()


def test_install_cli_uses_config_without_a_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_config(tmp_path)
    received: dict[str, object] = {}

    def fake_install(*, config_path: Path, start: bool) -> Path:
        received.update(config_path=config_path, start=start)
        return config_path

    monkeypatch.setattr(cli, "install", fake_install)

    assert (
        cli.main(
            [
                "install",
                "--config",
                str(config_path),
                "--no-start",
            ]
        )
        == 0
    )
    assert received == {"config_path": config_path, "start": False}
