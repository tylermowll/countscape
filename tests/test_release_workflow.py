from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _job_block(workflow: str, job: str, next_job: str) -> str:
    return workflow.split(f"  {job}:\n", 1)[1].split(f"  {next_job}:\n", 1)[0]


def test_pypi_job_can_reverify_private_draft_immediately_before_upload() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    publish = _job_block(workflow, "publish", "github-release")

    assert "      contents: write\n      id-token: write\n" in publish
    assert "gh release view" in publish
    assert "Reverify exact GitHub release and tag" in publish


def test_one_time_recovery_rechecks_mutable_draft_after_approval() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    recovery = workflow.split("  recover-pypi:\n", 1)[1]

    assert "      contents: write\n      id-token: write\n" in recovery
    assert 'releases/375099485"' in recovery
    assert '--rawfile body "${notes}"' in recovery
    assert ".draft == true" in recovery
    assert ".immutable == false" in recovery
    assert 'gh release download "${RELEASE_TAG}"' in recovery
    assert recovery.index("Reverify exact source and bundle") < recovery.index(
        "Detect an exact prior PyPI publication"
    )
