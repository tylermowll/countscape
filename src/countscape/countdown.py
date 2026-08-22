from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil

from countscape.errors import ConfigError


@dataclass(frozen=True, slots=True)
class CountdownState:
    arrived: bool
    text: str
    remaining_minutes: int


def _unit(value: int, singular: str) -> str:
    suffix = singular if value == 1 else f"{singular}s"
    return f"{value} {suffix}"


def calculate_countdown(
    now: datetime,
    target: datetime,
    after_arrival_message: str,
) -> CountdownState:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ConfigError("current time must be timezone-aware")
    if target.tzinfo is None or target.utcoffset() is None:
        raise ConfigError("event target must be timezone-aware")

    remaining_seconds = (target.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
    if remaining_seconds <= 0:
        return CountdownState(
            arrived=True,
            text=after_arrival_message,
            remaining_minutes=0,
        )

    total_minutes = ceil(remaining_seconds / 60)
    days, minute_remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(minute_remainder, 60)
    parts = [_unit(days, "day")] if days else []
    if days or hours:
        parts.append(_unit(hours, "hour"))
    parts.append(_unit(minutes, "minute"))
    return CountdownState(
        arrived=False,
        text=" · ".join(parts),
        remaining_minutes=total_minutes,
    )
