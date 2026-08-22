from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import make_image, write_config

from countscape.errors import ConfigError, IntegrationError, PhotoError, StateError
from countscape.gnome import apply_wallpaper
from countscape.install import (
    SERVICE_NAME,
    TIMER_NAME,
    install,
    uninstall,
    unit_contents,
)
from countscape.state import OWNERSHIP_MARKER, read_json


class FakeSystemctl:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, "active\n", "")


class FakeIntegration(FakeSystemctl):
    def __init__(self) -> None:
        super().__init__()
        self.settings = {
            "picture-uri": "file:///original.png",
            "picture-uri-dark": "file:///original-dark.png",
            "picture-options": "zoom",
        }

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "systemctl":
            return super().__call__(command, **_kwargs)
        action = command[1]
        key = command[3]
        if action == "get":
            return subprocess.CompletedProcess(
                command,
                0,
                repr(self.settings[key]),
                "",
            )
        self.settings[key] = command[4]
        return subprocess.CompletedProcess(command, 0, "", "")


class StopFailingIntegration(FakeIntegration):
    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemctl", "--user", "stop"]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "stop failed")
        return super().__call__(command, **kwargs)


def _set_xdg_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    xdg_config = tmp_path / "xdg-config"
    xdg_state = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    return xdg_config, xdg_state


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o755)
    return path


def test_unit_contents_invoke_installed_python_module_and_quote_paths() -> None:
    service, timer = unit_contents(
        Path("/tmp/tool environment/bin/python"),
        Path("/tmp/config with space/config.toml"),
    )

    assert (
        'ExecStart="/tmp/tool environment/bin/python" -m countscape apply '
        '--config "/tmp/config with space/config.toml" --retries 3'
    ) in service
    assert ".venv" not in service
    assert "OnActiveSec=1s" in timer
    assert "OnCalendar=*-*-* *:*:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=graphical-session.target" in timer


def test_unit_contents_escape_systemd_percent_specifiers() -> None:
    service, _timer = unit_contents(
        Path("/tmp/tool%name/bin/python"),
        Path("/tmp/config%name/config.toml"),
    )

    assert 'ExecStart="/tmp/tool%%name/bin/python"' in service
    assert '--config "/tmp/config%%name/config.toml"' in service


def test_unit_contents_escape_systemd_environment_expansion() -> None:
    service, _timer = unit_contents(
        Path("/tmp/$HOME/bin/python"),
        Path("/tmp/${HOME}/config.toml"),
    )

    assert 'ExecStart="/tmp/$$HOME/bin/python"' in service
    assert '--config "/tmp/$${HOME}/config.toml"' in service


@pytest.mark.parametrize(
    ("countdown_refresh_seconds", "photo_rotation_seconds"),
    ((7, 60), (60, 90)),
)
def test_unit_contents_reject_non_wall_aligned_intervals(
    countdown_refresh_seconds: int,
    photo_rotation_seconds: int,
) -> None:
    with pytest.raises(ConfigError, match="evenly divide|whole number of minutes"):
        unit_contents(
            Path("/usr/bin/true"),
            Path("/tmp/config.toml"),
            countdown_refresh_seconds=countdown_refresh_seconds,
            photo_rotation_seconds=photo_rotation_seconds,
        )


def test_install_is_idempotent_and_has_no_checkout_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    source = make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, seed="stable-machine")
    executable = _make_executable(tmp_path / "tool environment" / "bin" / "python")
    fake = FakeSystemctl()
    config_before = config_path.read_bytes()
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)

    assert (
        install(
            config_path=config_path,
            executable=executable,
            start=True,
            runner=fake,
        )
        == config_path.resolve()
    )
    service_path = xdg_config / "systemd" / "user" / "countscape.service"
    timer_path = xdg_config / "systemd" / "user" / "countscape.timer"
    first_service = service_path.read_text(encoding="utf-8")
    first_timer = timer_path.read_text(encoding="utf-8")

    install(
        config_path=config_path,
        executable=executable,
        start=True,
        runner=fake,
    )

    assert service_path.read_text(encoding="utf-8") == first_service
    assert timer_path.read_text(encoding="utf-8") == first_timer
    assert f'ExecStart="{executable.resolve()}" -m countscape apply' in first_service
    assert ".venv" not in first_service
    assert config_path.read_bytes() == config_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    manifest = read_json(xdg_state / "countscape" / "install.json")
    assert manifest["config"] == str(config_path.resolve())
    assert manifest["python"] == str(executable.resolve())
    assert manifest["output_directory"] == str(tmp_path / "data" / "generated")
    assert manifest["cache_directory"] == str(tmp_path / "cache")
    assert fake.commands.count(["systemctl", "--user", "enable", TIMER_NAME]) == 2
    assert fake.commands.count(["systemctl", "--user", "restart", TIMER_NAME]) == 2


