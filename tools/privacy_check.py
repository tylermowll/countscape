from __future__ import annotations

import argparse
import hashlib
import re
import stat
import subprocess
import tarfile
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000

PRIVATE_PATH = re.compile(
    r"(?:/(?:ho[m]e|U[s]ers|var/ho[m]e)/[^/\s]+|"
    r"/mnt/[a-z]/U[s]ers/[^/\s]+|"
    r"[a-z]:[\\/]U[s]ers[\\/][^\\/\s]+)",
    re.IGNORECASE,
)
EMAIL_ADDRESS = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
NONPERSONAL_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "noreply.github.com",
    "users.noreply.github.com",
}
NONPERSONAL_EMAIL_ADDRESSES = {
    "noreply@github.com",
    "support@github.com",
}
LEGACY_NAME = re.compile("desktop" + r"[-_ ]countdown", re.IGNORECASE)
SECRET_PATTERNS = (
    re.compile("BEGIN " + r"[A-Z ]*PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile("github" + r"_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:password|api[_-]?key)\s*[:=]", re.IGNORECASE),
)
FORBIDDEN_SUFFIXES = (
    ".3gp",
    ".arw",
    ".avi",
    ".avif",
    ".bmp",
    ".bz2",
    ".cr2",
    ".dng",
    ".flac",
    ".gif",
    ".gz",
    ".heic",
    ".ico",
    ".jpg",
    ".jpeg",
    ".jxl",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mp3",
    ".nef",
    ".ogg",
    ".pbm",
    ".pdf",
    ".pgm",
    ".png",
    ".pnm",
    ".ppm",
    ".pyc",
    ".svg",
    ".svgz",
    ".tar.gz",
    ".tgz",
    ".tif",
    ".tiff",
    ".wav",
    ".webm",
    ".webp",
    ".whl",
    ".xbm",
    ".xpm",
    ".xz",
    ".zip",
)

# These are the reviewed public-media exceptions. The exact-byte guards also
# fix their sizes, dimensions, encodings, and stripped metadata; changing either
# illustration requires an explicit review and digest update.
APPROVED_MEDIA = {
    "docs/assets/countscape-hero.webp": {
        "sha256": "99fd4ca74c6ff6a18c2fb2be4e6dbe1d8250f577550f94a975717a8326e1392b",
        "size": 60_602,
    },
    "docs/assets/countscape-social-preview.png": {
        "sha256": "7b7174c232a778a43483ed6e34a183c348dc7ec7b33510d23fe0356bf199bf40",
        "size": 911_564,
    },
}


def _run_git(arguments: list[str], *, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=input_data,
    )
    if result.returncode != 0:
        raise RuntimeError("Git history could not be inspected")
    return result.stdout


def candidate_paths() -> tuple[Path, ...]:
    output = _run_git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    return tuple(
        ROOT / raw.decode("utf-8", errors="surrogateescape")
        for raw in output.split(b"\0")
        if raw
    )


def _text_findings(text: str) -> tuple[str, ...]:
    findings: list[str] = []
    if PRIVATE_PATH.search(text):
        findings.append("absolute user-home path")
    if any(
        match.group(0).lower() not in NONPERSONAL_EMAIL_ADDRESSES
        and match.group(0).rsplit("@", 1)[1].lower() not in NONPERSONAL_EMAIL_DOMAINS
        for match in EMAIL_ADDRESS.finditer(text)
    ):
        findings.append("personal email address")
    if LEGACY_NAME.search(text):
        findings.append("legacy project name")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        findings.append("possible secret")
    return tuple(findings)


def _approved_media(repository_path: str, data: bytes) -> bool:
    expected = APPROVED_MEDIA.get(repository_path)
    if expected is None or len(data) != expected["size"]:
        return False
    return hashlib.sha256(data).hexdigest() == expected["sha256"]


