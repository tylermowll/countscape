from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import countscape.gnome as gnome_module
from countscape.errors import IntegrationError
from countscape.gnome import (
    apply_wallpaper,
    current_background_paths,
    get_background_settings,
    managed_output_paths,
    protected_output_paths,
    restore_background,
)
from countscape.state import atomic_write_json, read_json

ORIGINAL = {
    "picture-uri": "file:///original-light.png",
    "picture-uri-dark": "file:///original-dark.png",
    "picture-options": "zoom",
}


class FakeGSettings:
    def __init__(self) -> None:
        self.values = ORIGINAL.copy()
        self.fail_key: str | None = None
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        action = command[1]
        key = command[3]
        if action == "get":
            return subprocess.CompletedProcess(command, 0, repr(self.values[key]), "")
        if key == self.fail_key:
            return subprocess.CompletedProcess(command, 1, "", "simulated failure")
        self.values[key] = command[4]
        return subprocess.CompletedProcess(command, 0, "", "")


def _state(
    *,
    original: dict[str, str] | None = ORIGINAL,
    managed: list[object] | object | None = None,
    last_applied: object | None = None,
    pending: object | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {
        "application": "countscape",
        "schema_version": 1,
        "original": original,
        "managed_uris": [] if managed is None else managed,
    }
    if last_applied is not None:
        state["last_applied"] = last_applied
    if pending is not None:
        state["pending"] = pending
    return state


def _write_state(directory: Path, state: dict[str, object]) -> Path:
    path = directory / "gnome-background.json"
    atomic_write_json(path, state)
    return path


@pytest.mark.parametrize(
    ("runner", "message"),
    (
        (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("not found")),
            "not found",
        ),
        (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("gsettings", 8)
            ),
            "timed out",
        ),
        (
            lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 4, "", ""),
            "exit 4",
        ),
    ),
)
def test_gsettings_adapter_converts_process_failures(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    message: str,
) -> None:
    with pytest.raises(IntegrationError, match=message):
        get_background_settings(runner=runner)


@pytest.mark.parametrize(
    ("raw", "message"),
    (("not-a-literal", "invalid value"), ("123", "is not a string")),
)
def test_gsettings_adapter_requires_string_literals(raw: str, message: str) -> None:
    def runner(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, raw, "")

    with pytest.raises(IntegrationError, match=message):
        get_background_settings(runner=runner)


@pytest.mark.parametrize(
    ("state", "message"),
    (
        (_state(managed="file:///one.png"), "invalid managed URIs"),
        (_state(managed=["file:///one.png", 2]), "invalid managed URIs"),
        (_state(last_applied={}), "invalid applied settings"),
        (_state(pending=[]), "invalid transaction"),
    ),
)
def test_state_consumers_enforce_strict_integration_schema(
    state: dict[str, object],
    message: str,
    tmp_path: Path,
) -> None:
    _write_state(tmp_path, state)

    with pytest.raises(IntegrationError, match=message):
        managed_output_paths(state_directory=tmp_path)


