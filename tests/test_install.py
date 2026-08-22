from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_image, write_config

import countscape.install as install_module
from countscape.errors import ConfigError, IntegrationError, PhotoError, StateError
from countscape.gnome import apply_wallpaper
from countscape.install import (
    INSTALL_MANIFEST_SCHEMA_VERSION,
    SERVICE_NAME,
    TIMER_NAME,
    PackageEnvironment,
    _installed_package_environment,
    initialize_config,
    install,
    uninstall,
    unit_contents,
)
from countscape.state import OWNERSHIP_MARKER, read_json


class FakeSystemctl:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.links: dict[str, str] = {}

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[2] == "link":
            for raw in command[3:]:
                path = Path(raw)
                self.links[path.name] = str(path.resolve())
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[2] == "show":
            path = self.links.get(command[-1], "")
            return subprocess.CompletedProcess(command, 0, f"{path}\n", "")
        if command[2] == "disable":
            for name in command[3:]:
                if not name.startswith("-"):
                    self.links.pop(Path(name).name, None)
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


class PartiallyLinkFailingSystemctl(FakeSystemctl):
    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemctl", "--user", "link"]:
            self.commands.append(command)
            first = Path(command[3])
            self.links[first.name] = str(first.resolve())
            return subprocess.CompletedProcess(command, 1, "", "link failed")
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


def _package_environment(
    executable: Path,
    *,
    version: str = "0.1.0",
) -> PackageEnvironment:
    return PackageEnvironment(python=executable, version=version)


@pytest.mark.parametrize(
    "artifact",
    (
        "install.json",
        "gnome-background.json",
        f"systemd/{SERVICE_NAME}",
        f"systemd/{TIMER_NAME}",
    ),
)
def test_init_force_refuses_existing_integration_before_mutation(
    tmp_path: Path,
    artifact: str,
) -> None:
    state = tmp_path / "state"
    config_path = write_config(tmp_path, state=state)
    before = config_path.read_bytes()
    integration_artifact = state / artifact
    integration_artifact.parent.mkdir(parents=True, exist_ok=True)
    integration_artifact.write_text("existing integration\n", encoding="utf-8")
    replacement_photos = tmp_path / "replacement photos"
    replacement_state = tmp_path / "replacement state"

    with pytest.raises(ConfigError, match="run countscape uninstall"):
        initialize_config(
            target="2032-01-01T12:00:00+00:00",
            timezone="Etc/UTC",
            source_directory=replacement_photos,
            state_directory=replacement_state,
            config_path=config_path,
            force=True,
        )

    assert config_path.read_bytes() == before
    assert integration_artifact.read_text(encoding="utf-8") == (
        "existing integration\n"
    )
    assert not replacement_photos.exists()
    assert not replacement_state.exists()


class FakeDistribution:
    def __init__(
        self,
        location: Path,
        *,
        direct_url: str | None = None,
        version: str = "1.2.3",
    ) -> None:
        self.location = location
        self.direct_url = direct_url
        self.version = version

    def read_text(self, name: str) -> str | None:
        assert name == "direct_url.json"
        return self.direct_url

    def locate_file(self, _path: str) -> Path:
        return self.location


