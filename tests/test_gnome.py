from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from countscape.errors import IntegrationError
from countscape.gnome import (
    MAX_MANAGED_URI_HISTORY,
    apply_wallpaper,
    managed_output_paths,
    restore_background,
)
from countscape.state import read_json


class FakeGSettings:
    def __init__(self) -> None:
        self.values = {
            "picture-uri": "file:///original-light.png",
            "picture-uri-dark": "file:///original-dark.png",
            "picture-options": "zoom",
        }
        self.fail_key: str | None = None
        self.commands: list[list[str]] = []

    def __call__(
        self, command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "gsettings"
        self.commands.append(command)
        action = command[1]
        key = command[3]
        if action == "get":
            return subprocess.CompletedProcess(command, 0, repr(self.values[key]), "")
        assert action == "set"
        if key == self.fail_key:
            return subprocess.CompletedProcess(command, 1, "", "simulated failure")
        self.values[key] = command[4]
        return subprocess.CompletedProcess(command, 0, "", "")


def test_apply_snapshots_once_and_restore_is_conditional(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    first = tmp_path / "wallpaper-0.png"
    second = tmp_path / "wallpaper-1.png"
    first.touch()
    second.touch()

    apply_wallpaper(first, multi_monitor=True, runner=fake, state_directory=state)
    apply_wallpaper(second, multi_monitor=True, runner=fake, state_directory=state)
    saved = read_json(state / "gnome-background.json")
    assert saved["original"]["picture-uri"] == "file:///original-light.png"
    assert set(saved["managed_uris"]) == {
        first.resolve().as_uri(),
        second.resolve().as_uri(),
    }
    assert set(managed_output_paths(state_directory=state)) == {first, second}
    assert fake.values["picture-options"] == "spanned"

    # A URI from an older successful apply is still Countscape-managed.
    fake.values["picture-uri"] = first.resolve().as_uri()
    assert restore_background(runner=fake, state_directory=state)
    assert fake.values["picture-uri"] == "file:///original-light.png"
    assert fake.values["picture-uri-dark"] == "file:///original-dark.png"
    assert fake.values["picture-options"] == "zoom"
    assert not (state / "gnome-background.json").exists()


def test_apply_is_a_true_no_op_when_uri_and_state_are_current(
    tmp_path: Path,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=True, runner=fake, state_directory=state)
    state_path = state / "gnome-background.json"
    state_before = state_path.read_bytes()
    fake.commands.clear()

    apply_wallpaper(wallpaper, multi_monitor=True, runner=fake, state_directory=state)

    assert not any(command[1] == "set" for command in fake.commands)
    assert state_path.read_bytes() == state_before


def test_managed_uri_history_is_bounded_and_still_restores_recent_uri(
    tmp_path: Path,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpapers = [tmp_path / f"wallpaper-{index}.png" for index in range(100)]
    for wallpaper in wallpapers:
        wallpaper.touch()
        apply_wallpaper(
            wallpaper,
            multi_monitor=True,
            runner=fake,
            state_directory=state,
        )

    saved = read_json(state / "gnome-background.json")
    assert len(saved["managed_uris"]) == MAX_MANAGED_URI_HISTORY
    assert saved["managed_uris"][0] == wallpapers[-1].resolve().as_uri()
    assert wallpapers[0].resolve().as_uri() not in saved["managed_uris"]

    retained_uri = wallpapers[-20].resolve().as_uri()
    fake.values["picture-uri"] = retained_uri
    fake.values["picture-uri-dark"] = retained_uri
    assert restore_background(runner=fake, state_directory=state)
    assert fake.values == {
        "picture-uri": "file:///original-light.png",
        "picture-uri-dark": "file:///original-dark.png",
        "picture-options": "zoom",
    }


def test_true_no_op_compacts_oversized_managed_history(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=False, runner=fake, state_directory=state)
    state_path = state / "gnome-background.json"
    saved = read_json(state_path)
    saved["managed_uris"] = [
        f"file:///old-wallpaper-{index}.png" for index in range(5000)
    ]
    state_path.write_text(json.dumps(saved), encoding="utf-8")
    fake.commands.clear()

    apply_wallpaper(wallpaper, multi_monitor=False, runner=fake, state_directory=state)

    compacted = read_json(state_path)
    assert len(compacted["managed_uris"]) == MAX_MANAGED_URI_HISTORY
    assert compacted["managed_uris"][0] == wallpaper.resolve().as_uri()
    assert not any(command[1] == "set" for command in fake.commands)


def test_restore_preserves_newer_user_wallpaper(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=True, runner=fake, state_directory=state)
    fake.values["picture-uri"] = "file:///user-changed.png"
    assert restore_background(runner=fake, state_directory=state)
    assert fake.values["picture-uri"] == "file:///user-changed.png"
    assert fake.values["picture-uri-dark"] == "file:///original-dark.png"
    assert fake.values["picture-options"] == "spanned"
    assert not (state / "gnome-background.json").exists()


def test_restore_retires_state_when_both_wallpapers_were_replaced(
    tmp_path: Path,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=True, runner=fake, state_directory=state)
    fake.values.update(
        {
            "picture-uri": "file:///new-light.png",
            "picture-uri-dark": "file:///new-dark.png",
            "picture-options": "scaled",
        }
    )

    assert not restore_background(runner=fake, state_directory=state)
    assert fake.values == {
        "picture-uri": "file:///new-light.png",
        "picture-uri-dark": "file:///new-dark.png",
        "picture-options": "scaled",
    }
    assert not (state / "gnome-background.json").exists()


def test_partial_apply_rolls_back_current_values(tmp_path: Path) -> None:
    fake = FakeGSettings()
    fake.fail_key = "picture-uri-dark"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    with pytest.raises(IntegrationError, match="simulated failure"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            runner=fake,
            state_directory=tmp_path / "state",
        )
    assert fake.values["picture-uri"] == "file:///original-light.png"


class FailingTransactionSettings(FakeGSettings):
    def __init__(self) -> None:
        super().__init__()
        self.set_attempts: dict[str, int] = {}
        self.failures = {
            ("picture-uri-dark", 1),
            ("picture-uri", 2),
        }

    def __call__(
        self, command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[1] == "set":
            key = command[3]
            attempt = self.set_attempts.get(key, 0) + 1
            self.set_attempts[key] = attempt
            if (key, attempt) in self.failures:
                self.commands.append(command)
                return subprocess.CompletedProcess(
                    command, 1, "", "simulated transaction failure"
                )
        return super().__call__(command, **kwargs)


def test_pending_apply_transaction_can_be_safely_restored(tmp_path: Path) -> None:
    fake = FailingTransactionSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()

    with pytest.raises(IntegrationError, match="rollback was incomplete"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            runner=fake,
            state_directory=state,
        )

    state_path = state / "gnome-background.json"
    saved = read_json(state_path)
    desired_uri = wallpaper.resolve().as_uri()
    assert saved["pending"]["desired"]["picture-uri"] == desired_uri
    assert fake.values["picture-uri"] == desired_uri

    fake.failures.clear()
    assert restore_background(runner=fake, state_directory=state)
    assert fake.values == {
        "picture-uri": "file:///original-light.png",
        "picture-uri-dark": "file:///original-dark.png",
        "picture-options": "zoom",
    }
    assert not state_path.exists()


@pytest.mark.parametrize(
    ("contents", "message"),
    (
        ("not JSON", "invalid JSON"),
        (
            json.dumps(
                {
                    "application": "countscape",
                    "schema_version": 1,
                    "original": None,
                    "managed_uris": [],
                    "pending": {"desired": {}, "prior": {}},
                }
            ),
            "invalid transaction",
        ),
        (
            json.dumps(
                {
                    "application": "countscape",
                    "schema_version": 1,
                    "original": {
                        "picture-uri": "file:///original-light.png",
                        "picture-uri-dark": "file:///original-dark.png",
                        "picture-options": "zoom",
                        "preview_field": "unsupported",
                    },
                    "managed_uris": ["file:///managed.png"],
                }
            ),
            "invalid original",
        ),
    ),
)
def test_corrupt_gnome_state_is_never_silently_replaced(
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    state.mkdir()
    state_path = state / "gnome-background.json"
    state_path.write_text(contents, encoding="utf-8")
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    before_settings = fake.values.copy()

    with pytest.raises(IntegrationError, match=message):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            runner=fake,
            state_directory=state,
        )
    with pytest.raises(IntegrationError, match=message):
        restore_background(runner=fake, state_directory=state)

    assert state_path.read_text(encoding="utf-8") == contents
    assert fake.values == before_settings
    assert not any(command[1] == "set" for command in fake.commands)


def test_pre_release_gnome_state_schema_is_rejected(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    state.mkdir()
    state_path = state / "gnome-background.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "original": None,
                "managed_uris": [],
            }
        ),
        encoding="utf-8",
    )
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()

    with pytest.raises(IntegrationError, match="unsupported schema"):
        apply_wallpaper(
            wallpaper,
            multi_monitor=False,
            state_directory=state,
            runner=fake,
        )

    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 1
    assert not any(command[1] == "set" for command in fake.commands)


def test_original_none_is_promoted_after_a_user_wallpaper_change(
    tmp_path: Path,
) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "wallpaper.png"
    wallpaper.touch()
    managed_uri = wallpaper.resolve().as_uri()
    fake.values = {
        "picture-uri": managed_uri,
        "picture-uri-dark": managed_uri,
        "picture-options": "zoom",
    }

    apply_wallpaper(
        wallpaper,
        multi_monitor=False,
        runner=fake,
        state_directory=state,
    )
    assert read_json(state / "gnome-background.json")["original"] is None

    user_settings = {
        "picture-uri": "file:///user-light.png",
        "picture-uri-dark": "file:///user-dark.png",
        "picture-options": "scaled",
    }
    fake.values = user_settings.copy()
    apply_wallpaper(
        wallpaper,
        multi_monitor=False,
        runner=fake,
        state_directory=state,
    )

    assert read_json(state / "gnome-background.json")["original"] == user_settings
    assert restore_background(runner=fake, state_directory=state)
    assert fake.values == user_settings


def test_managed_paths_decode_file_uris_with_spaces(tmp_path: Path) -> None:
    fake = FakeGSettings()
    state = tmp_path / "state"
    wallpaper = tmp_path / "folder with spaces" / "wallpaper.png"
    wallpaper.parent.mkdir()
    wallpaper.touch()
    apply_wallpaper(wallpaper, multi_monitor=False, runner=fake, state_directory=state)
    assert managed_output_paths(state_directory=state) == (wallpaper,)
