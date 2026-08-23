from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
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
        self.link_paths: dict[str, Path] = {}
        self.manager_aliases: dict[str, set[str]] = {}
        self.manager_drop_ins: dict[str, tuple[Path, ...]] = {}
        self.extra_unit_paths: list[Path] = []

    @staticmethod
    def _unit_root() -> Path:
        return install_module.xdg_config_home() / "systemd" / "user"

    def _sync_links(self) -> None:
        root = self._unit_root()
        for name in (SERVICE_NAME, TIMER_NAME):
            link = self.link_paths.get(name, root / name)
            if link.is_symlink():
                self.links[name] = str(link.resolve())
            else:
                self.links.pop(name, None)

    def _unit_paths(self) -> tuple[Path, ...]:
        return (
            self._unit_root(),
            install_module.xdg_data_home() / "systemd" / "user",
            Path(os.environ["XDG_RUNTIME_DIR"]) / "systemd" / "user",
            *self.extra_unit_paths,
        )

    def _show_output(self, unit_name: str, fragment_path: str) -> str:
        names = [unit_name, *sorted(self.manager_aliases.get(unit_name, set()))]
        drop_ins = self.manager_drop_ins.get(unit_name, ())
        return "\n".join(
            (
                f"LoadState={'loaded' if fragment_path else 'not-found'}",
                f"FragmentPath={fragment_path}",
                f"Names={' '.join(names)}",
                f"DropInPaths={' '.join(str(path) for path in drop_ins)}",
                "",
            )
        )

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[:3] == ["systemd-analyze", "--user", "unit-paths"]:
            stdout = "\n".join(str(path) for path in self._unit_paths()) + "\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if command[2] == "link":
            root = self._unit_root()
            root.mkdir(parents=True, exist_ok=True)
            for raw in command[3:]:
                path = Path(raw)
                (root / path.name).symlink_to(path.resolve())
                self.link_paths[path.name] = root / path.name
                self.links[path.name] = str(path.resolve())
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[2] == "show":
            path = self.links.get(command[-1], "")
            return subprocess.CompletedProcess(
                command,
                0,
                self._show_output(command[-1], path),
                "",
            )
        if command[2] == "enable":
            root = self._unit_root()
            timer = root / TIMER_NAME
            wants = root / "graphical-session.target.wants" / TIMER_NAME
            wants.parent.mkdir(parents=True, exist_ok=True)
            if not wants.is_symlink():
                wants.symlink_to(timer.resolve())
        if command[2] == "disable":
            for name in command[3:]:
                if not name.startswith("-"):
                    self.links.pop(Path(name).name, None)
        if command[2] == "daemon-reload":
            self._sync_links()
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
        if command[0] in {"systemctl", "systemd-analyze"}:
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
        if command[:3] == ["systemctl", "--user", "stop"] and command[-1] == (
            SERVICE_NAME
        ):
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "stop failed")
        return super().__call__(command, **kwargs)


class TimerStopFailingOnceIntegration(FakeIntegration):
    def __init__(self) -> None:
        super().__init__()
        self.stop_side_effect = False

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if (
            command[:3] == ["systemctl", "--user", "stop"]
            and command[-1] == TIMER_NAME
            and not self.stop_side_effect
        ):
            self.commands.append(command)
            self.stop_side_effect = True
            return subprocess.CompletedProcess(command, 1, "", "late stop failure")
        return super().__call__(command, **kwargs)


class FailOnceIntegration(FakeIntegration):
    def __init__(self) -> None:
        super().__init__()
        self.fail_action: str | None = None
        self.successes_before_failure = 0

    def fail_next(self, action: str, *, after: int = 0) -> None:
        self.fail_action = action
        self.successes_before_failure = after

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "systemctl" and command[2] == self.fail_action:
            if self.successes_before_failure:
                self.successes_before_failure -= 1
            else:
                self.commands.append(command)
                self.fail_action = None
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    f"injected {command[2]} failure",
                )
        return super().__call__(command, **kwargs)


class StaleManagerIntegration(FailOnceIntegration):
    def __init__(self) -> None:
        super().__init__()
        self.loaded_links: dict[str, str] = {}

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemctl", "--user", "show"]:
            self.commands.append(command)
            path = self.loaded_links.get(command[-1], "")
            return subprocess.CompletedProcess(
                command,
                0,
                self._show_output(command[-1], path),
                "",
            )
        result = super().__call__(command, **kwargs)
        if (
            command[:3] == ["systemctl", "--user", "daemon-reload"]
            and result.returncode == 0
        ):
            self.loaded_links = dict(self.links)
        return result