def test_gnome_state_symlink_is_rejected_as_integration_error(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    atomic_write_json(target, _state(managed=["file:///managed.png"]))
    state = tmp_path / "state"
    state.mkdir()
    (state / "gnome-background.json").symlink_to(target)

    with pytest.raises(IntegrationError, match="symbolic link"):
        managed_output_paths(state_directory=state)


def test_apply_rejects_missing_wallpaper_without_desktop_access(tmp_path: Path) -> None:
    def unexpected_runner(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing files must fail before gsettings access")

    with pytest.raises(IntegrationError, match="does not exist"):
        apply_wallpaper(
            tmp_path / "missing.png",
            multi_monitor=False,
            state_directory=tmp_path / "state",
            runner=unexpected_runner,  # type: ignore[arg-type]
        )


def test_apply_refuses_an_existing_pending_transaction(tmp_path: Path) -> None:
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    desired = {
        "picture-uri": wallpaper.resolve().as_uri(),
        "picture-uri-dark": wallpaper.resolve().as_uri(),
        "picture-options": "zoom",
    }
    state = tmp_path / "state"
    state_path = _write_state(
        state,
        _state(
            managed=[wallpaper.resolve().as_uri()],
            pending={"desired": desired, "prior": ORIGINAL},
        ),
    )
    before = state_path.read_bytes()
    fake = FakeGSettings()

    with pytest.raises(IntegrationError, match="unfinished transaction"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            state_directory=state,
            runner=fake,
        )

    assert state_path.read_bytes() == before
    assert not any(command[1] == "set" for command in fake.commands)


def test_failed_update_rolls_back_and_retains_last_good_state(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    first = tmp_path / "wallpaper-first.png"
    second = tmp_path / "wallpaper-second.png"
    first.touch()
    second.touch()
    apply_wallpaper(first, multi_monitor=False, state_directory=state, runner=fake)
    first_state = read_json(state / "gnome-background.json")
    first_settings = fake.values.copy()
    fake.fail_key = "picture-uri-dark"

    with pytest.raises(IntegrationError, match="rollback succeeded"):
        apply_wallpaper(second, multi_monitor=False, state_directory=state, runner=fake)

    assert fake.values == first_settings
    saved = read_json(state / "gnome-background.json")
    assert "pending" not in saved
    assert saved == first_state


def test_final_state_write_failure_rolls_back_desktop_and_retains_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    original_write = gnome_module._write_integration_state
    writes = 0

    def fail_second_write(path: Path, data: dict[str, object]) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise IntegrationError("simulated final-state failure")
        original_write(path, data)

    monkeypatch.setattr(gnome_module, "_write_integration_state", fail_second_write)

    with pytest.raises(
        IntegrationError,
        match="simulated final-state failure; rollback succeeded",
    ):
        apply_wallpaper(
            wallpaper,
            multi_monitor=True,
            state_directory=state,
            runner=fake,
        )

    assert fake.values == ORIGINAL
    saved = read_json(state / "gnome-background.json")
    assert saved["pending"]["desired"]["picture-uri"] == wallpaper.resolve().as_uri()


class RollbackVerificationFailure(FakeGSettings):
    def __init__(self) -> None:
        super().__init__()
        self.desired_failure_seen = False

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if (
            command[1] == "set"
            and command[3] == "picture-uri-dark"
            and not self.desired_failure_seen
        ):
            self.desired_failure_seen = True
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "apply failed")
        if command[1] == "get" and self.desired_failure_seen:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "verification failed")
        return super().__call__(command, **kwargs)


def test_rollback_remains_pending_when_desktop_state_cannot_be_verified(
    tmp_path: Path,
) -> None:
    fake = RollbackVerificationFailure()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()

    with pytest.raises(IntegrationError, match="rollback was incomplete"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            state_directory=state,
            runner=fake,
        )

    assert "pending" in read_json(state / "gnome-background.json")


def test_state_write_os_error_prevents_desktop_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGSettings()
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()

    def fail_write(_path: Path, _state: dict[str, object]) -> None:
        raise OSError("read-only state directory")

    monkeypatch.setattr(gnome_module, "atomic_write_json", fail_write)

    with pytest.raises(IntegrationError, match="could not save GNOME.*read-only"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            state_directory=tmp_path / "state",
            runner=fake,
        )

    assert fake.values == ORIGINAL
    assert not any(command[1] == "set" for command in fake.commands)


def test_state_unlink_os_error_is_reported_after_preserving_user_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=False, state_directory=state, runner=fake)
    user_values = {
        "picture-uri": "file:///user-light.png",
        "picture-uri-dark": "file:///user-dark.png",
        "picture-options": "scaled",
    }
    fake.values = user_values.copy()
    state_path = state / "gnome-background.json"
    original_unlink = Path.unlink

    def fail_state_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == state_path:
            raise OSError("simulated unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_state_unlink)

    with pytest.raises(IntegrationError, match="could not remove GNOME.*unlink"):
        restore_background(state_directory=state, runner=fake)

    assert fake.values == user_values
    assert state_path.exists()


def test_restore_handles_missing_and_unowned_state(tmp_path: Path) -> None:
    fake = FakeGSettings()
    assert not restore_background(state_directory=tmp_path / "missing", runner=fake)

    state = tmp_path / "state"
    _write_state(state, _state(original=None))
    with pytest.raises(IntegrationError, match="no managed wallpaper"):
        restore_background(state_directory=state, runner=fake)


def test_restore_uses_pending_transaction_to_restore_picture_options(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    managed_uri = "file:///managed.png"
    desired = {
        "picture-uri": managed_uri,
        "picture-uri-dark": managed_uri,
        "picture-options": "spanned",
    }
    _write_state(
        state,
        _state(
            managed=[],
            pending={"desired": desired, "prior": ORIGINAL},
        ),
    )
    fake = FakeGSettings()
    fake.values = desired.copy()

    assert restore_background(state_directory=state, runner=fake)
    assert fake.values == ORIGINAL
    assert not (state / "gnome-background.json").exists()


@pytest.mark.parametrize(
    ("light", "dark", "expected"),
    (
        (
            "file:///folder%20one/light.png",
            "file://localhost/folder%20two/dark.png",
            (Path("/folder one/light.png"), Path("/folder two/dark.png")),
        ),
        (
            "file:///same.png",
            "file:///same.png",
            (Path("/same.png"),),
        ),
        ("https://example.com/image.png", "file://server/share/image.png", ()),
    ),
)
def test_current_background_paths_accept_only_local_file_uris(
    light: str,
    dark: str,
    expected: tuple[Path, ...],
) -> None:
    fake = FakeGSettings()
    fake.values["picture-uri"] = light
    fake.values["picture-uri-dark"] = dark

    assert current_background_paths(runner=fake) == expected


def test_managed_and_protected_paths_handle_pending_original_and_nonfile_uris(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    original = {
        "picture-uri": "file:///original%20light.png",
        "picture-uri-dark": "https://example.com/original.png",
        "picture-options": "zoom",
    }
    last_applied = {
        "picture-uri": "file:///managed.png",
        "picture-uri-dark": "file:///managed.png",
        "picture-options": "spanned",
    }
    pending_desired = {
        "picture-uri": "file://localhost/pending.png",
        "picture-uri-dark": "file://remote/ignored.png",
        "picture-options": "spanned",
    }
    _write_state(
        state,
        _state(
            original=original,
            managed=["file:///history.png", "https://example.com/ignored.png"],
            last_applied=last_applied,
            pending={"desired": pending_desired, "prior": last_applied},
        ),
    )

    assert set(managed_output_paths(state_directory=state)) == {
        Path("/history.png"),
        Path("/managed.png"),
        Path("/pending.png"),
    }
    assert set(protected_output_paths(state_directory=state)) == {
        Path("/original light.png"),
        Path("/managed.png"),
        Path("/pending.png"),
    }
    assert managed_output_paths(state_directory=tmp_path / "missing") == ()
    assert protected_output_paths(state_directory=tmp_path / "missing") == ()
