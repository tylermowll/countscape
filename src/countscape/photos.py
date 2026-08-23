from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from PIL import Image

from countscape.errors import PhotoError

SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
# This accepts 8K and common 48 MP photos while limiting one RGBA expansion to
# about 191 MiB before decoder and resampling overhead. It is intentionally not
# configurable so every source-photo entry point has the same safety boundary.
MAX_SOURCE_IMAGE_PIXELS = 50_000_000


@dataclass(frozen=True, slots=True)
class PhotoPool:
    root: Path
    photos: tuple[Path, ...]
    signature: str


def _source_limit_error(path: Path, *, size: tuple[int, int] | None = None) -> str:
    detail = f" ({size[0]}x{size[1]})" if size is not None else ""
    return (
        f"source image exceeds the {MAX_SOURCE_IMAGE_PIXELS:,}-pixel limit: "
        f"{path.name}{detail}"
    )


@contextmanager
def open_source_image(path: Path) -> Iterator[Image.Image]:
    """Open a source photo behind Countscape's fixed decode-safety boundary."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise PhotoError(
                        f"unreadable image: {path.name}: invalid image dimensions"
                    )
                if width * height > MAX_SOURCE_IMAGE_PIXELS:
                    raise PhotoError(_source_limit_error(path, size=(width, height)))
                yield image
    except PhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise PhotoError(_source_limit_error(path)) from error
    except (EOFError, OSError, SyntaxError, ValueError) as error:
        detail = str(error) or type(error).__name__
        raise PhotoError(f"unreadable image: {path.name}: {detail}") from error


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
        with open_source_image(path) as image:
            image.verify()
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