class PartiallyLinkFailingSystemctl(FakeSystemctl):
    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemctl", "--user", "link"]:
            self.commands.append(command)
            first = Path(command[3])
            root = self._unit_root()
            root.mkdir(parents=True, exist_ok=True)
            (root / first.name).symlink_to(first.resolve())
            self.link_paths[first.name] = root / first.name
            self.links[first.name] = str(first.resolve())
            return subprocess.CompletedProcess(command, 1, "", "link failed")
        return super().__call__(command, **kwargs)


class StalePartialLinkRollbackSystemctl(FakeSystemctl):
    def __init__(self) -> None:
        super().__init__()
        self.partial_link_failed = False
        self.rollback_reload_failed = False

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if (
            command[:3] == ["systemctl", "--user", "link"]
            and not self.partial_link_failed
        ):
            self.commands.append(command)
            self.partial_link_failed = True
            first = Path(command[3])
            root = self._unit_root()
            root.mkdir(parents=True, exist_ok=True)
            (root / first.name).symlink_to(first.resolve())
            self.link_paths[first.name] = root / first.name
            # The manager view remains stale and reports the disk link as absent.
            return subprocess.CompletedProcess(command, 1, "", "partial link failure")
        if (
            command[:3] == ["systemctl", "--user", "daemon-reload"]
            and self.partial_link_failed
            and not self.rollback_reload_failed
        ):
            self.commands.append(command)
            self.rollback_reload_failed = True
            return subprocess.CompletedProcess(command, 1, "", "reload unavailable")
        return super().__call__(command, **kwargs)


def _set_xdg_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    xdg_config = tmp_path / "xdg-config"
    xdg_state = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg-runtime"))
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


def _install_lifecycle_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: FakeIntegration,
) -> tuple[Path, Path]:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    install(
        config_path=config_path,
        start=False,
        runner=runner,
        _environment=_package_environment(executable),
    )
    return config_path, state


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
    assert manifest["unit_link_directory"] == str(xdg_config / "systemd" / "user")
    assert manifest["python_executable"] == str(executable.absolute())
    assert manifest["output_directory"] == str(tmp_path / "data" / "generated")
    assert manifest["cache_directory"] == str(tmp_path / "cache")
    assert fake.commands.count(["systemctl", "--user", "enable", TIMER_NAME]) == 1
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


def test_uninstall_uses_recorded_unit_link_root_after_xdg_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    original_root = fake._unit_root()
    original_links = (original_root / SERVICE_NAME, original_root / TIMER_NAME)
    assert all(path.is_symlink() for path in original_links)
    changed_root = tmp_path / "different-xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(changed_root))

    assert not uninstall(config_path=config_path, runner=fake)

    assert all(not path.is_symlink() for path in original_links)
    assert not (changed_root / "systemd").exists()
    assert not (state / "install.json").exists()


def test_manifest_rejects_nonabsolute_unit_link_directory_before_systemd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    manifest_path = state / "install.json"
    manifest = read_json(manifest_path)
    manifest["unit_link_directory"] = "relative/systemd/user"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    commands_before = list(fake.commands)

    with pytest.raises(IntegrationError, match="unit_link_directory must be absolute"):
        uninstall(config_path=config_path, runner=fake)

    assert fake.commands == commands_before
    assert (fake._unit_root() / SERVICE_NAME).is_symlink()
    assert (fake._unit_root() / TIMER_NAME).is_symlink()


