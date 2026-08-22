from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

import pytest

from countscape.config import DisplayConfig
from countscape.errors import DisplayError
from countscape.models import DisplayLayout, LogicalMonitor, PhysicalMonitor
from countscape.mutter import DISPLAY_SIGNATURE, discover_layout, parse_current_state


def _mode(*, current: object = True, width: object = 800) -> list[object]:
    return [
        "800x600",
        width,
        600,
        60.0,
        1.0,
        [1.0],
        {"is-current": {"type": "b", "data": current}},
    ]


def _monitor(*, modes: list[object] | None = None) -> list[object]:
    return [
        ["EXAMPLE-1", "vendor", "product", "serial"],
        [_mode()] if modes is None else modes,
        {},
    ]


def _logical(*, primary: object = True, connector: str = "EXAMPLE-1") -> list[object]:
    return [
        0,
        0,
        1.0,
        0,
        primary,
        [[connector, "vendor", "product", "serial"]],
        {},
    ]


def _payload(
    *,
    monitors: list[object] | None = None,
    logical: list[object] | None = None,
    properties: object | None = None,
    data: object | None = None,
) -> str:
    document = {
        "type": DISPLAY_SIGNATURE,
        "data": (
            [
                1,
                [_monitor()] if monitors is None else monitors,
                [_logical()] if logical is None else logical,
                {"layout-mode": {"type": "u", "data": 1}}
                if properties is None
                else properties,
            ]
            if data is None
            else data
        ),
    }
    return json.dumps(document)


def _fallback() -> DisplayLayout:
    return DisplayLayout(
        monitors=(
            LogicalMonitor(
                x=0,
                y=0,
                scale=1,
                transform=0,
                primary=True,
                connectors=("FALLBACK-1",),
                physical=(PhysicalMonitor("FALLBACK-1", 1024, 768),),
            ),
        ),
        layout_mode=1,
        source="profile:fallback",
    )


def _auto(*, fallback: bool = False) -> DisplayConfig:
    layout = _fallback()
    return DisplayConfig(
        mode="auto",
        fallback_profile="fallback" if fallback else None,
        profiles={"fallback": layout} if fallback else {},
    )


def test_parse_current_state_accepts_unwrapped_variants() -> None:
    mode = _mode()
    mode[6] = {"is-current": True}
    layout = parse_current_state(
        _payload(monitors=[_monitor(modes=[mode])], properties={"layout-mode": 1})
    )

    assert layout.monitors[0].physical[0] == PhysicalMonitor("EXAMPLE-1", 800, 600)
    assert layout.layout_mode == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ("[]", "must be an object"),
        (_payload(data=[1]), "incomplete"),
        (_payload(monitors=[[]]), "invalid Mutter monitor data"),
        (
            _payload(monitors=[_monitor(modes=[["short"]])]),
            "invalid Mutter monitor data",
        ),
        (
            _payload(monitors=[_monitor(modes=[_mode(width="not-an-integer")])]),
            "invalid Mutter monitor data",
        ),
        (_payload(logical=[_logical(primary=1)]), "primary status"),
        (
            _payload(logical=[_logical(connector="INACTIVE-1")]),
            "without an active mode",
        ),
        (_payload(properties=[]), "invalid Mutter layout mode"),
        (
            _payload(properties={"layout-mode": {"type": "u"}}),
            "invalid Mutter layout mode",
        ),
    ),
)
def test_parse_current_state_rejects_malformed_structures(
    payload: str,
    message: str,
) -> None:
    with pytest.raises(DisplayError, match=message):
        parse_current_state(payload)


def test_parse_current_state_rejects_logical_connector_without_current_mode() -> None:
    payload = _payload(monitors=[_monitor(modes=[_mode(current=False)])])
    with pytest.raises(DisplayError, match="without an active mode"):
        parse_current_state(payload)


def test_profile_mode_never_invokes_mutter() -> None:
    fallback = _fallback()

    def unexpected_runner(*_args: object, **_kwargs: object) -> None:
        pytest.fail("profile mode must not invoke busctl")

    result = discover_layout(
        DisplayConfig(
            mode="profile",
            fallback_profile="fallback",
            profiles={"fallback": fallback},
        ),
        runner=unexpected_runner,  # type: ignore[arg-type]
    )

    assert result is fallback


def test_discover_layout_passes_adapter_contract_and_parses_success() -> None:
    calls: list[tuple[object, ...]] = []
    command = ("synthetic-busctl", "current-state")

    def runner(
        received: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((received, kwargs))
        return subprocess.CompletedProcess(command, 0, _payload(), "")

    layout = discover_layout(_auto(), runner=runner, command=command)

    assert layout.source == "mutter"
    assert calls == [
        (
            command,
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 8,
            },
        )
    ]


@pytest.mark.parametrize(
    "runner",
    (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bus missing")),
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("busctl", 8)
        ),
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "not json", ""),
    ),
)
def test_discovery_failures_use_explicit_fallback(
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    config = _auto(fallback=True)
    assert discover_layout(config, runner=runner) is config.profiles["fallback"]


def test_discovery_wraps_process_errors_and_reports_empty_stderr() -> None:
    def raises_os_error(*_args: object, **_kwargs: object) -> None:
        raise OSError("bus missing")

    with pytest.raises(DisplayError, match="bus missing"):
        discover_layout(_auto(), runner=raises_os_error)  # type: ignore[arg-type]

    def failed_runner(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 7, "", "")

    with pytest.raises(DisplayError, match="exit 7"):
        discover_layout(_auto(), runner=failed_runner)