def test_durable_uv_tool_environment_preserves_symlinked_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_directory = tmp_path / "uv-tools"
    environment = tool_directory / "countscape"
    base_python = _make_executable(tmp_path / "managed-python" / "python3.14")
    python = environment / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(base_python)
    (environment / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    package_location = environment / "lib" / "python3.14" / "site-packages"
    package_location.mkdir(parents=True)
    installed = FakeDistribution(package_location)
    monkeypatch.setenv("UV_TOOL_DIR", str(tool_directory))
    monkeypatch.setattr(install_module, "distribution", lambda _name: installed)
    monkeypatch.setattr(sys, "prefix", str(environment))
    monkeypatch.setattr(sys, "executable", str(python))

    detected = _installed_package_environment()

    assert detected == PackageEnvironment(python=python.absolute(), version="1.2.3")
    service, _timer = unit_contents(detected.python, tmp_path / "config.toml")
    assert f'ExecStart="{python.absolute()}"' in service
    assert str(base_python.resolve()) not in service


def test_editable_tool_environment_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = tmp_path / "uv-tools" / "countscape"
    package_location = environment / "lib" / "python3.14" / "site-packages"
    package_location.mkdir(parents=True)
    installed = FakeDistribution(
        package_location,
        direct_url=json.dumps({"dir_info": {"editable": True}}),
    )
    monkeypatch.setattr(install_module, "distribution", lambda _name: installed)

    with pytest.raises(IntegrationError, match="editable or source-checkout"):
        _installed_package_environment()


def test_ephemeral_uvx_environment_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_directory = tmp_path / "uv-cache"
    environment = cache_directory / "archive-v0" / "temporary-tool"
    python = _make_executable(environment / "bin" / "python")
    package_location = environment / "lib" / "python3.14" / "site-packages"
    package_location.mkdir(parents=True)
    (environment / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    installed = FakeDistribution(package_location)
    monkeypatch.setenv("UV_CACHE_DIR", str(cache_directory))
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "uv-tools"))
    monkeypatch.setattr(install_module, "distribution", lambda _name: installed)
    monkeypatch.setattr(sys, "prefix", str(environment))
    monkeypatch.setattr(sys, "executable", str(python))

    with pytest.raises(IntegrationError, match="ephemeral `uvx`"):
        _installed_package_environment()


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
    config_path = write_config(
        tmp_path,
        seed="stable-machine",
        state=xdg_state / "countscape",
    )
    base_python = _make_executable(tmp_path / "managed python" / "python3.14")
    executable = tmp_path / "tool environment" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(base_python)
    fake = FakeSystemctl()
    config_before = config_path.read_bytes()
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)

    assert (
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=True,
            runner=fake,
        )
        == config_path.resolve()
    )
    unit_directory = xdg_state / "countscape" / "systemd"
    service_path = unit_directory / "countscape.service"
    timer_path = unit_directory / "countscape.timer"
    first_service = service_path.read_text(encoding="utf-8")
    first_timer = timer_path.read_text(encoding="utf-8")

    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=True,
        runner=fake,
    )

    assert service_path.read_text(encoding="utf-8") == first_service
    assert timer_path.read_text(encoding="utf-8") == first_timer
    assert f'ExecStart="{executable.absolute()}" -m countscape apply' in first_service
    assert f'ExecStart="{base_python.resolve()}"' not in first_service
    assert ".venv" not in first_service
    assert config_path.read_bytes() == config_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    manifest = read_json(xdg_state / "countscape" / "install.json")
    assert manifest["schema_version"] == INSTALL_MANIFEST_SCHEMA_VERSION
    assert manifest["package_version"] == "0.1.0"
    assert manifest["config_path"] == str(config_path.resolve())
    assert manifest["runtime_state_directory"] == str(xdg_state / "countscape")
    assert manifest["python_executable"] == str(executable.absolute())
    assert manifest["output_directory"] == str(tmp_path / "data" / "generated")
    assert manifest["cache_directory"] == str(tmp_path / "cache")
    assert fake.commands.count(["systemctl", "--user", "enable", TIMER_NAME]) == 2
    assert fake.commands.count(["systemctl", "--user", "restart", TIMER_NAME]) == 2
    assert (
        fake.commands.count(
            ["systemctl", "--user", "link", str(service_path), str(timer_path)]
        )
        == 1
    )


def test_reinstall_update_and_rollback_preserve_installation_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    first_python = _make_executable(tmp_path / "tool-v1" / "bin" / "python")
    second_python = _make_executable(tmp_path / "tool-v2" / "bin" / "python")
    fake = FakeSystemctl()

    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(first_python, version="1.0.0"),
    )
    manifest_path = xdg_state / "countscape" / "install.json"
    first = read_json(manifest_path)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "different-xdg-config"))
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(second_python, version="2.0.0"),
    )
    updated = read_json(manifest_path)
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(first_python, version="1.0.0"),
    )
    rolled_back = read_json(manifest_path)

    assert updated["installation_id"] == first["installation_id"]
    assert rolled_back["installation_id"] == first["installation_id"]
    assert updated["package_version"] == "2.0.0"
    assert updated["python_executable"] == str(second_python.absolute())
    assert rolled_back["package_version"] == "1.0.0"
    assert rolled_back["python_executable"] == str(first_python.absolute())
    service_path = xdg_state / "countscape" / "systemd" / SERVICE_NAME
    assert f'ExecStart="{first_python.absolute()}"' in service_path.read_text(
        encoding="utf-8"
    )
    assert not (tmp_path / "different-xdg-config" / "systemd").exists()


