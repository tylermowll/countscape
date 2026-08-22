import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import write_config

import countscape.cli as cli
from countscape.config import load_config
from countscape.errors import ConfigError, CountdownError, IntegrationError, StateError


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


def test_doctor_is_non_mutating_and_redacts_private_details_by_default(
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
    assert report["privacy"] == "redacted"
    assert report["checks"]["photos"] == {"ok": False}
    assert report["errors"] == [{"check": "photos", "message": "photos check failed"}]
    serialized = json.dumps(report)
    assert str(tmp_path) not in serialized
    assert "Until the lantern festival" not in serialized
    assert "America/New_York" not in serialized
    assert "fixture-panel" not in serialized
    assert before == after


def test_doctor_private_details_require_flag_and_print_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "photos").mkdir()
    config_path = write_config(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    assert (
        cli.main(
            [
                "doctor",
                "--config",
                str(config_path),
                "--json",
                "--include-private",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["privacy"] == "contains-private-data"
    assert report["paths"]["photos"] == str((tmp_path / "photos").resolve())
    assert report["event"]["label"] == "Until the lantern festival"
    assert "WARNING: private diagnostics" in captured.err


def test_status_redacts_raw_timer_and_render_state_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_config(tmp_path)
    private_detail = f"failed to read {tmp_path}/private-unit"
    raw_render = {
        "application": "countscape",
        "schema_version": 1,
        "output": "wallpaper-private.png",
        "bucket": 123,
        "text_bucket": 456,
        "photo": "family/private-photo.jpg",
        "layout_source": "private-display-connector",
        "rendered_at": "2026-08-22T12:34:56-04:00",
        "render_key": {"private_path": str(tmp_path / "private-font.ttf")},
    }
    monkeypatch.setattr(
        cli,
        "timer_status",
        lambda **_kwargs: {"active": False, "detail": private_detail},
    )
    monkeypatch.setattr(cli, "render_metadata", lambda _config: raw_render)

    assert cli.main(["status", "--config", str(config_path), "--json"]) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "privacy": "redacted",
        "timer": {"active": False},
        "render": {"available": True},
    }
    assert captured.err == ""
    assert str(tmp_path) not in captured.out
    assert "private-unit" not in captured.out
    assert "private-photo" not in captured.out
    assert "private-display-connector" not in captured.out

    assert cli.main(["status", "--config", str(config_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == (
        "privacy: redacted\ntimer: inactive\nlast render: available\n"
    )
    assert captured.err == ""
    assert str(tmp_path) not in captured.out
    assert "private-unit" not in captured.out
    assert "private-photo" not in captured.out
    assert "private-display-connector" not in captured.out


def test_status_private_details_require_flag_and_print_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_config(tmp_path)
    raw_timer = {"active": True, "detail": f"active at {tmp_path}/private-unit"}
    raw_render = {
        "application": "countscape",
        "schema_version": 1,
        "output": "wallpaper-private.png",
        "bucket": 123,
        "text_bucket": 456,
        "photo": "family/private-photo.jpg",
        "layout_source": "private-display-connector",
        "rendered_at": "2026-08-22T12:34:56-04:00",
        "render_key": {"private_path": str(tmp_path / "private-font.ttf")},
    }
    monkeypatch.setattr(cli, "timer_status", lambda **_kwargs: raw_timer)
    monkeypatch.setattr(cli, "render_metadata", lambda _config: raw_render)

    assert (
        cli.main(
            [
                "status",
                "--config",
                str(config_path),
                "--json",
                "--include-private",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "privacy": "contains-private-data",
        "timer": raw_timer,
        "render": raw_render,
    }
    assert "WARNING: private status" in captured.err
    assert "Review before sharing" in captured.err

    assert (
        cli.main(
            [
                "status",
                "--config",
                str(config_path),
                "--include-private",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert raw_timer["detail"] in captured.out
    assert raw_render["photo"] in captured.out
    assert "WARNING: private status" in captured.err
    assert "Review before sharing" in captured.err


@pytest.mark.parametrize("failure", ("config", "timer", "render"))
def test_status_failure_paths_are_private_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    private_path = tmp_path / "private-state" / "local-detail.json"
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "timer_status",
        lambda **_kwargs: {"active": False, "detail": "inactive"},
    )
    monkeypatch.setattr(cli, "render_metadata", lambda _config: None)
    if failure == "config":
        config_path = private_path
    elif failure == "timer":

        def fail_timer(**_kwargs: object) -> dict[str, object]:
            raise IntegrationError(f"timer state failed at {private_path}")

        monkeypatch.setattr(cli, "timer_status", fail_timer)
    else:

        def fail_render(_config: object) -> dict[str, object]:
            raise StateError(f"render state failed at {private_path}")

        monkeypatch.setattr(cli, "render_metadata", fail_render)

    arguments = ["status", "--config", str(config_path), "--json"]
    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "countscape: status check failed\n"
    assert str(private_path) not in captured.err

    assert cli.main([*arguments, "--include-private"]) == 1
    captured = capsys.readouterr()
    assert "WARNING: private status" in captured.err
    assert str(private_path) in captured.err


def test_config_io_diagnostic_is_redacted_unless_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = tmp_path / "private-config.toml"
    error = ConfigError(f"could not read configuration file {private_path}")
    monkeypatch.setattr(cli, "load_config", lambda _path: (_ for _ in ()).throw(error))

    assert cli.main(["status", "--config", str(private_path)]) == 1
    captured = capsys.readouterr()
    assert captured.err == "countscape: status check failed\n"
    assert str(private_path) not in captured.err

    assert cli.main(["status", "--config", str(private_path), "--include-private"]) == 1
    captured = capsys.readouterr()
    assert "WARNING: private status" in captured.err
    assert str(private_path) in captured.err


def test_top_level_version_uses_distribution_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "installed_version", lambda: "9.8.7")

    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out == "countscape 9.8.7\n"


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
    assert config.runtime.state_directory == roots["state"] / "countscape"
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
    state = tmp_path / "runtime state"
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
        "--state-directory",
        str(state),
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
    assert config.runtime.state_directory == state.resolve()
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

    assert "configuration and photo directories must not overlap" in (
        capsys.readouterr().err
    )
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


def test_doctor_reports_successful_photos_and_all_failure_categories_privately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_config(tmp_path)
    private_detail = str(tmp_path / "private-diagnostic")
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda tool: None if tool in {"gsettings", "systemctl"} else f"/bin/{tool}",
    )
    monkeypatch.setattr(
        cli,
        "scan_photo_pool",
        lambda _path: SimpleNamespace(
            photos=(tmp_path / "photos" / "synthetic.jpg",),
            signature="synthetic-signature",
        ),
    )

    def fail_font(_configured: object) -> Path:
        raise IntegrationError(f"font failed at {private_detail}")

    def fail_display(_configured: object) -> object:
        raise IntegrationError(f"display failed at {private_detail}")

    monkeypatch.setattr(cli, "resolve_font", fail_font)
    monkeypatch.setattr(cli, "discover_layout", fail_display)

    report, healthy = cli.doctor_report(config_path, include_private=True)

    assert not healthy
    assert report["checks"]["photos"] == {
        "ok": True,
        "count": 1,
        "signature": "synthetic-signature",
    }
    assert report["checks"]["font"] == {"ok": False}
    assert report["checks"]["display"] == {"ok": False}
    assert report["tools"]["gsettings"] == {"ok": False, "path": None}
    assert report["tools"]["systemctl"] == {"ok": False, "path": None}
    assert {error["check"] for error in report["errors"]} == {
        "font",
        "display",
        "tools",
    }
    assert private_detail in json.dumps(report)

    redacted, redacted_healthy = cli.doctor_report(config_path)
    assert not redacted_healthy
    assert redacted["checks"]["photos"] == {"ok": True}
    assert private_detail not in json.dumps(redacted)


def test_doctor_reports_missing_configuration_without_private_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "private" / "missing.toml"
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/bin/{tool}")

    report, healthy = cli.doctor_report(missing)

    assert not healthy
    assert report["checks"]["config"] == {"ok": False}
    assert report["errors"] == [{"check": "config", "message": "config check failed"}]
    assert str(missing) not in json.dumps(report)


def test_doctor_human_output_lists_checks_and_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "version": "0.1.0",
        "privacy": "redacted",
        "checks": {
            "config": {"ok": True},
            "display": {"ok": True, "monitor_count": 2},
            "font": {"ok": False},
        },
        "errors": [{"check": "font", "message": "font check failed"}],
    }
    monkeypatch.setattr(cli, "doctor_report", lambda *_args, **_kwargs: (report, False))

    assert cli.main(["doctor"]) == 1

    captured = capsys.readouterr()
    assert captured.out == (
        "version: 0.1.0\n"
        "privacy: redacted\n"
        "config: ok\n"
        "display: ok (2 logical)\n"
        "font: failed\n"
    )
    assert captured.err == "error [font]: font check failed\n"


def test_apply_retries_transaction_then_prunes_only_protected_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_config(tmp_path)
    config = load_config(config_path)
    layout = config.display.profiles["fixture"]
    output = tmp_path / "data" / "generated" / "wallpaper-result.png"
    protected = tmp_path / "data" / "generated" / "wallpaper-protected.png"
    calls: dict[str, list[object]] = {
        "render": [],
        "apply": [],
        "prune": [],
        "sleep": [],
    }

    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "discover_layout", lambda _display: layout)
    monkeypatch.setattr(cli, "operation_lock", lambda _directory: nullcontext())

    def fake_render(_config: object, _layout: object, *, acquire_lock: bool) -> Path:
        calls["render"].append(acquire_lock)
        if len(calls["render"]) == 1:
            raise IntegrationError("synthetic transient apply failure")
        return output

    def fake_apply(path: Path, **kwargs: object) -> None:
        calls["apply"].append((path, kwargs))

    def fake_prune(directory: Path, *, keep: tuple[Path, ...]) -> None:
        calls["prune"].append((directory, keep))

    monkeypatch.setattr(cli, "render_wallpaper", fake_render)
    monkeypatch.setattr(cli, "apply_wallpaper", fake_apply)
    monkeypatch.setattr(cli, "prune_generated_outputs", fake_prune)
    monkeypatch.setattr(cli, "protected_output_paths", lambda **_kwargs: (protected,))
    monkeypatch.setattr(
        cli.time, "sleep", lambda seconds: calls["sleep"].append(seconds)
    )

    assert cli._apply_with_retries(config_path, 2) == output
    assert calls["render"] == [False, False]
    assert calls["sleep"] == [1]
    assert calls["apply"] == [
        (
            output,
            {
                "multi_monitor": False,
                "state_directory": config.runtime.state_directory,
            },
        )
    ]
    assert calls["prune"] == [(config.wallpaper.output_directory, (output, protected))]

    monkeypatch.setattr(
        cli,
        "render_wallpaper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            IntegrationError("synthetic permanent failure")
        ),
    )
    with pytest.raises(IntegrationError, match="permanent"):
        cli._apply_with_retries(config_path, 1)
    with pytest.raises(CountdownError, match="at least 1"):
        cli._apply_with_retries(config_path, 0)


def test_init_prompts_for_missing_required_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(("2030-01-01T12:00:00+00:00", "Etc/UTC"))
    received: dict[str, object] = {}
    destination = tmp_path / "config" / "config.toml"
    monkeypatch.setattr("builtins.input", lambda _message: next(answers))

    def fake_initialize(**kwargs: object) -> Path:
        received.update(kwargs)
        return destination

    monkeypatch.setattr(cli, "initialize_config", fake_initialize)

    assert cli.main(["init", "--config", str(destination)]) == 0
    assert received["target"] == "2030-01-01T12:00:00+00:00"
    assert received["timezone"] == "Etc/UTC"
    assert capsys.readouterr().out == f"{destination}\n"


@pytest.mark.parametrize("response", ("", "   "))
def test_prompt_rejects_empty_input(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _message: response)

    with pytest.raises(ConfigError, match="value is required"):
        cli._prompt(None, "Synthetic prompt: ")


def test_prompt_translates_end_of_input_to_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def end_of_input(_message: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", end_of_input)

    with pytest.raises(ConfigError, match="pass it as an option"):
        cli._prompt(None, "Synthetic prompt: ")


def test_render_and_apply_commands_forward_outputs_and_retry_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_config(tmp_path)
    config = load_config(config_path)
    layout = config.display.profiles["fixture"]
    rendered = tmp_path / "rendered.png"
    applied = tmp_path / "applied.png"
    received: list[tuple[Path, int]] = []
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "discover_layout", lambda _display: layout)
    monkeypatch.setattr(cli, "render_wallpaper", lambda *_args: rendered)

    assert cli.main(["render", "--config", str(config_path)]) == 0
    assert capsys.readouterr().out == f"{rendered}\n"

    def fake_apply(path: Path, retries: int) -> Path:
        received.append((path, retries))
        return applied

    monkeypatch.setattr(cli, "_apply_with_retries", fake_apply)
    assert cli.main(["apply", "--config", str(config_path), "--retries", "3"]) == 0
    assert received == [(config_path, 3)]
    assert capsys.readouterr().out == f"{applied}\n"


@pytest.mark.parametrize("apply_result", (False, True))
def test_calibrate_preview_and_apply_use_the_expected_locking_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    apply_result: bool,
) -> None:
    config_path = write_config(tmp_path)
    config = load_config(config_path)
    layout = config.display.profiles["fixture"]
    output = tmp_path / "calibration.png"
    protected = tmp_path / "protected.png"
    calls: dict[str, list[object]] = {"render": [], "apply": [], "prune": []}
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "discover_layout", lambda _display: layout)
    monkeypatch.setattr(cli, "operation_lock", lambda _directory: nullcontext())

    def fake_render(
        _config: object,
        _layout: object,
        *,
        acquire_lock: bool = True,
    ) -> Path:
        calls["render"].append(acquire_lock)
        return output

    monkeypatch.setattr(cli, "render_calibration", fake_render)
    monkeypatch.setattr(
        cli,
        "apply_wallpaper",
        lambda path, **kwargs: calls["apply"].append((path, kwargs)),
    )
    monkeypatch.setattr(
        cli,
        "prune_generated_outputs",
        lambda directory, *, keep: calls["prune"].append((directory, keep)),
    )
    monkeypatch.setattr(cli, "protected_output_paths", lambda **_kwargs: (protected,))

    arguments = ["calibrate", "--config", str(config_path)]
    if apply_result:
        arguments.append("--apply")
    assert cli.main(arguments) == 0
    assert capsys.readouterr().out == f"{output}\n"
    assert calls["render"] == [not apply_result]
    if apply_result:
        assert calls["apply"] == [
            (
                output,
                {
                    "multi_monitor": False,
                    "state_directory": config.runtime.state_directory,
                },
            )
        ]
        assert calls["prune"] == [
            (config.wallpaper.output_directory, (output, protected))
        ]
    else:
        assert calls["apply"] == []
        assert calls["prune"] == []


@pytest.mark.parametrize(
    "metadata_error",
    (OSError("synthetic metadata failure"), json.JSONDecodeError("bad", "", 0)),
)
def test_status_treats_unreadable_render_metadata_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    metadata_error: Exception,
) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "timer_status",
        lambda **_kwargs: {"active": True, "detail": "active"},
    )

    def fail_metadata(_config: object) -> None:
        raise metadata_error

    monkeypatch.setattr(cli, "render_metadata", fail_metadata)

    assert cli.main(["status", "--config", str(config_path)]) == 0
    assert capsys.readouterr().out == (
        "privacy: redacted\ntimer: active\nlast render: none\n"
    )


@pytest.mark.parametrize(
    ("state_override", "restored", "expected_message"),
    (
        (None, False, "wallpaper unchanged"),
        ("recovery-state", True, "previous wallpaper restored"),
    ),
)
def test_uninstall_cli_supports_config_and_explicit_state_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state_override: str | None,
    restored: bool,
    expected_message: str,
) -> None:
    config_path = tmp_path / "config" / "config.toml"
    state_path = tmp_path / state_override if state_override else None
    received: list[tuple[Path | None, Path | None]] = []

    def fake_uninstall(
        *,
        config_path: Path | None,
        state_directory: Path | None,
    ) -> bool:
        received.append((config_path, state_directory))
        return restored

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    arguments = ["uninstall", "--config", str(config_path)]
    if state_path is not None:
        arguments.extend(("--state-directory", str(state_path)))

    assert cli.main(arguments) == 0
    assert received == [(None if state_path is not None else config_path, state_path)]
    assert expected_message in capsys.readouterr().out


def test_install_defaults_to_starting_and_keyboard_interrupt_returns_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    received: list[tuple[Path, bool]] = []

    def fake_install(*, config_path: Path, start: bool) -> Path:
        received.append((config_path, start))
        return config_path

    monkeypatch.setattr(cli, "install", fake_install)
    assert cli.main(["install", "--config", str(config_path)]) == 0
    assert received == [(config_path, True)]

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda _path: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert cli.main(["render", "--config", str(config_path)]) == 130