@pytest.mark.parametrize("unit_name", (SERVICE_NAME, TIMER_NAME))
def test_install_refuses_a_foreign_systemd_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unit_name: str,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    unit_path = xdg_config / "systemd" / "user" / unit_name
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text("# This unit belongs to the user.\n", encoding="utf-8")

    with pytest.raises(IntegrationError, match="foreign systemd unit"):
        install(
            config_path=config_path,
            executable=executable,
            start=False,
            runner=FakeSystemctl(),
        )

    assert unit_path.read_text(encoding="utf-8") == (
        "# This unit belongs to the user.\n"
    )
    assert not (xdg_state / "countscape" / "install.json").exists()


@pytest.mark.parametrize(
    ("managed", "foreign_kind"),
    (("output", "cache"), ("cache", "output")),
)
def test_install_rejects_shared_seed_marker_kind_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    managed: str,
    foreign_kind: str,
) -> None:
    _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, seed="shared-fixture-seed")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    directories = {
        "output": tmp_path / "data" / "generated",
        "cache": tmp_path / "cache",
    }
    directory = directories[managed]
    directory.mkdir(parents=True)
    marker = directory / OWNERSHIP_MARKER
    marker.write_text(
        json.dumps(
            {
                "application": "countscape",
                "kind": foreign_kind,
                "ownership_id": "shared-fixture-seed",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StateError, match="foreign owner marker"):
        install(
            config_path=config_path,
            executable=executable,
            start=False,
            runner=FakeSystemctl(),
        )

    assert json.loads(marker.read_text(encoding="utf-8"))["kind"] == foreign_kind


def test_modified_managed_unit_blocks_reinstall_and_uninstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeSystemctl()
    install(
        config_path=config_path,
        executable=executable,
        start=False,
        runner=fake,
    )
    service = xdg_config / "systemd" / "user" / SERVICE_NAME
    timer = xdg_config / "systemd" / "user" / TIMER_NAME
    manifest = xdg_state / "countscape" / "install.json"
    service.write_text(
        service.read_text(encoding="utf-8") + "# local edit\n",
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (service, timer, manifest)}
    commands_before = list(fake.commands)

    with pytest.raises(IntegrationError, match="not owned by this install"):
        install(
            config_path=config_path,
            executable=executable,
            start=False,
            runner=fake,
        )
    with pytest.raises(IntegrationError, match="not owned by this install"):
        uninstall(runner=fake)

    assert {path: path.read_bytes() for path in before} == before
    assert fake.commands == commands_before


def test_install_does_not_write_when_photo_pool_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    (tmp_path / "photos").mkdir()
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeSystemctl()

    with pytest.raises(PhotoError, match="no JPG"):
        install(
            config_path=config_path,
            executable=executable,
            start=False,
            runner=fake,
        )

    assert not (xdg_config / "systemd" / "user").exists()
    assert not (xdg_state / "countscape" / "install.json").exists()
    assert not fake.commands


def test_uninstall_removes_only_owned_runtime_and_preserves_user_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    source = make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        executable=executable,
        start=False,
        runner=fake,
    )
    config_before = config_path.read_bytes()
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
    output = tmp_path / "data" / "generated"
    cache = tmp_path / "cache"
    managed = output / "wallpaper-0123456789abcdef01234567.png"
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.touch()
    apply_wallpaper(
        managed,
        multi_monitor=False,
        runner=fake,
        state_directory=xdg_state / "countscape",
    )
    for name in ("render-state.json", "calibration.png", ".countscape.lock"):
        (output / name).touch()
    unrelated_output = output / "keep-me.txt"
    unrelated_output.write_text("user data", encoding="utf-8")
    cache.mkdir(exist_ok=True)
    for name in ("base.png", "base.json"):
        (cache / name).touch()
    unrelated_cache = cache / "keep-me.txt"
    unrelated_cache.write_text("user data", encoding="utf-8")

    assert uninstall(runner=fake)

    assert fake.settings["picture-uri"] == "file:///original.png"
    assert not managed.exists()
    assert not (output / "render-state.json").exists()
    assert not (output / "calibration.png").exists()
    assert not (output / ".countscape.lock").exists()
    assert not (cache / "base.png").exists()
    assert not (cache / "base.json").exists()
    assert not (output / OWNERSHIP_MARKER).exists()
    assert not (cache / OWNERSHIP_MARKER).exists()
    assert unrelated_output.read_text(encoding="utf-8") == "user data"
    assert unrelated_cache.read_text(encoding="utf-8") == "user data"
    assert config_path.read_bytes() == config_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    assert not (xdg_config / "systemd" / "user" / "countscape.service").exists()
    assert not (xdg_config / "systemd" / "user" / "countscape.timer").exists()
    assert not (xdg_state / "countscape" / "install.json").exists()


def test_failed_service_stop_preserves_integration_and_runtime_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = StopFailingIntegration()
    install(
        config_path=config_path,
        executable=executable,
        start=False,
        runner=fake,
    )
    output = tmp_path / "data" / "generated"
    cache = tmp_path / "cache"
    managed = output / f"wallpaper-{'2' * 24}.png"
    managed.touch()
    apply_wallpaper(
        managed,
        multi_monitor=False,
        runner=fake,
        state_directory=xdg_state / "countscape",
    )
    (output / "render-state.json").write_text("{}\n", encoding="utf-8")
    (cache / "base.png").write_bytes(b"cached image")
    (cache / "base.json").write_text("{}\n", encoding="utf-8")
    tracked = (
        xdg_config / "systemd" / "user" / SERVICE_NAME,
        xdg_config / "systemd" / "user" / TIMER_NAME,
        xdg_state / "countscape" / "install.json",
        xdg_state / "countscape" / "gnome-background.json",
        output / OWNERSHIP_MARKER,
        cache / OWNERSHIP_MARKER,
        output / "render-state.json",
        managed,
        cache / "base.png",
        cache / "base.json",
    )
    before = {path: path.read_bytes() for path in tracked}

    with pytest.raises(IntegrationError, match="could not stop Countscape service"):
        uninstall(runner=fake)

    assert {path: path.read_bytes() for path in tracked} == before
    assert fake.settings["picture-uri"] == managed.resolve().as_uri()
    assert ["systemctl", "--user", "stop", SERVICE_NAME] in fake.commands


@pytest.mark.parametrize(
    ("protected_kind", "restored"),
    (("original", True), ("current", False)),
)
def test_uninstall_retains_generated_file_referenced_by_gnome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_kind: str,
    restored: bool,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        executable=executable,
        start=False,
        runner=fake,
    )
    output = tmp_path / "data" / "generated"
    protected = output / f"wallpaper-{'1' * 24}.png"
    managed = output / f"wallpaper-{'2' * 24}.png"
    protected.write_bytes(b"keep the referenced image")
    managed.write_bytes(b"remove the managed image")
    protected_uri = protected.resolve().as_uri()
    if protected_kind == "original":
        fake.settings["picture-uri"] = protected_uri
        fake.settings["picture-uri-dark"] = protected_uri
    apply_wallpaper(
        managed,
        multi_monitor=False,
        runner=fake,
        state_directory=xdg_state / "countscape",
    )
    if protected_kind == "current":
        fake.settings["picture-uri"] = protected_uri
        fake.settings["picture-uri-dark"] = protected_uri

    assert uninstall(runner=fake) is restored

    assert protected.read_bytes() == b"keep the referenced image"
    assert not managed.exists()
    assert fake.settings["picture-uri"] == protected_uri
    assert fake.settings["picture-uri-dark"] == protected_uri


