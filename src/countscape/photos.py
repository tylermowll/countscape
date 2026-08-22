from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from countscape.errors import PhotoError

SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


@dataclass(frozen=True, slots=True)
class PhotoPool:
    root: Path
    photos: tuple[Path, ...]
    signature: str


def scan_photo_pool(root: Path) -> PhotoPool:
    if not root.exists():
        raise PhotoError(f"photo directory does not exist: {root}")
    if not root.is_dir():
        raise PhotoError(f"photo path is not a directory: {root}")

    candidates = tuple(
        sorted(
            (
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
            ),
            key=lambda path: path.name.casefold(),
        )
    )
    if not candidates:
        raise PhotoError(f"photo directory has no JPG, JPEG, or PNG images: {root}")

    digest = sha256()
    for path in candidates:
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as error:
            raise PhotoError(f"unreadable image: {path.name}: {error}") from error
        stat = path.stat()
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode())
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(b"\0")
    return PhotoPool(root=root, photos=candidates, signature=digest.hexdigest())


def photo_bucket(now: datetime, change_seconds: int) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise PhotoError("photo selection time must be timezone-aware")
    if (
        not isinstance(change_seconds, int)
        or isinstance(change_seconds, bool)
        or change_seconds <= 0
    ):
        raise PhotoError("photo change interval seconds must be a positive integer")
    return int(now.timestamp()) // change_seconds


def select_photo(pool: PhotoPool, bucket: int, seed: str) -> Path:
    if not seed:
        raise PhotoError("selection seed must not be empty")
    ranked = sorted(
        pool.photos,
        key=lambda path: sha256(
            (
                seed
                + "\0"
                + pool.signature
                + "\0"
                + path.relative_to(pool.root).as_posix()
            ).encode()
        ).digest(),
    )
    return ranked[bucket % len(ranked)]
