from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from countscape.errors import ConfigError


@dataclass(frozen=True, slots=True)
class DateState:
    local_date: date
    text: str


def current_date_state(now: datetime, timezone: ZoneInfo) -> DateState:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ConfigError("current time must be timezone-aware")
    if not isinstance(timezone, ZoneInfo):
        raise ConfigError("date display requires an IANA timezone")
    local = now.astimezone(timezone)
    return DateState(
        local_date=local.date(),
        text=f"{local:%A}, {local:%B} {local.day}, {local.year}",
    )
