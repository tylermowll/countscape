from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)")
HTML_LINK = re.compile(
    r"<(?:a|img)\b[^>]*\b(?:href|src)\s*=\s*(['\"])(.*?)\1",
    re.IGNORECASE,
)
HTML_ANCHOR = re.compile(
    r"<(?:a|[^>]+)\b(?:id|name)\s*=\s*(['\"])(.*?)\1",
    re.IGNORECASE,
)
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
LINE_FRAGMENT = re.compile(r"L(?P<start>\d+)(?:-L(?P<end>\d+))?", re.IGNORECASE)
INLINE_CODE = re.compile(r"`+[^`]*`+")


def markdown_paths() -> tuple[Path, ...]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.md",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Markdown files could not be enumerated")
    return tuple(
        sorted(
            ROOT / raw.decode("utf-8", errors="surrogateescape")
            for raw in result.stdout.split(b"\0")
            if raw
        )
    )


def _slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith(("P", "C"))
        or character in {"-", "_"}
    )
    return re.sub(r"\s+", "-", text)


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    fence_marker = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fenced:
                fenced = True
                fence_marker = marker
            elif marker == fence_marker:
                fenced = False
            continue
        if fenced:
            continue
        for match in HTML_ANCHOR.finditer(line):
            anchors.add(unquote(match.group(2)).lower())
        match = HEADING.match(line)
        if match is None:
            continue
        base = _slug(match.group(1))
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _targets(path: Path) -> tuple[tuple[int, str], ...]:
    targets: list[tuple[int, str]] = []
    fenced = False
    fence_marker = ""
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fenced:
                fenced = True
                fence_marker = marker
            elif marker == fence_marker:
                fenced = False
            continue
        if fenced:
            continue
        searchable = INLINE_CODE.sub("", line)
        targets.extend(
            (line_number, match.group(1).strip("<>"))
            for match in INLINE_LINK.finditer(searchable)
        )
        reference = REFERENCE_LINK.match(searchable)
        if reference is not None:
            targets.append((line_number, reference.group(1).strip("<>")))
        targets.extend(
            (line_number, match.group(2)) for match in HTML_LINK.finditer(searchable)
        )
    return tuple(targets)


def _local_target(source: Path, raw_target: str) -> tuple[Path, str] | None:
    if not raw_target or "${{" in raw_target or raw_target.startswith("//"):
        return None
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = unquote(parsed.path)
    if raw_path.startswith("/"):
        target = ROOT / raw_path.lstrip("/")
    elif raw_path:
        target = source.parent / raw_path
    else:
        target = source
    return target.resolve(), unquote(parsed.fragment)


def _valid_fragment(target: Path, fragment: str) -> bool:
    if not fragment:
        return True
    if target.suffix.lower() == ".md":
        return fragment.lower() in markdown_anchors(target)
    match = LINE_FRAGMENT.fullmatch(fragment)
    if match is None or not target.is_file():
        return False
    lines = len(target.read_bytes().splitlines())
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    return 1 <= start <= end <= lines


def check_links() -> tuple[list[str], int]:
    violations: list[str] = []
    paths = markdown_paths()
    for source in paths:
        relative = source.relative_to(ROOT).as_posix()
        for line_number, raw_target in _targets(source):
            resolved = _local_target(source, raw_target)
            if resolved is None:
                continue
            target, fragment = resolved
            if not target.is_relative_to(ROOT):
                violations.append(f"{relative}:{line_number}: link escapes repository")
                continue
            if target.is_symlink() or not target.exists():
                violations.append(
                    f"{relative}:{line_number}: local link target is missing"
                )
                continue
            if not _valid_fragment(target, fragment):
                violations.append(
                    f"{relative}:{line_number}: local link anchor is missing"
                )
    return sorted(set(violations)), len(paths)


def main() -> int:
    try:
        violations, count = check_links()
    except OSError, RuntimeError, UnicodeDecodeError:
        print("Markdown link check failed: repository files could not be inspected.")
        return 1
    if violations:
        print("Markdown link check failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"Markdown link check passed ({count} files; external links skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
