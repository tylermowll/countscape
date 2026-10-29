from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import make_image, write_config
from PIL import ImageFont
from test_install import (
    FakeIntegration,
    _make_executable,
    _package_environment,
    _set_xdg_roots,
)

import countscape.install as install_module
from countscape.config import AppConfig, load_config
from countscape.errors import ConfigError
from countscape.gnome import apply_wallpaper
from countscape.install import (
    SERVICE_NAME,
    TIMER_NAME,
    PackageEnvironment,
    configure_settings,
    initialize_config,
    install,
    uninstall,
)
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor
from countscape.render import render_wallpaper
from countscape.state import read_json


@dataclass
class LifecycleCase:
    path: Path
    source: Path
    layout: DisplayLayout
    fake: FakeIntegration
    environment: PackageEnvironment
    font: Path

    def font_runner(self, command, **_kwargs):
        assert command[0] == "fc-match"
        return subprocess.CompletedProcess(command, 0, str(self.font), "")

    def install(self, *, start: bool = False) -> None:
        install(
            config_path=self.path,
            start=start,
            runner=self.fake,
            _environment=self.environment,
        )


def _case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    date_only: bool,
) -> LifecycleCase:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    if date_only:
        path = initialize_config(mode="date", message="A good day", timezone="Etc/UTC")
    else:
        path = write_config(
            tmp_path, state=xdg_state / "countscape", photo_rotation_seconds=120
        )
    config = load_config(path)
    source = make_image(config.wallpaper.source_directory / "sample.png")
    layout = DisplayLayout(
        monitors=tuple(
            LogicalMonitor(
                x=index * 640,
                y=0,
                scale=1,
                transform=0,
                primary=index == 0,
                connectors=(f"fixture-panel-{index}",),
                physical=(PhysicalMonitor(f"fixture-panel-{index}", 640, 480),),
            )
            for index in range(2)
        ),
        layout_mode=1,
        source="fixture",
    )
    font = Path(ImageFont.truetype("DejaVuSans.ttf", 12).path)
    monkeypatch.setattr(install_module, "discover_layout", lambda _display: layout)
    monkeypatch.setattr(install_module, "resolve_font", lambda _font: font)
    executable = _make_executable(tmp_path / "persistent-tool" / "bin" / "python")
    return LifecycleCase(
        path,
        source,
        layout,
        FakeIntegration(),
        _package_environment(executable, version="0.3.0"),
        font,
    )


def _snapshot(*paths: Path) -> dict[Path, tuple[bytes, int]]:
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


@pytest.mark.parametrize("newer_uri", [None, "picture-uri", "picture-uri-dark"])
def test_date_only_render_install_apply_and_uninstall_preserve_user_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    newer_uri: str | None,
) -> None:
    case = _case(tmp_path, monkeypatch, date_only=True)
    config = load_config(case.path)
    assert config.event is None
    preserved = _snapshot(case.path, case.source)
    original = dict(case.fake.settings)
    output = render_wallpaper(
        config,
        case.layout,
        now=datetime(2026, 10, 29, 12, tzinfo=UTC),
        runner=case.font_runner,
    )
    assert case.fake.settings == original
    case.install(start=True)
    manifest = read_json(config.runtime.state_directory / "install.json")
    assert manifest["package_version"] == "0.3.0"
    service = Path(manifest["service_path"]).read_text(encoding="utf-8")
    assert f'ExecStart="{case.environment.python}" -m countscape apply' in service
    assert ".venv" not in service
    assert ["systemctl", "--user", "restart", TIMER_NAME] in case.fake.commands

    for _ in range(2):
        apply_wallpaper(
            output,
            multi_monitor=True,
            state_directory=config.runtime.state_directory,
            runner=case.fake,
        )
    assert case.fake.settings["picture-uri"] == output.as_uri()
    assert case.fake.settings["picture-uri-dark"] == output.as_uri()
    assert case.fake.settings["picture-options"] == "spanned"
    assert _snapshot(case.path, case.source) == preserved

    if newer_uri is not None:
        case.fake.settings[newer_uri] = "file:///newer-choice.png"
    assert uninstall(config_path=case.path, runner=case.fake)

    expected = original | (
        {newer_uri: "file:///newer-choice.png", "picture-options": "spanned"}
        if newer_uri is not None
        else {}
    )
    assert case.fake.settings == expected
    assert _snapshot(case.path, case.source) == preserved
    assert not output.exists()
    assert not (config.runtime.state_directory / "install.json").exists()
    assert not (config.runtime.state_directory / "gnome-background.json").exists()
    assert not (case.fake._unit_root() / SERVICE_NAME).is_symlink()
    assert not (case.fake._unit_root() / TIMER_NAME).is_symlink()


def test_mode_switches_preserve_installation_identity_and_support_config_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch, date_only=False)
    before = load_config(case.path)
    backup = case.path.read_bytes()
    source_before = _snapshot(case.source)
    case.environment = _package_environment(case.environment.python, version="0.2.0")
    case.install()
    manifest_path = before.runtime.state_directory / "install.json"
    original_manifest = read_json(manifest_path)
    stable = (
        "installation_id",
        "ownership_id",
        "config_path",
        "runtime_state_directory",
        "unit_directory",
        "unit_link_directory",
        "output_directory",
        "cache_directory",
    )

    configure_settings(case.path, mode="date", message="A good day")
    case.environment = _package_environment(case.environment.python, version="0.3.0")
    case.install()
    date = load_config(case.path)
    assert date.overlay.mode == "date"
    assert date.event == before.event
    assert date.wallpaper == before.wallpaper
    assert date.runtime == before.runtime
    date_manifest = read_json(manifest_path)
    assert date_manifest["package_version"] == "0.3.0"
    assert {key: date_manifest[key] for key in stable} == {
        key: original_manifest[key] for key in stable
    }

    configure_settings(case.path, mode="countdown")
    case.install()
    resumed = load_config(case.path)
    assert resumed.event == before.event
    assert resumed.overlay.mode == "countdown"
    assert resumed.overlay.message == date.overlay.message
    assert resumed.wallpaper == before.wallpaper
    assert resumed.runtime == before.runtime
    assert (
        read_json(manifest_path)["installation_id"]
        == original_manifest["installation_id"]
    )

    # A mode switch retains the new table; restoring the old config backup also
    # restores the schema shape understood by the previous package.
    assert "overlay" in tomllib.loads(case.path.read_text(encoding="utf-8"))
    case.path.write_bytes(backup)
    assert "overlay" not in tomllib.loads(case.path.read_text(encoding="utf-8"))
    assert load_config(case.path) == before
    case.environment = _package_environment(case.environment.python, version="0.2.0")
    case.install()
    rolled_back = read_json(manifest_path)
    assert rolled_back["package_version"] == "0.2.0"
    assert {key: rolled_back[key] for key in stable} == {
        key: original_manifest[key] for key in stable
    }
    assert _snapshot(case.source) == source_before


def test_date_only_forced_init_refuses_active_integration_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch, date_only=True)
    case.install()
    config: AppConfig = load_config(case.path)
    manifest_path = config.runtime.state_directory / "install.json"
    preserved = _snapshot(case.path, case.source, manifest_path)

    with pytest.raises(ConfigError, match="active or unresolved integration"):
        initialize_config(
            config_path=case.path,
            mode="date",
            message="A different day",
            timezone="Etc/UTC",
            force=True,
        )

    assert _snapshot(case.path, case.source, manifest_path) == preserved
