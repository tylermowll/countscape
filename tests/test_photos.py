from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_image

from countscape.errors import PhotoError
from countscape.photos import photo_bucket, scan_photo_pool, select_photo


def test_missing_empty_and_invalid_pools(tmp_path: Path) -> None:
    with pytest.raises(PhotoError, match="does not exist"):
        scan_photo_pool(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(PhotoError, match="no JPG"):
        scan_photo_pool(empty)
    (empty / "broken.jpg").write_text("not an image", encoding="utf-8")
    with pytest.raises(PhotoError, match="unreadable image"):
        scan_photo_pool(empty)


def test_portrait_landscape_and_transparent_images_are_accepted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "photos"
    make_image(root / "landscape.jpg", (1200, 800))
    make_image(root / "portrait.png", (800, 1200))
    make_image(root / "small.png", (10, 10))
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.iterdir()
    }
    pool = scan_photo_pool(root)
    assert len(pool.photos) == 3
    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.iterdir()
    }
    assert after == before


def test_selection_is_stable_independent_and_never_repeats(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    for index in range(4):
        make_image(root / f"{index}.png", color=(index * 40, 20, 100))
    pool = scan_photo_pool(root)
    sequence_a = [select_photo(pool, bucket, "machine-a") for bucket in range(12)]
    sequence_again = [select_photo(pool, bucket, "machine-a") for bucket in range(12)]
    seeded_sequences = {
        tuple(select_photo(pool, bucket, f"machine-{seed}") for bucket in range(12))
        for seed in range(12)
    }
    assert sequence_a == sequence_again
    assert len(seeded_sequences) > 1
    assert all(
        left != right for left, right in zip(sequence_a, sequence_a[1:], strict=False)
    )


def test_bucket_changes_only_on_ten_minute_boundary() -> None:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    first = photo_bucket(start, 600)
    assert photo_bucket(start + timedelta(minutes=9, seconds=59), 600) == first
    assert photo_bucket(start + timedelta(minutes=10), 600) == first + 1


def test_bucket_supports_five_second_test_interval() -> None:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    first = photo_bucket(start, 5)
    assert photo_bucket(start + timedelta(seconds=4), 5) == first
    assert photo_bucket(start + timedelta(seconds=5), 5) == first + 1


@pytest.mark.parametrize("interval", (0, -1, 1.5, True))
def test_bucket_rejects_invalid_second_intervals(interval: object) -> None:
    with pytest.raises(PhotoError, match="positive integer"):
        photo_bucket(datetime(2026, 1, 1, tzinfo=UTC), interval)  # type: ignore[arg-type]
