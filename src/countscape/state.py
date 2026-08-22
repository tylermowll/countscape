from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from countscape.errors import CountdownError, StateError

OWNERSHIP_MARKER = ".countscape-owned.json"
OWNERSHIP_MARKER_SCHEMA_VERSION = 1


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError, OSError:
        return {}
    return value if isinstance(value, dict) else {}


def read_json_strict(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise StateError(f"state file must not be a symbolic link: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        raise StateError(f"could not read state file {path}: {error}") from error
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise StateError(f"invalid JSON in state file {path}: {error}") from error
    if not isinstance(value, dict):
        raise StateError(f"state file must contain a JSON object: {path}")
    return value


def ensure_owned_directory(
    directory: Path,
    *,
    kind: str,
    ownership_id: str,
    reserved_names: frozenset[str],
    reserved_patterns: tuple[re.Pattern[str], ...] = (),
) -> Path:
    path = directory.resolve()
    if path.exists() and not path.is_dir():
        raise StateError(f"managed path is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker = path / OWNERSHIP_MARKER
    existing = read_json_strict(marker)
    expected = {
        "application": "countscape",
        "schema_version": OWNERSHIP_MARKER_SCHEMA_VERSION,
        "kind": kind,
        "ownership_id": ownership_id,
    }
    if existing is not None:
        if existing != expected:
            raise StateError(f"managed directory has a foreign owner marker: {path}")
        return path
    collisions = [
        child.name
        for child in path.iterdir()
        if child.name in reserved_names
        or any(pattern.fullmatch(child.name) for pattern in reserved_patterns)
    ]
    if collisions:
        names = ", ".join(sorted(collisions))
        raise StateError(f"unowned managed directory contains reserved files: {names}")
    atomic_write_json(marker, expected)
    return path


def validate_owned_directory(
    directory: Path,
    *,
    kind: str,
    ownership_id: str,
) -> Path | None:
    path = directory.resolve()
    marker = path / OWNERSHIP_MARKER
    existing = read_json_strict(marker)
    expected = {
        "application": "countscape",
        "schema_version": OWNERSHIP_MARKER_SCHEMA_VERSION,
        "kind": kind,
        "ownership_id": ownership_id,
    }
    return path if existing == expected else None


@contextmanager
def operation_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".countscape.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CountdownError(
                "another render/apply operation is already running"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
