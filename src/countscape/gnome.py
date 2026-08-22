from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote, urlparse

from countscape.config import xdg_state_home
from countscape.errors import IntegrationError, StateError
from countscape.state import atomic_write_json, read_json_strict

SCHEMA = "org.gnome.desktop.background"
KEYS = ("picture-uri", "picture-uri-dark", "picture-options")
URI_KEYS = ("picture-uri", "picture-uri-dark")
MAX_MANAGED_URI_HISTORY = 64
Runner = Callable[..., subprocess.CompletedProcess[str]]


def integration_state_directory() -> Path:
    return xdg_state_home() / "countscape"


def _run_gsettings(
    arguments: list[str],
    *,
    runner: Runner = subprocess.run,
) -> str:
    try:
        result = runner(
            ["gsettings", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntegrationError(f"gsettings failed: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise IntegrationError(f"gsettings failed: {detail}")
    return result.stdout.strip()


def get_background_settings(*, runner: Runner = subprocess.run) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in KEYS:
        raw = _run_gsettings(["get", SCHEMA, key], runner=runner)
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError) as error:
            raise IntegrationError(
                f"gsettings returned an invalid value for {key}: {raw}"
            ) from error
        if not isinstance(parsed, str):
            raise IntegrationError(f"gsettings {key} is not a string")
        values[key] = parsed
    return values


def set_background_settings(
    values: dict[str, str],
    *,
    runner: Runner = subprocess.run,
) -> None:
    for key in KEYS:
        if key in values:
            _run_gsettings(["set", SCHEMA, key, values[key]], runner=runner)


def _valid_settings(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(key), str) for key in KEYS
    )


def _read_integration_state(path: Path) -> dict[str, object] | None:
    try:
        return read_json_strict(path)
    except StateError as error:
        raise IntegrationError(str(error)) from error


def _write_integration_state(path: Path, state: dict[str, object]) -> None:
    try:
        atomic_write_json(path, state)
    except OSError as error:
        raise IntegrationError(
            f"could not save GNOME integration state: {error}"
        ) from error


def _unlink_integration_state(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise IntegrationError(
            f"could not remove GNOME integration state: {error}"
        ) from error


def _validate_integration_state(state: dict[str, object]) -> None:
    original = state.get("original")
    if original is not None and not _valid_settings(original):
        raise IntegrationError("GNOME integration state has an invalid original")
    managed = state.get("managed_uris", [])
    if not isinstance(managed, list) or not all(
        isinstance(value, str) for value in managed
    ):
        raise IntegrationError("GNOME integration state has invalid managed URIs")
    last_applied = state.get("last_applied")
    if last_applied is not None and not _valid_settings(last_applied):
        raise IntegrationError("GNOME integration state has invalid applied settings")
    pending = state.get("pending")
    if pending is not None and (
        not isinstance(pending, dict)
        or not _valid_settings(pending.get("desired"))
        or not _valid_settings(pending.get("prior"))
    ):
        raise IntegrationError("GNOME integration state has an invalid transaction")


def _rollback_settings(values: dict[str, str], *, runner: Runner) -> bool:
    for key in KEYS:
        with suppress(IntegrationError):
            set_background_settings({key: values[key]}, runner=runner)
    try:
        return get_background_settings(runner=runner) == values
    except IntegrationError:
        return False


def _settings_uris(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        uri
        for key in URI_KEYS
        if isinstance((uri := value.get(key)), str)
    )


def _compact_managed_uris(
    state: dict[str, object], *, newest: str | None = None
) -> bool:
    """Keep a bounded, most-recent-first history of Countscape URIs."""
    previous = state.get("managed_uris", [])
    candidates = (
        *((newest,) if newest is not None else ()),
        *_settings_uris(state.get("last_applied")),
        *previous,
    )
    compacted = list(dict.fromkeys(candidates))[:MAX_MANAGED_URI_HISTORY]
    if compacted == previous:
        return False
    state["managed_uris"] = compacted
    return True


def apply_wallpaper(
    path: Path,
    *,
    multi_monitor: bool,
    runner: Runner = subprocess.run,
    state_directory: Path | None = None,
) -> None:
    if not path.is_file():
        raise IntegrationError(f"rendered wallpaper does not exist: {path}")
    state_dir = state_directory or integration_state_directory()
    state_path = state_dir / "gnome-background.json"
    loaded = _read_integration_state(state_path)
    state: dict[str, object]
    prior = get_background_settings(runner=runner)
    uri = path.resolve().as_uri()
    desired = {
        "picture-uri": uri,
        "picture-uri-dark": uri,
        "picture-options": "spanned" if multi_monitor else "zoom",
    }

    if loaded is None:
        original: dict[str, str] | None = prior if prior != desired else None
        state = {
            "version": 1,
            "original": original,
            "managed_uris": [],
        }
    else:
        state = loaded
        _validate_integration_state(state)
        if state.get("pending") is not None:
            raise IntegrationError(
                "GNOME integration has an unfinished transaction; run uninstall"
            )
        managed = _managed_uris(state)
        if state.get("original") is None and any(
            prior.get(key) not in managed for key in URI_KEYS
        ):
            state["original"] = prior

    if (
        prior == desired
        and loaded is not None
        and state.get("last_applied") == desired
        and uri in _managed_uris(state)
    ):
        if _compact_managed_uris(state, newest=uri):
            _write_integration_state(state_path, state)
        return
    if prior == desired:
        state["last_applied"] = desired
        _compact_managed_uris(state, newest=uri)
        _write_integration_state(state_path, state)
        return

    state["pending"] = {"desired": desired, "prior": prior}
    _write_integration_state(state_path, state)
    try:
        set_background_settings(desired, runner=runner)
    except IntegrationError as error:
        rolled_back = _rollback_settings(prior, runner=runner)
        if rolled_back:
            state.pop("pending", None)
            if state.get("managed_uris") or state.get("last_applied") is not None:
                _write_integration_state(state_path, state)
            else:
                _unlink_integration_state(state_path)
        detail = "rollback succeeded" if rolled_back else "rollback was incomplete"
        raise IntegrationError(f"{error}; {detail}") from error

    state["last_applied"] = desired
    _compact_managed_uris(state, newest=uri)
    state.pop("pending", None)
    try:
        _write_integration_state(state_path, state)
    except IntegrationError as error:
        rolled_back = _rollback_settings(prior, runner=runner)
        detail = "rollback succeeded" if rolled_back else "rollback was incomplete"
        raise IntegrationError(f"{error}; {detail}") from error


def _managed_uris(state: dict[str, object]) -> set[str]:
    managed = set(state.get("managed_uris", []))
    managed.update(_settings_uris(state.get("last_applied")))
    pending = state.get("pending")
    if isinstance(pending, dict):
        desired = pending.get("desired")
        if isinstance(desired, dict):
            for key in URI_KEYS:
                value = desired.get(key)
                if isinstance(value, str):
                    managed.add(value)
    return managed


def restore_background(
    *,
    runner: Runner = subprocess.run,
    state_directory: Path | None = None,
) -> bool:
    state_dir = state_directory or integration_state_directory()
    state_path = state_dir / "gnome-background.json"
    state = _read_integration_state(state_path)
    if state is None:
        return False
    _validate_integration_state(state)
    managed = _managed_uris(state)
    if not managed:
        if state.get("version") == 1 and state.get("pending") is None:
            _unlink_integration_state(state_path)
            return False
        raise IntegrationError("GNOME integration state has no managed wallpaper")
    original = state.get("original")
    current = get_background_settings(runner=runner)
    restore: dict[str, str] = {}
    if isinstance(original, dict):
        for key in URI_KEYS:
            original_value = original.get(key)
            if (
                current.get(key) in managed
                and isinstance(original_value, str)
                and original_value not in managed
            ):
                restore[key] = original_value
        original_option = original.get("picture-options")
        last_applied = state.get("last_applied")
        managed_option = (
            last_applied.get("picture-options")
            if isinstance(last_applied, dict)
            else None
        )
        if managed_option is None:
            pending = state.get("pending")
            desired = pending.get("desired") if isinstance(pending, dict) else None
            if isinstance(desired, dict):
                managed_option = desired.get("picture-options")
        uris_resolved = all(
            isinstance(original.get(key), str)
            and (
                key in restore
                or current.get(key) == original.get(key)
            )
            for key in URI_KEYS
        )
        if (
            uris_resolved
            and isinstance(original_option, str)
            and current.get("picture-options") == managed_option
        ):
            restore["picture-options"] = original_option
    if restore:
        set_background_settings(restore, runner=runner)
        current = get_background_settings(runner=runner)
    if not any(current.get(key) in managed for key in URI_KEYS):
        _unlink_integration_state(state_path)
    return bool(restore)


def _paths_from_settings(settings: dict[str, str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for key in URI_KEYS:
        parsed = urlparse(settings.get(key, ""))
        if parsed.scheme == "file" and parsed.netloc in {"", "localhost"}:
            path = Path(unquote(parsed.path))
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def current_background_paths(
    *, runner: Runner = subprocess.run
) -> tuple[Path, ...]:
    return _paths_from_settings(get_background_settings(runner=runner))


def managed_output_paths(
    *,
    state_directory: Path | None = None,
) -> tuple[Path, ...]:
    state_dir = state_directory or integration_state_directory()
    state = _read_integration_state(state_dir / "gnome-background.json")
    if state is None:
        return ()
    _validate_integration_state(state)
    settings = {key: "" for key in KEYS}
    uris = sorted(_managed_uris(state))
    paths: list[Path] = []
    for uri in uris:
        settings["picture-uri"] = uri
        for path in _paths_from_settings(settings):
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def protected_output_paths(
    *,
    state_directory: Path | None = None,
) -> tuple[Path, ...]:
    state_dir = state_directory or integration_state_directory()
    state = _read_integration_state(state_dir / "gnome-background.json")
    if state is None:
        return ()
    _validate_integration_state(state)
    uris: set[str] = set()
    last_applied = state.get("last_applied")
    if isinstance(last_applied, dict):
        for key in URI_KEYS:
            value = last_applied.get(key)
            if isinstance(value, str):
                uris.add(value)
    pending = state.get("pending")
    if isinstance(pending, dict):
        desired = pending.get("desired")
        if isinstance(desired, dict):
            for key in URI_KEYS:
                value = desired.get(key)
                if isinstance(value, str):
                    uris.add(value)
    original = state.get("original")
    if isinstance(original, dict):
        for key in URI_KEYS:
            value = original.get(key)
            if isinstance(value, str):
                uris.add(value)
    paths: list[Path] = []
    settings = {key: "" for key in KEYS}
    for uri in sorted(uris):
        settings["picture-uri"] = uri
        for path in _paths_from_settings(settings):
            if path not in paths:
                paths.append(path)
    return tuple(paths)