@pytest.mark.parametrize("failure_point", (SERVICE_NAME, TIMER_NAME, "install.json"))
def test_reinstall_publication_failure_restores_exact_prior_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    first_python = _make_executable(tmp_path / "tool-v1" / "bin" / "python")
    second_python = _make_executable(tmp_path / "tool-v2" / "bin" / "python")
    fake = FakeSystemctl()
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(first_python, version="1.0.0"),
    )
    service_path = state / "systemd" / SERVICE_NAME
    timer_path = state / "systemd" / TIMER_NAME
    manifest_path = state / "install.json"
    paths = (service_path, timer_path, manifest_path)
    prior = {path: path.read_bytes() for path in paths}
    original_write_text = install_module.atomic_write_text
    original_write_json = install_module.atomic_write_json
    failed = False

    def fail_text(path: Path, contents: str) -> None:
        nonlocal failed
        if path.name == failure_point and not failed:
            failed = True
            raise OSError(f"injected {failure_point} publication failure")
        original_write_text(path, contents)

    def fail_json(path: Path, data: dict[str, object]) -> None:
        nonlocal failed
        if path.name == failure_point and not failed:
            failed = True
            raise OSError(f"injected {failure_point} publication failure")
        original_write_json(path, data)

    monkeypatch.setattr(install_module, "atomic_write_text", fail_text)
    monkeypatch.setattr(install_module, "atomic_write_json", fail_json)

    with pytest.raises(IntegrationError, match="prior generation was restored"):
        install(
            config_path=config_path,
            start=False,
            runner=fake,
            _environment=_package_environment(second_python, version="2.0.0"),
        )

    assert failed
    assert {path: path.read_bytes() for path in paths} == prior

    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(second_python, version="2.0.0"),
    )
    updated = read_json(manifest_path)
    assert updated["package_version"] == "2.0.0"
    assert f'ExecStart="{second_python.absolute()}"' in service_path.read_text(
        encoding="utf-8"
    )


def test_reinstall_systemd_failure_keeps_committed_generation_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    first_python = _make_executable(tmp_path / "tool-v1" / "bin" / "python")
    second_python = _make_executable(tmp_path / "tool-v2" / "bin" / "python")
    fake = FailOnceIntegration()
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(first_python, version="1.0.0"),
    )
    fake.fail_next("daemon-reload", after=1)

    with pytest.raises(IntegrationError, match="consistent unit generation"):
        install(
            config_path=config_path,
            start=False,
            runner=fake,
            _environment=_package_environment(second_python, version="2.0.0"),
        )

    service_path = state / "systemd" / SERVICE_NAME
    timer_path = state / "systemd" / TIMER_NAME
    manifest_path = state / "install.json"
    committed = read_json(manifest_path)
    assert committed["package_version"] == "2.0.0"
    assert committed["service_sha256"] == sha256(service_path.read_bytes()).hexdigest()
    assert committed["timer_sha256"] == sha256(timer_path.read_bytes()).hexdigest()

    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(second_python, version="2.0.0"),
    )


def test_manager_not_found_metadata_is_treated_as_an_absent_unit() -> None:
    fake = FakeSystemctl()

    assert (
        install_module._manager_unit_path(
            SERVICE_NAME,
            runner=fake,
        )
        is None
    )

    assert fake.commands == [
        [
            "systemctl",
            "--user",
            "show",
            "--all",
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=Names",
            "--property=DropInPaths",
            SERVICE_NAME,
        ]
    ]


def test_systemd_manager_query_failure_is_not_treated_as_an_absent_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = FailOnceIntegration()
    install(
        config_path=config_path,
        start=False,
        runner=fake,
        _environment=_package_environment(executable),
    )
    commands_before = len(fake.commands)
    fake.fail_next("show")

    with pytest.raises(IntegrationError, match="could not query systemd user unit"):
        uninstall(config_path=config_path, runner=fake)

    attempted = fake.commands[commands_before:]
    assert attempted == [
        ["systemctl", "--user", "daemon-reload"],
        [
            "systemctl",
            "--user",
            "show",
            "--all",
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=Names",
            "--property=DropInPaths",
            TIMER_NAME,
        ],
    ]
    assert (state / "install.json").exists()
    assert (state / "systemd" / SERVICE_NAME).exists()
    assert (state / "systemd" / TIMER_NAME).exists()