@pytest.mark.parametrize("unit_name", (SERVICE_NAME, TIMER_NAME))
def test_install_refuses_a_foreign_systemd_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unit_name: str,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    unit_path = xdg_state / "countscape" / "systemd" / unit_name
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text("# This unit belongs to the user.\n", encoding="utf-8")

    with pytest.raises(IntegrationError, match="foreign systemd unit"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
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
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(
        tmp_path,
        seed="shared-fixture-seed",
        state=xdg_state / "countscape",
    )
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
                "schema_version": 1,
                "kind": foreign_kind,
                "ownership_id": "shared-fixture-seed",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StateError, match="foreign owner marker"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=FakeSystemctl(),
        )

    assert json.loads(marker.read_text(encoding="utf-8"))["kind"] == foreign_kind


def test_install_rejects_pre_release_ownership_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    output = tmp_path / "data" / "generated"
    output.mkdir(parents=True)
    marker = output / OWNERSHIP_MARKER
    marker.write_text(
        json.dumps(
            {
                "application": "countscape",
                "kind": "output",
                "ownership_id": "fixture-machine",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StateError, match="foreign owner marker"):
        install(
            config_path=config_path,
            start=False,
            runner=FakeSystemctl(),
            _environment=_package_environment(
                _make_executable(tmp_path / "tool" / "bin" / "python")
            ),
        )

    assert "schema_version" not in read_json(marker)


def test_modified_managed_unit_blocks_reinstall_and_uninstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeSystemctl()
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=False,
        runner=fake,
    )
    service = xdg_state / "countscape" / "systemd" / SERVICE_NAME
    timer = xdg_state / "countscape" / "systemd" / TIMER_NAME
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
            _environment=_package_environment(executable),
            start=False,
            runner=fake,
        )
    with pytest.raises(IntegrationError, match="not owned by this install"):
        uninstall(config_path=config_path, runner=fake)

    assert {path: path.read_bytes() for path in before} == before
    assert fake.commands == commands_before


def test_install_does_not_write_when_photo_pool_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    (tmp_path / "photos").mkdir()
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeSystemctl()

    with pytest.raises(PhotoError, match="no JPG"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=fake,
        )

    assert not (xdg_state / "countscape" / "systemd").exists()
    assert not (xdg_state / "countscape" / "install.json").exists()
    assert not fake.commands


def test_first_install_manifest_failure_rolls_back_unit_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")

    def fail_manifest(_path: Path, _data: dict[str, object]) -> None:
        raise OSError("injected manifest write failure")

    monkeypatch.setattr(install_module, "atomic_write_json", fail_manifest)

    with pytest.raises(IntegrationError, match="manifest write failure"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=FakeSystemctl(),
        )

    assert not (state / "install.json").exists()


def test_first_install_refuses_preexisting_output_lock_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    output = tmp_path / "data" / "generated"
    output.mkdir(parents=True)
    sentinel = output / ".countscape.lock"
    sentinel.write_text("user lock sentinel\n", encoding="utf-8")

    with pytest.raises(StateError, match="unowned.*reserved files"):
        install(
            config_path=config_path,
            start=False,
            runner=FakeSystemctl(),
            _environment=_package_environment(
                _make_executable(tmp_path / "tool" / "bin" / "python")
            ),
        )

    assert sentinel.read_text(encoding="utf-8") == "user lock sentinel\n"
    assert not (output / OWNERSHIP_MARKER).exists()
    assert not (state / "install.json").exists()
    assert not (state / "systemd" / SERVICE_NAME).exists()
    assert not (state / "systemd" / TIMER_NAME).exists()