def _scan_repository_bytes(repository_path: str, data: bytes) -> list[str]:
    label = repository_path
    if len(data) > MAX_ENTRY_BYTES:
        return [f"{label}: file exceeds the privacy-audit size limit"]

    if label.lower().endswith(FORBIDDEN_SUFFIXES):
        if _approved_media(label, data):
            return []
        return [f"{label}: unexpected media or build artifact"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{label}: unexpected binary file"]
    return [f"{label}: {finding}" for finding in _text_findings(text)]


def _scan_repository_entry(path: Path) -> list[str]:
    label = path.relative_to(ROOT).as_posix()
    if path.is_symlink():
        return [f"{label}: symbolic links are not allowed"]
    if not path.exists():
        # Git continues to enumerate a tracked path after its deletion is
        # staged. The index scanner separately inspects every surviving staged
        # blob, so an absent worktree entry has no bytes left to inspect.
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return [f"{label}: file could not be inspected"]
    return _scan_repository_bytes(label, data)


def scan() -> list[str]:
    """Scan tracked and non-ignored worktree files."""
    violations: list[str] = []
    for path in candidate_paths():
        violations.extend(_scan_repository_entry(path))
    return violations


def scan_staged() -> list[str]:
    """Scan the exact regular-file blobs staged in the Git index."""
    violations: list[str] = []
    output = _run_git(["ls-files", "--cached", "--stage", "-z"])
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_id, raw_stage = metadata.split(b" ", 2)
            repository_path = raw_path.decode("utf-8", errors="surrogateescape")
            stage = int(raw_stage)
        except ValueError, UnicodeDecodeError:
            violations.append("Git index contains an uninspectable entry")
            continue
        if stage != 0:
            violations.append(f"{repository_path}: unresolved staged entry")
            continue
        if mode == b"120000":
            violations.append(f"{repository_path}: symbolic links are not allowed")
            continue
        if mode == b"160000":
            violations.append(f"{repository_path}: Git submodules are not allowed")
            continue
        if mode not in {b"100644", b"100755"} or not object_id.strip(b"0"):
            violations.append(f"{repository_path}: unsupported staged entry")
            continue
        try:
            data = _run_git(["cat-file", "blob", object_id.decode("ascii")])
        except RuntimeError, UnicodeDecodeError:
            violations.append(f"{repository_path}: staged blob could not be inspected")
            continue
        violations.extend(_scan_repository_bytes(repository_path, data))
    return violations


def _history_paths() -> dict[str, set[str]]:
    paths: dict[str, set[str]] = defaultdict(set)
    treeishes = set(_run_git(["rev-list", "--all", "HEAD"]).splitlines())
    refs = _run_git(
        [
            "for-each-ref",
            "--format=%(objectname)%00%(objecttype)%00%(*objectname)%00%(*objecttype)",
        ]
    )
    for record in refs.splitlines():
        object_id, object_type, peeled_id, peeled_type = record.split(b"\0")
        if object_type == b"tree":
            treeishes.add(object_id)
        if peeled_type == b"tree":
            treeishes.add(peeled_id)
    for treeish in sorted(treeishes):
        tree = _run_git(
            ["ls-tree", "-rz", "-r", "--full-tree", treeish.decode("ascii")]
        )
        for record in tree.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            _mode, object_type, object_id = metadata.split(b" ", 2)
            if object_type == b"blob":
                paths[object_id.decode("ascii")].add(
                    raw_path.decode("utf-8", errors="surrogateescape")
                )
    return paths


def _history_objects() -> tuple[tuple[str, str, int], ...]:
    object_ids = sorted(
        set(
            _run_git(
                ["rev-list", "--objects", "--all", "HEAD", "--no-object-names"]
            ).splitlines()
        )
    )
    if not object_ids:
        return ()
    checks = _run_git(
        ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        input_data=b"\n".join(object_ids) + b"\n",
    )
    objects: list[tuple[str, str, int]] = []
    for line in checks.splitlines():
        object_id, object_type, raw_size = line.decode("ascii").split()
        objects.append((object_id, object_type, int(raw_size)))
    return tuple(sorted(objects))


def scan_history() -> list[str]:
    """Scan every object reachable from every local ref without printing content."""
    violations: list[str] = []
    paths_by_object = _history_paths()
    for object_id, object_type, size in _history_objects():
        if object_type == "tree":
            continue
        label = f"history {object_type} {object_id}"
        if size > MAX_ENTRY_BYTES:
            violations.append(f"{label}: object exceeds the privacy-audit size limit")
            continue
        data = _run_git(["cat-file", object_type, object_id])
        object_paths = paths_by_object.get(object_id, set())
        forbidden_paths = {
            path for path in object_paths if path.lower().endswith(FORBIDDEN_SUFFIXES)
        }
        if forbidden_paths and not (
            len(object_paths) == 1
            and len(forbidden_paths) == 1
            and _approved_media(next(iter(forbidden_paths)), data)
        ):
            violations.append(f"{label}: unexpected media or build artifact")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if not (
                len(object_paths) == 1
                and _approved_media(next(iter(object_paths)), data)
            ):
                violations.append(f"{label}: unexpected binary object")
            continue
        violations.extend(f"{label}: {finding}" for finding in _text_findings(text))
    return violations


def _safe_member_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    without_trailing_slash = name[:-1] if name.endswith("/") else name
    raw_parts = without_trailing_slash.split("/")
    if not without_trailing_slash or any(part in {"", ".", ".."} for part in raw_parts):
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and not (path.parts and path.parts[0].endswith(":"))
        and not any(
            unicodedata.category(character).startswith("C") for character in name
        )
    )