@pytest.mark.parametrize(
    ("metadata", "message"),
    (
        (
            "LoadState=loaded\nFragmentPath\nNames={unit}\nDropInPaths=\n",
            "malformed unit metadata",
        ),
        (
            "LoadState=loaded\nFragmentPath={path}\nNames={unit}\n",
            "incomplete unit metadata",
        ),
        (
            "LoadState=loaded\nFragmentPath=relative.service\nNames={unit}\n"
            "DropInPaths=\n",
            "non-absolute unit path",
        ),
        (
            "LoadState=not-found\nFragmentPath={path}\nNames={unit}\nDropInPaths=\n",
            "inconsistent not-found metadata",
        ),
        (
            "LoadState=loaded\nFragmentPath=\nNames={unit}\nDropInPaths=\n",
            "inconsistent loaded metadata",
        ),
        (
            "LoadState=masked\nFragmentPath={path}\nNames={unit}\nDropInPaths=\n",
            "unsupported load state",
        ),
    ),
)
def test_reinstall_rejects_invalid_structured_manager_metadata_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: str,
    message: str,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    managed_paths = (
        state / "systemd" / SERVICE_NAME,
        state / "systemd" / TIMER_NAME,
        state / "install.json",
    )
    before = {path: path.read_bytes() for path in managed_paths}
    commands_before = len(fake.commands)

    def invalid_metadata_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemctl", "--user", "show"]:
            fake.commands.append(command)
            unit_name = command[-1]
            output = metadata.format(
                unit=unit_name,
                path=state / "systemd" / unit_name,
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        return fake(command, **kwargs)

    with pytest.raises(IntegrationError, match=message):
        install(
            config_path=config_path,
            start=True,
            runner=invalid_metadata_runner,
            _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
        )

    attempted = fake.commands[commands_before:]
    assert not any(
        command[0] == "systemctl"
        and command[2] in {"link", "enable", "restart", "stop"}
        for command in attempted
    )
    assert {path: path.read_bytes() for path in managed_paths} == before


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "message"),
    (
        (1, "", "lookup failed", "lookup failed"),
        (0, "relative/systemd/user\n", "", "unsafe user-unit path"),
        (0, "\n", "", "no user-unit paths"),
    ),
)
def test_reinstall_fails_closed_on_invalid_systemd_unit_path_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    stderr: str,
    message: str,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    managed_paths = (
        state / "systemd" / SERVICE_NAME,
        state / "systemd" / TIMER_NAME,
        state / "install.json",
    )
    before = {path: path.read_bytes() for path in managed_paths}
    commands_before = len(fake.commands)

    def invalid_discovery_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["systemd-analyze", "--user", "unit-paths"]:
            fake.commands.append(command)
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout,
                stderr,
            )
        return fake(command, **kwargs)

    with pytest.raises(IntegrationError, match=message):
        install(
            config_path=config_path,
            start=True,
            runner=invalid_discovery_runner,
            _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
        )

    attempted = fake.commands[commands_before:]
    assert not any(
        command[0] == "systemctl"
        and command[2] in {"link", "enable", "restart", "stop"}
        for command in attempted
    )
    assert {path: path.read_bytes() for path in managed_paths} == before


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
    "topology",
    ("alias", "drop-in", "runtime"),
)
def test_uninstall_rejects_unsupported_unit_link_topology_before_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topology: str,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    # Add the standard enablement link before introducing the unsupported shape.
    install(
        config_path=config_path,
        start=True,
        runner=fake,
        _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
    )
    root = fake._unit_root()
    service_path = state / "systemd" / SERVICE_NAME
    if topology == "alias":
        (root / "countscape-alias.service").symlink_to(service_path)
    elif topology == "drop-in":
        drop_in = root / f"{SERVICE_NAME}.d"
        drop_in.mkdir()
        (drop_in / "override.conf").write_text("[Service]\n", encoding="utf-8")
    elif topology == "runtime":
        runtime = tmp_path / "xdg-runtime" / "systemd" / "user"
        runtime.mkdir(parents=True)
        (runtime / SERVICE_NAME).symlink_to(service_path)
    commands_before = len(fake.commands)

    with pytest.raises(IntegrationError, match="systemd|unit_link_directory"):
        uninstall(config_path=config_path, runner=fake)

    attempted = fake.commands[commands_before:]
    assert not any(command[2] in {"stop", "disable"} for command in attempted)
    assert (root / SERVICE_NAME).is_symlink()
    assert (root / TIMER_NAME).is_symlink()
    assert (root / "graphical-session.target.wants" / TIMER_NAME).is_symlink()
    assert (state / "install.json").exists()
    assert service_path.exists()


def test_uninstall_deduplicates_symlinked_effective_unit_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    install(
        config_path=config_path,
        start=True,
        runner=fake,
        _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
    )
    root = fake._unit_root()
    moved_root = tmp_path / "moved-unit-root"
    root.rename(moved_root)
    root.symlink_to(moved_root, target_is_directory=True)
    fake.extra_unit_paths.extend((root, moved_root))

    assert not uninstall(config_path=config_path, runner=fake)

    assert root.is_symlink()
    assert not (moved_root / SERVICE_NAME).is_symlink()
    assert not (moved_root / TIMER_NAME).is_symlink()
    assert not (moved_root / "graphical-session.target.wants" / TIMER_NAME).is_symlink()
    assert not (state / "install.json").exists()


