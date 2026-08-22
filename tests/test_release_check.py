from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools import release_check


def _changelog(
    root: Path,
    heading: str,
    body: str = "### Added\n\n- Safe change.",
) -> None:
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## Unreleased\n\nNone.\n\n## {heading}\n\n{body}\n",
        encoding="utf-8",
    )


def _metadata(requires_python: str) -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        "Name: countscape\n"
        "Version: 0.1.0\n"
        f"Requires-Python: {requires_python}\n\n"
    ).encode()


def test_distribution_python_contract_accepts_metadata_whitespace_only() -> None:
    release_check._validate_metadata_identity(
        _metadata(">=3.14, <3.15"),
        "0.1.0",
    )

    with pytest.raises(ValueError, match="Python support"):
        release_check._validate_metadata_identity(
            _metadata(">=3.14"),
            "0.1.0",
        )


def test_changelog_section_requires_dated_exact_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    _changelog(tmp_path, "0.1.0 - 2026-08-22")

    assert release_check.changelog_section("0.1.0") == ("### Added\n\n- Safe change.")


@pytest.mark.parametrize(
    "heading,version",
    [
        ("0.1.0 - Pending", "0.1.0"),
        ("0.2.0 - 2026-08-22", "0.1.0"),
        ("0.1.0 - 22 August 2026", "0.1.0"),
    ],
)
def test_changelog_section_rejects_unreleasable_headings(
    tmp_path: Path,
    monkeypatch,
    heading: str,
    version: str,
) -> None:
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    _changelog(tmp_path, heading)

    with pytest.raises(ValueError):
        release_check.changelog_section(version)


def test_changelog_section_rejects_pending_body(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    _changelog(
        tmp_path,
        "0.1.0 - 2026-08-22",
        "This release is not published until all gates pass.",
    )

    with pytest.raises(ValueError, match="publication-pending"):
        release_check.changelog_section("0.1.0")


def test_release_notes_are_complete_and_deterministic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    _changelog(tmp_path, "0.1.0 - 2026-08-22")
    wheel = tmp_path / "countscape-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "countscape-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    artifacts = (wheel, sdist)

    notes = release_check.render_release_notes("v0.1.0", "0.1.0", artifacts)

    assert notes.startswith("# Countscape v0.1.0\n\n## Changes\n")
    assert "## Support scope" in notes
    assert "## Known limitations" in notes
    assert "## Artifact SHA-256 digests" in notes
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert f"{digest}  {artifact.name}" in notes
    assert notes.endswith("```\n")