def _artifact_repository_path(artifact: Path, member_name: str) -> str:
    parts = PurePosixPath(member_name).parts
    if artifact.name.endswith(".tar.gz") and len(parts) > 1:
        return PurePosixPath(*parts[1:]).as_posix()
    return PurePosixPath(*parts).as_posix()


def _member_label(artifact: Path, member_name: str) -> str:
    identifier = hashlib.sha256(member_name.encode("utf-8")).hexdigest()[:16]
    return f"artifact {artifact.name} member {identifier}"


def _scan_archive_bytes(
    artifact: Path,
    member_name: str,
    data: bytes,
) -> list[str]:
    label = _member_label(artifact, member_name)
    repository_path = _artifact_repository_path(artifact, member_name)
    if repository_path.lower().endswith(FORBIDDEN_SUFFIXES):
        if _approved_media(repository_path, data):
            return []
        return [f"{label}: unexpected media or build artifact"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{label}: unexpected binary member"]
    return [f"{label}: {finding}" for finding in _text_findings(text)]


def _scan_zip(artifact: Path) -> list[str]:
    violations: list[str] = []
    total_size = 0
    seen: set[str] = set()
    with zipfile.ZipFile(artifact) as archive:
        members = sorted(archive.infolist(), key=lambda member: member.filename)
        if len(members) > MAX_ARCHIVE_MEMBERS:
            return [f"artifact {artifact.name}: archive has too many members"]
        for member in members:
            label = _member_label(artifact, member.filename)
            if member.filename in seen:
                violations.append(f"{label}: duplicate archive member")
                continue
            seen.add(member.filename)
            if not _safe_member_name(member.filename):
                violations.append(f"{label}: unsafe archive member path")
                continue
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                violations.append(f"{label}: symbolic links are not allowed")
                continue
            if member.is_dir():
                continue
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                violations.append(f"{label}: special files are not allowed")
                continue
            if member.flag_bits & 0x1:
                violations.append(f"{label}: encrypted archive member")
                continue
            total_size += member.file_size
            if member.file_size > MAX_ENTRY_BYTES or total_size > MAX_ARCHIVE_BYTES:
                violations.append(f"{label}: archive size limit exceeded")
                continue
            try:
                with archive.open(member) as extracted:
                    data = extracted.read(MAX_ENTRY_BYTES + 1)
            except OSError, RuntimeError, zipfile.BadZipFile:
                violations.append(f"{label}: archive member could not be inspected")
                continue
            if len(data) != member.file_size:
                violations.append(f"{label}: archive member size is inconsistent")
                continue
            violations.extend(_scan_archive_bytes(artifact, member.filename, data))
    return violations


def _scan_tar(artifact: Path) -> list[str]:
    violations: list[str] = []
    total_size = 0
    seen: set[str] = set()
    expected_root = artifact.name.removesuffix(".tar.gz")
    with tarfile.open(artifact, mode="r:gz") as archive:
        members = sorted(archive.getmembers(), key=lambda member: member.name)
        if len(members) > MAX_ARCHIVE_MEMBERS:
            return [f"artifact {artifact.name}: archive has too many members"]
        for member in members:
            label = _member_label(artifact, member.name)
            if member.name in seen:
                violations.append(f"{label}: duplicate archive member")
                continue
            seen.add(member.name)
            if not _safe_member_name(member.name):
                violations.append(f"{label}: unsafe archive member path")
                continue
            if PurePosixPath(member.name).parts[0] != expected_root:
                violations.append(f"{label}: unexpected source-distribution root")
                continue
            if member.isdir():
                continue
            if not member.isfile():
                violations.append(f"{label}: links and special files are not allowed")
                continue
            total_size += member.size
            if member.size > MAX_ENTRY_BYTES or total_size > MAX_ARCHIVE_BYTES:
                violations.append(f"{label}: archive size limit exceeded")
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                violations.append(f"{label}: archive member could not be inspected")
                continue
            try:
                data = extracted.read(MAX_ENTRY_BYTES + 1)
            except OSError:
                violations.append(f"{label}: archive member could not be inspected")
                continue
            violations.extend(_scan_archive_bytes(artifact, member.name, data))
    return violations


def scan_artifacts(artifacts: tuple[Path, ...]) -> list[str]:
    violations: list[str] = []
    absolute = (path.expanduser().absolute() for path in artifacts)
    for artifact in sorted(absolute, key=lambda path: path.name):
        label = f"artifact {artifact.name}"
        if artifact.is_symlink() or not artifact.is_file():
            violations.append(f"{label}: artifact is missing or is a symbolic link")
            continue
        try:
            if artifact.stat().st_size > MAX_ARCHIVE_BYTES:
                violations.append(f"{label}: artifact exceeds the size limit")
                continue
            if artifact.name.endswith(".whl"):
                violations.extend(_scan_zip(artifact))
            elif artifact.name.endswith(".tar.gz"):
                violations.extend(_scan_tar(artifact))
            else:
                violations.append(f"{label}: unsupported distribution format")
        except OSError, tarfile.TarError, zipfile.BadZipFile:
            violations.append(f"{label}: archive could not be inspected")
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit Countscape's worktree, history, and release artifacts."
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan every Git object reachable from every local ref",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="also scan the exact regular-file blobs staged in the Git index",
    )
    parser.add_argument(
        "--artifacts",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="also inspect built wheel and source distribution archives",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        violations = scan()
        if args.staged:
            violations.extend(scan_staged())
        if args.history:
            violations.extend(scan_history())
        if args.artifacts:
            violations.extend(scan_artifacts(tuple(args.artifacts)))
    except RuntimeError:
        print("Privacy check failed: repository history could not be inspected.")
        return 1
    if violations:
        print("Privacy check failed:")
        for violation in sorted(set(violations)):
            print(f"- {violation}")
        return 1
    scopes = ["worktree"]
    if args.staged:
        scopes.append("staged index")
    if args.history:
        scopes.append("reachable Git history")
    if args.artifacts:
        scopes.append("release artifacts")
    print(f"Privacy check passed ({', '.join(scopes)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
