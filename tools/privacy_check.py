from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATH = re.compile(r"(?:/home|/Users)/[^/\s]+", re.IGNORECASE)
PERSONAL_EMAIL = re.compile(
    r"\b[\w.+-]+@(?:gmail|hotmail|icloud|outlook|yahoo)\.[a-z]{2,}\b",
    re.IGNORECASE,
)
LEGACY_NAME = re.compile("desktop" + r"[-_ ]countdown", re.IGNORECASE)
SECRET_PATTERNS = (
    re.compile("BEGIN " + r"[A-Z ]*PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile("github" + r"_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:password|api[_-]?key)\s*[:=]", re.IGNORECASE),
)
FORBIDDEN_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".webp",
    ".mov",
    ".mp4",
    ".pyc",
    ".whl",
    ".tar.gz",
)


def candidate_paths() -> tuple[Path, ...]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        ROOT / raw.decode("utf-8")
        for raw in result.stdout.split(b"\0")
        if raw
    )


def scan() -> list[str]:
    violations: list[str] = []
    for path in candidate_paths():
        relative = path.relative_to(ROOT)
        lowered = relative.as_posix().lower()
        if path.is_symlink():
            violations.append(f"{relative}: symbolic links are not allowed")
            continue
        if lowered.endswith(FORBIDDEN_SUFFIXES):
            violations.append(f"{relative}: unexpected media or build artifact")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            violations.append(f"{relative}: unexpected binary file")
            continue
        if PRIVATE_PATH.search(text):
            violations.append(f"{relative}: absolute user-home path")
        if PERSONAL_EMAIL.search(text):
            violations.append(f"{relative}: personal email address")
        if LEGACY_NAME.search(text):
            violations.append(f"{relative}: legacy project name")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                violations.append(f"{relative}: possible secret")
    return violations


def main() -> int:
    violations = scan()
    if violations:
        print("Privacy check failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("Privacy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
