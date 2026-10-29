"""Submit only public, lock-resolved dependencies to GitHub's dependency graph."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURL = re.compile(r"pkg:pypi/[a-z0-9][a-z0-9._-]*@[A-Za-z0-9.!+_-]+")


def export_sbom(*options: str) -> dict:
    result = subprocess.run(
        ["uv", "export", "--locked", "--format", "cyclonedx1.5", *options],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def dependency_graph(sbom: dict) -> tuple[str, dict[str, str], dict[str, set[str]]]:
    root = sbom["metadata"]["component"]["bom-ref"]
    if not isinstance(root, str) or not root:
        raise ValueError("SBOM project root is missing")
    packages: dict[str, str] = {}
    for component in sbom["components"]:
        reference = component["bom-ref"]
        if reference == root:
            continue
        purl = component.get("purl", "")
        if not isinstance(purl, str) or not PURL.fullmatch(purl):
            raise ValueError(
                "SBOM contains an unsupported local or non-PyPI dependency"
            )
        if reference in packages or purl in packages.values():
            raise ValueError("SBOM contains duplicate dependency identities")
        packages[reference] = purl
    known = {root, *packages}
    edges: dict[str, set[str]] = {}
    for entry in sbom["dependencies"]:
        reference = entry["ref"]
        children = set(entry.get("dependsOn", []))
        if reference not in known or not children <= packages.keys():
            raise ValueError("SBOM contains an unresolved dependency reference")
        if reference in edges:
            raise ValueError("SBOM contains duplicate dependency graph entries")
        edges[reference] = children
    if edges.keys() != known:
        raise ValueError("SBOM dependency graph is incomplete")
    reachable, pending = set(), list(edges[root])
    while pending:
        reference = pending.pop()
        if reference not in reachable:
            reachable.add(reference)
            pending.extend(edges[reference])
    if reachable != packages.keys():
        raise ValueError("SBOM contains dependencies unreachable from the project")
    return root, packages, edges


def make_snapshot(
    all_sbom: dict,
    runtime_sbom: dict,
    *,
    sha: str,
    ref: str,
    job_id: str,
    job_url: str,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise ValueError("snapshot SHA must identify an exact commit")
    if ref != "refs/heads/main" or not job_id:
        raise ValueError("snapshot must identify a main-branch job")
    if not job_url.startswith("https://github.com/"):
        raise ValueError("snapshot job URL must be a public GitHub URL")
    root, packages, edges = dependency_graph(all_sbom)
    _, runtime_packages, _ = dependency_graph(runtime_sbom)
    runtime = set(runtime_packages.values())
    if not runtime <= set(packages.values()):
        raise ValueError("runtime dependencies do not match the complete lock graph")
    resolved = {
        purl: {
            "package_url": purl,
            "relationship": "direct" if reference in edges[root] else "indirect",
            "scope": "runtime" if purl in runtime else "development",
            "dependencies": sorted(packages[child] for child in edges[reference]),
        }
        for reference, purl in packages.items()
    }
    return {
        "version": 0,
        "sha": sha,
        "ref": ref,
        "job": {
            "id": job_id,
            "correlator": "countscape-uv-export-main",
            "html_url": job_url,
        },
        "detector": {
            "name": "countscape-uv-export",
            "version": "1.0.0",
            "url": "https://docs.astral.sh/uv/",
        },
        "scanned": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "coverage": "Locked runtime and dev groups; excludes build dependencies",
        },
        "manifests": {
            name: {
                "name": name,
                "file": {"source_location": name},
                "metadata": {"resolution_source": "uv.lock"},
                "resolved": resolved,
            }
            for name in ("uv.lock", "pyproject.toml")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("sha", "ref", "job-id", "job-url"):
        parser.add_argument(f"--{argument}", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = make_snapshot(
            export_sbom("--all-groups"),
            export_sbom("--no-default-groups"),
            sha=args.sha,
            ref=args.ref,
            job_id=args.job_id,
            job_url=args.job_url,
        )
        args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    except OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError:
        print("Dependency snapshot failed; nothing was submitted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
