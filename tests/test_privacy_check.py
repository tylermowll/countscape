from __future__ import annotations

import subprocess
from pathlib import Path

from tools import privacy_check


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    )


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.name", "Countscape tests")
    _git(path, "config", "user.email", "tests@users.noreply.github.com")
    tracked = path / "tracked.txt"
    tracked.write_text("safe public text\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "Initial safe fixture")
    return path


def test_github_automation_addresses_are_nonpersonal() -> None:
    text = "GitHub <noreply" + "@github.com> support" + "@github.com"

    assert privacy_check._text_findings(text) == ()
    assert privacy_check._text_findings("person" + "@github.com") == (
        "personal email address",
    )


def test_staged_scan_reads_index_instead_of_cleaned_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path / "repository")
    tracked = repository / "tracked.txt"
    private_path = "/ho" + "me/private-user/photos"
    tracked.write_text(f"private path: {private_path}\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    tracked.write_text("safe public text\n", encoding="utf-8")
    monkeypatch.setattr(privacy_check, "ROOT", repository)

    assert privacy_check.scan() == []
    assert privacy_check.scan_staged() == ["tracked.txt: absolute user-home path"]


def test_staged_scan_rejects_symbolic_links(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "repository")
    (repository / "linked.txt").symlink_to("tracked.txt")
    _git(repository, "add", "linked.txt")
    monkeypatch.setattr(privacy_check, "ROOT", repository)

    assert "linked.txt: symbolic links are not allowed" in privacy_check.scan_staged()


def test_staged_deletion_has_no_worktree_or_index_bytes_to_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path / "repository")
    _git(repository, "rm", "tracked.txt")
    monkeypatch.setattr(privacy_check, "ROOT", repository)

    assert privacy_check.scan() == []
    assert privacy_check.scan_staged() == []


def test_reviewed_media_is_bound_to_exact_path_and_bytes() -> None:
    for path in privacy_check.APPROVED_MEDIA:
        data = (privacy_check.ROOT / path).read_bytes()

        assert privacy_check._scan_repository_bytes(path, data) == []
        assert privacy_check._scan_repository_bytes("docs/assets/other.webp", data) == [
            "docs/assets/other.webp: unexpected media or build artifact"
        ]
        assert privacy_check._scan_repository_bytes(path, data + b"changed") == [
            f"{path}: unexpected media or build artifact"
        ]