def test_uninstall_ignores_unowned_directories_from_a_tampered_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    config_path = write_config(tmp_path)
    unrelated = tmp_path / "unrelated-application"
    unrelated.mkdir()
    sentinel = unrelated / "base.json"
    sentinel.write_text("do not delete", encoding="utf-8")
    state_dir = xdg_state / "countscape"
    state_dir.mkdir(parents=True)
    (state_dir / "install.json").write_text(
        json.dumps(
            {
                "config": str(config_path),
                "output_directory": str(tmp_path / "data" / "generated"),
                "cache_directory": str(unrelated),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(IntegrationError, match="manifest is invalid"):
        uninstall(runner=FakeSystemctl())

    assert sentinel.read_text(encoding="utf-8") == "do not delete"


@pytest.mark.parametrize(
    ("countdown_refresh_seconds", "photo_rotation_seconds", "calendar"),
    [
        (60, 600, "*-*-* *:*:00"),
        (300, 900, "*-*-* *:*:00"),
        (5, 600, "*-*-* *:*:00/5"),
        (60, 10, "*-*-* *:*:00/10"),
    ],
)
def test_generated_units_pass_systemd_verify(
    tmp_path: Path,
    countdown_refresh_seconds: int,
    photo_rotation_seconds: int,
    calendar: str,
) -> None:
    analyzer = shutil.which("systemd-analyze")
    assert analyzer is not None
    service, timer = unit_contents(
        Path("/usr/bin/true"),
        tmp_path / "config.toml",
        countdown_refresh_seconds=countdown_refresh_seconds,
        photo_rotation_seconds=photo_rotation_seconds,
    )
    assert f"OnCalendar={calendar}" in timer
    assert "Persistent=true" in timer
    service_path = tmp_path / "countscape.service"
    timer_path = tmp_path / "countscape.timer"
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    result = subprocess.run(
        [
            analyzer,
            "--user",
            "verify",
            str(service_path),
            str(timer_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
