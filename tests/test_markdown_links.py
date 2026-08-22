from __future__ import annotations

import subprocess
from pathlib import Path

from tools import check_markdown_links


def test_checked_in_wiki_navigation_resolves() -> None:
    violations, _count = check_markdown_links.check_links()

    assert [item for item in violations if item.startswith("wiki/")] == []


def test_staged_markdown_deletion_is_not_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Countscape tests"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@users.noreply.github.com"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    document = repository / "removed.md"
    document.write_text("# Removed\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "removed.md"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add Markdown fixture"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "rm", "removed.md"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(check_markdown_links, "ROOT", repository)

    violations, count = check_markdown_links.check_links()

    assert violations == []
    assert count == 0
