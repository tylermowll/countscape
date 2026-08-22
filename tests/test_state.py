from __future__ import annotations

import re
from pathlib import Path

import pytest

import countscape.state as state_module
from countscape.errors import CountdownError, StateError
from countscape.state import (
    OWNERSHIP_MARKER,
    atomic_write_json,
    atomic_write_text,
    ensure_owned_directory,
    operation_lock,
    read_json,
    read_json_strict,
    validate_owned_directory,
)


def test_atomic_writes_replace_complete_content(tmp_path: Path) -> None:
    text_path = tmp_path / "nested" / "state.txt"
    text_path.parent.mkdir()
    text_path.write_text("old", encoding="utf-8")

    atomic_write_text(text_path, "new\n")

    assert text_path.read_text(encoding="utf-8") == "new\n"
    assert not list(text_path.parent.glob(f".{text_path.name}.*.tmp"))

    json_path = tmp_path / "state.json"
    atomic_write_json(json_path, {"z": 1, "a": 2})
    assert json_path.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "z": 1\n}\n'


def test_atomic_write_failure_preserves_destination_and_removes_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "state.txt"
    destination.write_text("known good\n", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(state_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(destination, "partial replacement\n")

    assert destination.read_text(encoding="utf-8") == "known good\n"
    assert tuple(tmp_path.iterdir()) == (destination,)


@pytest.mark.parametrize(
    ("contents", "expected"),
    (
        ('{"ok": true}', {"ok": True}),
        ("not json", {}),
        ("[]", {}),
    ),
)
def test_permissive_json_reader(
    contents: str, expected: dict[str, object], tmp_path: Path
) -> None:
    path = tmp_path / "state.json"
    path.write_text(contents, encoding="utf-8")
    assert read_json(path) == expected


def test_permissive_json_reader_handles_missing_and_unreadable_paths(
    tmp_path: Path,
) -> None:
    assert read_json(tmp_path / "missing.json") == {}
    directory = tmp_path / "directory.json"
    directory.mkdir()
    assert read_json(directory) == {}


def test_strict_json_reader_distinguishes_missing_and_invalid_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    assert read_json_strict(path) is None

    path.write_text("not json", encoding="utf-8")
    with pytest.raises(StateError, match="invalid JSON"):
        read_json_strict(path)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(StateError, match="JSON object"):
        read_json_strict(path)

    path.unlink()
    path.mkdir()
    with pytest.raises(StateError, match="could not read state file"):
        read_json_strict(path)


def test_strict_json_reader_rejects_symbolic_links(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "state.json"
    link.symlink_to(target)

    with pytest.raises(StateError, match="symbolic link"):
        read_json_strict(link)


def test_owned_directory_creation_is_idempotent_and_validated(tmp_path: Path) -> None:
    directory = tmp_path / "managed"

    created = ensure_owned_directory(
        directory,
        kind="output",
        ownership_id="owner-a",
        reserved_names=frozenset({"render-state.json"}),
    )
    marker_before = (created / OWNERSHIP_MARKER).read_bytes()

    assert (
        ensure_owned_directory(
            directory,
            kind="output",
            ownership_id="owner-a",
            reserved_names=frozenset({"render-state.json"}),
        )
        == created
    )
    assert (created / OWNERSHIP_MARKER).read_bytes() == marker_before
    assert (
        validate_owned_directory(
            directory,
            kind="output",
            ownership_id="owner-a",
        )
        == created
    )
    assert (
        validate_owned_directory(
            directory,
            kind="cache",
            ownership_id="owner-a",
        )
        is None
    )
    assert (
        validate_owned_directory(
            tmp_path / "absent",
            kind="output",
            ownership_id="owner-a",
        )
        is None
    )


def test_owned_directory_rejects_files_foreign_markers_and_reserved_content(
    tmp_path: Path,
) -> None:
    not_directory = tmp_path / "not-a-directory"
    not_directory.write_text("user data", encoding="utf-8")
    with pytest.raises(StateError, match="not a directory"):
        ensure_owned_directory(
            not_directory,
            kind="cache",
            ownership_id="owner-a",
            reserved_names=frozenset(),
        )

    foreign = tmp_path / "foreign"
    ensure_owned_directory(
        foreign,
        kind="cache",
        ownership_id="owner-a",
        reserved_names=frozenset(),
    )
    with pytest.raises(StateError, match="foreign owner marker"):
        ensure_owned_directory(
            foreign,
            kind="cache",
            ownership_id="owner-b",
            reserved_names=frozenset(),
        )

    colliding = tmp_path / "colliding"
    colliding.mkdir()
    (colliding / "render-state.json").write_text("user data", encoding="utf-8")
    (colliding / "wallpaper-12.png").write_text("user data", encoding="utf-8")
    with pytest.raises(
        StateError,
        match=r"render-state\.json, wallpaper-12\.png",
    ):
        ensure_owned_directory(
            colliding,
            kind="output",
            ownership_id="owner-a",
            reserved_names=frozenset({"render-state.json"}),
            reserved_patterns=(re.compile(r"wallpaper-[0-9]+\.png"),),
        )
    assert not (colliding / OWNERSHIP_MARKER).exists()


def test_operation_lock_rejects_concurrent_holder_and_can_be_reacquired(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "output"
    with (
        operation_lock(directory),
        pytest.raises(CountdownError, match="another render/apply operation"),
        operation_lock(directory),
    ):
        pytest.fail("the second lock must never be acquired")

    with operation_lock(directory):
        assert (directory / ".countscape.lock").is_file()
