from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "countscape"


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("project.version is missing from pyproject.toml")
    return version


def validate_single_version_source(version: str) -> None:
    with (ROOT / "uv.lock").open("rb") as handle:
        lock = tomllib.load(handle)
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock has no package records")
    local_packages = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get("name") == PROJECT_NAME
        and isinstance(package.get("source"), dict)
        and package["source"].get("editable") == "."
    ]
    if len(local_packages) != 1 or local_packages[0].get("version") != version:
        raise ValueError("uv.lock and project metadata versions do not match")

    for module in sorted((ROOT / "src" / PROJECT_NAME).rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and node.id == "__version__"
                and isinstance(node.ctx, ast.Store)
            ):
                raise ValueError(
                    "package source must read installed metadata, "
                    "not declare __version__"
                )
            if isinstance(node, ast.ImportFrom) and any(
                (alias.asname or alias.name) == "__version__" for alias in node.names
            ):
                raise ValueError(
                    "package source must read installed metadata, "
                    "not import __version__"
                )
            if isinstance(node, ast.Import) and any(
                alias.asname == "__version__" for alias in node.names
            ):
                raise ValueError(
                    "package source must read installed metadata, "
                    "not import __version__"
                )
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__version__"
            ):
                raise ValueError(
                    "package source must read installed metadata, "
                    "not define __version__"
                )


def validate_tag(tag: str, version: str) -> None:
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(
            f"release tag must exactly match project metadata ({expected})"
        )


def _metadata_identity(data: bytes) -> tuple[str, str]:
    metadata = BytesParser(policy=policy.default).parsebytes(data)
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        raise ValueError("distribution metadata must contain one Name and Version")
    return names[0], versions[0]


def _validate_metadata_identity(data: bytes, version: str) -> None:
    name, artifact_version = _metadata_identity(data)
    normalized_name = re.sub(r"[-_.]+", "-", name).lower()
    if normalized_name != PROJECT_NAME or artifact_version != version:
        raise ValueError("distribution filename and embedded metadata do not match")


def _validate_wheel_metadata(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        metadata_members = [
            name
            for name in archive.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_members) != 1:
            raise ValueError("wheel must contain exactly one metadata record")
        _validate_metadata_identity(archive.read(metadata_members[0]), version)


def _validate_sdist_metadata(path: Path, version: str) -> None:
    root = path.name.removesuffix(".tar.gz")
    expected = f"{root}/PKG-INFO"
    with tarfile.open(path, mode="r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name == expected]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("sdist must contain exactly one root metadata record")
        extracted = archive.extractfile(members[0])
        if extracted is None:
            raise ValueError("sdist metadata could not be read")
        _validate_metadata_identity(extracted.read(), version)


def validate_artifacts(paths: tuple[Path, ...], version: str) -> tuple[Path, ...]:
    artifacts = tuple(
        sorted(
            (path.expanduser().absolute() for path in paths),
            key=lambda path: path.name,
        )
    )
    expected_names = {
        f"countscape-{version}-py3-none-any.whl",
        f"countscape-{version}.tar.gz",
    }
    actual_names = {path.name for path in artifacts}
    if len(artifacts) != 2 or actual_names != expected_names:
        raise ValueError(
            "release must contain exactly one expected wheel and one sdist"
        )
    if any(path.is_symlink() or not path.is_file() for path in artifacts):
        raise ValueError("release artifacts must be regular files")
    for artifact in artifacts:
        if artifact.name.endswith(".whl"):
            _validate_wheel_metadata(artifact, version)
        else:
            _validate_sdist_metadata(artifact, version)
    return artifacts


def write_checksums(path: Path, artifacts: tuple[Path, ...]) -> None:
    lines = []
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}\n")
    destination = path.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError("checksum destination must not be a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write("".join(lines))
        temporary.chmod(0o644)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate release identity and exact distribution artifacts."
    )
    parser.add_argument(
        "--tag",
        help="release tag; when supplied it must exactly match project metadata",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="print only the validated project version",
    )
    parser.add_argument("--artifacts", nargs="+", type=Path, metavar="PATH")
    parser.add_argument("--write-checksums", type=Path, metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        version = project_version()
        validate_single_version_source(version)
        if args.print_version and (args.tag or args.artifacts or args.write_checksums):
            raise ValueError("--print-version cannot be combined with other options")
        if args.print_version:
            print(version)
            return 0
        if args.tag:
            validate_tag(args.tag, version)
        artifacts: tuple[Path, ...] = ()
        if args.artifacts:
            artifacts = validate_artifacts(tuple(args.artifacts), version)
        if args.write_checksums:
            if not artifacts:
                raise ValueError("--write-checksums requires --artifacts")
            write_checksums(args.write_checksums, artifacts)
    except (
        OSError,
        SyntaxError,
        ValueError,
        tarfile.TarError,
        tomllib.TOMLDecodeError,
        zipfile.BadZipFile,
    ) as error:
        print(f"release check failed: {error}", file=sys.stderr)
        return 1
    print(f"Release identity is valid for v{version}.")
    if artifacts:
        print("Release contains exactly one wheel and one source distribution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