def test_uninstall_preserves_unrelated_symlinked_unit_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, _state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    foreign_directory = tmp_path / "foreign-unit-directory"
    foreign_directory.mkdir()
    linked_directory = fake._unit_root() / "linked-directory"
    linked_directory.symlink_to(foreign_directory, target_is_directory=True)

    assert not uninstall(config_path=config_path, runner=fake)

    assert linked_directory.is_symlink()
    assert linked_directory.resolve() == foreign_directory


def test_uninstall_rejects_xdg_data_home_alias_before_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    data_root = install_module.xdg_data_home() / "systemd" / "user"
    data_root.mkdir(parents=True)
    alias = data_root / "countscape-data-alias.service"
    alias.symlink_to(state / "systemd" / SERVICE_NAME)
    commands_before = len(fake.commands)

    with pytest.raises(IntegrationError, match="alias or runtime link"):
        uninstall(config_path=config_path, runner=fake)

    attempted = fake.commands[commands_before:]
    assert not any(command[2] == "stop" for command in attempted)
    assert alias.is_symlink()
    assert (state / "install.json").exists()


def test_uninstall_rejects_external_unit_path_drop_in_before_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    external_root = tmp_path / "external-unit-root"
    drop_in = external_root / f"{TIMER_NAME}.d"
    drop_in.mkdir(parents=True)
    (drop_in / "override.conf").write_text("[Timer]\n", encoding="utf-8")
    fake.extra_unit_paths.append(external_root)
    commands_before = len(fake.commands)

    with pytest.raises(IntegrationError, match="drop-in topology"):
        uninstall(config_path=config_path, runner=fake)

    attempted = fake.commands[commands_before:]
    assert not any(command[2] == "stop" for command in attempted)
    assert (state / "install.json").exists()


@pytest.mark.parametrize("metadata", ("alias", "drop-in"))
def test_reinstall_rejects_manager_aliases_and_drop_ins_before_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: str,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    if metadata == "alias":
        fake.manager_aliases[SERVICE_NAME] = {"countscape-alias.service"}
    else:
        fake.manager_drop_ins[SERVICE_NAME] = (tmp_path / "override.conf",)
    commands_before = len(fake.commands)

    with pytest.raises(
        IntegrationError, match="unsupported aliases|unsupported drop-ins"
    ):
        install(
            config_path=config_path,
            start=True,
            runner=fake,
            _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
        )

    attempted = fake.commands[commands_before:]
    assert not any(command[2] == "restart" for command in attempted)
    assert (state / "install.json").exists()


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


def test_first_install_rollback_reload_failure_preserves_sources_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _xdg_config, xdg_state = _set_xdg_roots(tmp_path, monkeypatch)
    make_image(tmp_path / "photos" / "photo.jpg")
    state = xdg_state / "countscape"
    config_path = write_config(tmp_path, state=state)
    executable = _make_executable(tmp_path / "tool" / "bin" / "python")
    fake = StalePartialLinkRollbackSystemctl()

    with pytest.raises(
        IntegrationError, match="rollback incomplete.*reload unavailable"
    ):
        install(
            config_path=config_path,
            _environment=_package_environment(executable),
            start=False,
            runner=fake,
        )

    # The manager reported the partial disk link as absent. A failed reload
    # makes that view untrustworthy, so the complete ownership generation stays.
    assert not fake.links
    assert (state / "systemd" / SERVICE_NAME).exists()
    assert (state / "systemd" / TIMER_NAME).exists()
    assert (state / "install.json").exists()

    install(
        config_path=config_path,
        _environment=_package_environment(executable),
        start=False,
        runner=fake,
    )
    assert set(fake.links) == {SERVICE_NAME, TIMER_NAME}


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