def test_first_install_unit_write_failure_rolls_back_prior_unit_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    original_write = install_module.atomic_write_text

    def fail_timer(path: Path, contents: str) -> None:
        if path.name == TIMER_NAME:
            raise OSError("injected timer write failure")
        original_write(path, contents)

    monkeypatch.setattr(install_module, "atomic_write_text", fail_timer)

    with pytest.raises(IntegrationError, match="timer write failure"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=FakeSystemctl(),
        )

    assert not (state / "install.json").exists()
    assert not (state / "systemd" / SERVICE_NAME).exists()
    assert not (state / "systemd" / TIMER_NAME).exists()


def test_first_install_partial_link_failure_removes_new_links_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = PartiallyLinkFailingSystemctl()

    with pytest.raises(IntegrationError, match="link failed"):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=fake,
        )

    assert fake.links == {}
    assert not (state / "install.json").exists()
    assert not (state / "systemd" / SERVICE_NAME).exists()
    assert not (state / "systemd" / TIMER_NAME).exists()


def test_uninstall_removes_only_owned_runtime_and_preserves_user_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    source = make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    output = tmp_path / "data" / "generated"
    output.mkdir(parents=True)
    legacy_calibration = output / "calibration.png"
    legacy_calibration.write_text("unowned user file", encoding="utf-8")
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=False,
        runner=fake,
    )
    config_before = config_path.read_bytes()
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
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
    for name in ("render-state.json", ".countscape.lock"):
        (output / name).touch()
    unrelated_output = output / "keep-me.txt"
    unrelated_output.write_text("user data", encoding="utf-8")
    cache.mkdir(exist_ok=True)
    for name in ("base.png", "base.json"):
        (cache / name).touch()
    unrelated_cache = cache / "keep-me.txt"
    unrelated_cache.write_text("user data", encoding="utf-8")

    assert uninstall(config_path=config_path, runner=fake)

    assert fake.settings["picture-uri"] == "file:///original.png"
    assert not managed.exists()
    assert not (output / "render-state.json").exists()
    assert legacy_calibration.read_text(encoding="utf-8") == "unowned user file"
    assert not (output / ".countscape.lock").exists()
    assert not (cache / "base.png").exists()
    assert not (cache / "base.json").exists()
    assert not (output / OWNERSHIP_MARKER).exists()
    assert not (cache / OWNERSHIP_MARKER).exists()
    assert unrelated_output.read_text(encoding="utf-8") == "user data"
    assert unrelated_cache.read_text(encoding="utf-8") == "user data"
    assert config_path.read_bytes() == config_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    assert not (xdg_state / "countscape" / "systemd" / "countscape.service").exists()
    assert not (xdg_state / "countscape" / "systemd" / "countscape.timer").exists()
    assert not (xdg_state / "countscape" / "install.json").exists()
    assert fake.links == {}


@pytest.mark.parametrize("reference_kind", ("original", "newer_choice"))
def test_uninstall_stops_before_cleanup_for_gnome_referenced_cache_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference_kind: str,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    source = make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=False,
        runner=fake,
    )
    output = tmp_path / "data" / "generated"
    cache = tmp_path / "cache"
    managed = output / f"wallpaper-{'2' * 24}.png"
    cached_base = cache / "base.png"
    managed.write_bytes(b"managed wallpaper")
    cached_base.write_bytes(b"cached source image")
    (cache / "base.json").write_text("{}\n", encoding="utf-8")
    cached_uri = cached_base.resolve().as_uri()
    if reference_kind == "original":
        fake.settings["picture-uri"] = cached_uri
        fake.settings["picture-uri-dark"] = cached_uri
    apply_wallpaper(
        managed,
        multi_monitor=False,
        runner=fake,
        state_directory=state,
    )
    if reference_kind == "newer_choice":
        fake.settings["picture-uri"] = cached_uri
        fake.settings["picture-uri-dark"] = cached_uri

    config_before = config_path.read_bytes()
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
    preserved = (
        state / "install.json",
        state / "systemd" / SERVICE_NAME,
        state / "systemd" / TIMER_NAME,
        output / OWNERSHIP_MARKER,
        cache / OWNERSHIP_MARKER,
        managed,
        cached_base,
        cache / "base.json",
    )
    before = {path: path.read_bytes() for path in preserved}

    with pytest.raises(IntegrationError, match="cache image remains referenced"):
        uninstall(config_path=config_path, runner=fake)

    assert fake.settings["picture-uri"] == cached_uri
    assert fake.settings["picture-uri-dark"] == cached_uri
    assert {path: path.read_bytes() for path in preserved} == before
    assert config_path.read_bytes() == config_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before


