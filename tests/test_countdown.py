from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from countscape.countdown import calculate_countdown
from countscape.errors import ConfigError

TARGET = datetime(2027, 6, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            TARGET - timedelta(days=2, hours=3, minutes=4),
            "2 days · 3 hours · 4 minutes",
        ),
        (TARGET - timedelta(minutes=1), "1 minute"),
        (TARGET - timedelta(seconds=1), "1 minute"),
    ],
)
def test_positive_countdown_rounds_up(now: datetime, expected: str) -> None:
    state = calculate_countdown(now, TARGET, "It's here!")
    assert not state.arrived
    assert state.text == expected


@pytest.mark.parametrize(
    "now",
    [
        TARGET,
        TARGET + timedelta(seconds=1),
        TARGET + timedelta(days=30),
    ],
)
def test_arrival_boundary_never_goes_negative(now: datetime) -> None:
    state = calculate_countdown(now, TARGET, "It's here!")
    assert state.arrived
    assert state.remaining_minutes == 0
    assert state.text == "It's here!"


def test_same_instant_in_another_zone() -> None:
    now_utc = (TARGET - timedelta(hours=1)).astimezone(UTC)
    assert (
        calculate_countdown(now_utc, TARGET, "It's here!").text
        == "1 hour · 0 minutes"
    )


def test_dst_and_clock_corrections_are_reflected() -> None:
    zone = ZoneInfo("America/New_York")
    before_dst = datetime(2026, 3, 8, 1, 59, tzinfo=zone)
    after_dst = datetime(2026, 3, 8, 3, 1, tzinfo=zone)
    target = datetime(2026, 3, 8, 4, 0, tzinfo=zone)
    assert calculate_countdown(before_dst, target, "It's here!").remaining_minutes == 61
    assert calculate_countdown(after_dst, target, "It's here!").remaining_minutes == 59


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ConfigError, match="timezone-aware"):
        calculate_countdown(datetime(2026, 1, 1), TARGET, "It's here!")