def test_timer_stop_failure_occurs_before_any_link_removal_and_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = TimerStopFailingOnceIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    install(
        config_path=config_path,
        start=True,
        runner=fake,
        _environment=_package_environment(tmp_path / "tool" / "bin" / "python"),
    )
    root = fake._unit_root()
    links = (
        root / SERVICE_NAME,
        root / TIMER_NAME,
        root / "graphical-session.target.wants" / TIMER_NAME,
    )
    commands_before = len(fake.commands)

    with pytest.raises(IntegrationError, match="could not stop Countscape timer"):
        uninstall(config_path=config_path, runner=fake)

    attempted = fake.commands[commands_before:]
    assert fake.stop_side_effect
    assert ["systemctl", "--user", "stop", TIMER_NAME] in attempted
    assert ["systemctl", "--user", "stop", SERVICE_NAME] not in attempted
    assert not any(command[2] == "disable" for command in attempted)
    assert all(path.is_symlink() for path in links)
    assert (state / "systemd" / SERVICE_NAME).exists()
    assert (state / "systemd" / TIMER_NAME).exists()
    assert (state / "install.json").exists()

    assert not uninstall(config_path=config_path, runner=fake)
    assert all(not path.is_symlink() for path in links)


def test_uninstall_reload_failure_preserves_evidence_and_reconciles_stale_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = StaleManagerIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    output = tmp_path / "data" / "generated"
    cache = tmp_path / "cache"
    generated = output / f"wallpaper-{'4' * 24}.png"
    generated.write_bytes(b"generated")
    (output / "render-state.json").write_text("{}\n", encoding="utf-8")
    (cache / "base.png").write_bytes(b"cache")
    tracked = (
        state / "install.json",
        state / "systemd" / SERVICE_NAME,
        state / "systemd" / TIMER_NAME,
        output / OWNERSHIP_MARKER,
        cache / OWNERSHIP_MARKER,
        generated,
        output / "render-state.json",
        cache / "base.png",
    )
    before = {path: path.read_bytes() for path in tracked}
    fake.fail_next("daemon-reload", after=1)

    with pytest.raises(IntegrationError, match="injected daemon-reload failure"):
        uninstall(config_path=config_path, runner=fake)

    assert {path: path.read_bytes() for path in tracked} == before
    assert all(not path.is_symlink() for path in fake.link_paths.values())
    assert set(fake.loaded_links) == {SERVICE_NAME, TIMER_NAME}

    assert not uninstall(config_path=config_path, runner=fake)
    assert not (state / "install.json").exists()
    assert not (output / OWNERSHIP_MARKER).exists()
    assert not (cache / OWNERSHIP_MARKER).exists()


@pytest.mark.parametrize(
    "failure_phase",
    ("managed-data", "unit-source", "ownership-marker", "manifest"),
)
def test_uninstall_destructive_phases_retain_enough_evidence_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    fake = FakeIntegration()
    config_path, state = _install_lifecycle_case(tmp_path, monkeypatch, fake)
    output = tmp_path / "data" / "generated"
    cache = tmp_path / "cache"
    render_state = output / "render-state.json"
    render_state.write_text("{}\n", encoding="utf-8")
    (cache / "base.png").write_bytes(b"cache")
    targets = {
        "managed-data": render_state,
        "unit-source": state / "systemd" / TIMER_NAME,
        "ownership-marker": cache / OWNERSHIP_MARKER,
        "manifest": state / "install.json",
    }
    target = targets[failure_phase]
    original_unlink = Path.unlink
    failed = False

    def fail_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if path == target and not failed:
            failed = True
            raise OSError(f"injected {failure_phase} unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    with pytest.raises(IntegrationError, match="lifecycle operation can be retried"):
        uninstall(config_path=config_path, runner=fake)

    assert failed
    assert (state / "install.json").exists()
    if failure_phase == "managed-data":
        assert (state / "systemd" / SERVICE_NAME).exists()
        assert (state / "systemd" / TIMER_NAME).exists()
    if failure_phase == "unit-source":
        assert not (state / "systemd" / SERVICE_NAME).exists()
        assert (state / "systemd" / TIMER_NAME).exists()
        assert (output / OWNERSHIP_MARKER).exists()
    if failure_phase == "ownership-marker":
        assert not (output / OWNERSHIP_MARKER).exists()
        assert (cache / OWNERSHIP_MARKER).exists()
    if failure_phase == "manifest":
        assert not (output / OWNERSHIP_MARKER).exists()
        assert not (cache / OWNERSHIP_MARKER).exists()

    assert not uninstall(config_path=config_path, runner=fake)
    assert not (state / "install.json").exists()


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