def test_uninstall_without_manifest_rejects_unresolved_gnome_state(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    managed = tmp_path / f"wallpaper-{'3' * 24}.png"
    managed.write_bytes(b"managed wallpaper")
    managed_uri = managed.resolve().as_uri()
    fake = FakeIntegration()
    fake.settings = {
        "picture-uri": managed_uri,
        "picture-uri-dark": managed_uri,
        "picture-options": "zoom",
    }
    apply_wallpaper(
        managed,
        multi_monitor=False,
        runner=fake,
        state_directory=state,
    )
    state_path = state / "gnome-background.json"
    state_before = state_path.read_bytes()

    with pytest.raises(IntegrationError, match="wallpaper restoration is unresolved"):
        uninstall(state_directory=state, runner=fake)

    assert state_path.read_bytes() == state_before
    assert managed.read_bytes() == b"managed wallpaper"
    assert fake.settings["picture-uri"] == managed_uri
    assert fake.settings["picture-uri-dark"] == managed_uri


def test_config_based_uninstall_rejects_a_different_config_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=False,
        runner=fake,
    )
    other_config = tmp_path / "other-config" / "config.toml"
    other_config.parent.mkdir()
    other_config.write_bytes(config_path.read_bytes())
    commands_before = list(fake.commands)

    with pytest.raises(IntegrationError, match="configuration path.*does not match"):
        uninstall(config_path=other_config, runner=fake)

    assert fake.commands == commands_before
    assert (state / "install.json").exists()
    assert (state / "systemd" / SERVICE_NAME).exists()
    assert (state / "systemd" / TIMER_NAME).exists()
    assert not uninstall(state_directory=state, runner=fake)
    assert not (state / "install.json").exists()


def test_uninstall_state_override_recovers_from_missing_final_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state_directory = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state_directory)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(executable),
    )
    config_path.write_text("pre-release config\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        uninstall(config_path=config_path, runner=fake)

    assert not uninstall(state_directory=state_directory, runner=fake)
    assert config_path.read_text(encoding="utf-8") == "pre-release config\n"
    assert not (state_directory / "install.json").exists()
    assert not (state_directory / "systemd" / SERVICE_NAME).exists()
    assert not (state_directory / "systemd" / TIMER_NAME).exists()


def test_failed_service_stop_preserves_integration_and_runtime_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = StopFailingIntegration()
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
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
        xdg_state / "countscape" / "systemd" / SERVICE_NAME,
        xdg_state / "countscape" / "systemd" / TIMER_NAME,
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
        uninstall(config_path=config_path, runner=fake)

    assert {path: path.read_bytes() for path in tracked} == before
    assert fake.settings["picture-uri"] == managed.resolve().as_uri()
    assert ["systemctl", "--user", "stop", SERVICE_NAME] in fake.commands


@pytest.mark.parametrize("protected_kind", ("original", "current"))
def test_uninstall_stops_before_cleanup_for_gnome_referenced_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_kind: str,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FakeIntegration()
    install(
        config_path=config_path,
        _environment=_package_environment(executable),
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

    with pytest.raises(IntegrationError, match="choose another wallpaper"):
        uninstall(config_path=config_path, runner=fake)

    assert protected.read_bytes() == b"keep the referenced image"
    assert managed.read_bytes() == b"remove the managed image"
    assert fake.settings["picture-uri"] == protected_uri
    assert fake.settings["picture-uri-dark"] == protected_uri
    assert (output / OWNERSHIP_MARKER).exists()
    assert (tmp_path / "cache" / OWNERSHIP_MARKER).exists()
    assert (xdg_state / "countscape" / "install.json").exists()


def test_uninstall_ignores_unowned_directories_from_a_tampered_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    config_path = write_config(tmp_path, state=xdg_state / "countscape")
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

    with pytest.raises(IntegrationError, match="unsupported schema"):
        uninstall(state_directory=state_dir, runner=FakeSystemctl())

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
