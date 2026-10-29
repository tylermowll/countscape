from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from tools import dependency_snapshot

IDENTITY = {
    "sha": "a" * 40,
    "ref": "refs/heads/main",
    "job_id": "123-1",
    "job_url": "https://github.com/example/project/actions/runs/123",
}


def _sbom(*, development: bool = True) -> dict:
    packages = {"photo": "pillow@13.0.0", "shared": "example-runtime@1.0"}
    edges = {"root": ["photo"], "photo": ["shared"], "shared": []}
    if development:
        packages.update({"test": "pytest@9.2.0", "helper": "example-helper@2.0"})
        edges["root"].append("test")
        edges.update({"test": ["helper", "shared"], "helper": []})
    return {
        "metadata": {
            "component": {"bom-ref": "root", "name": "private project"},
            "private": "secret event",
        },
        "components": [
            {
                "bom-ref": reference,
                "purl": f"pkg:pypi/{package}",
                "properties": [{"name": "path", "value": "/private/photos"}],
            }
            for reference, package in packages.items()
        ],
        "dependencies": [
            {"ref": reference, "dependsOn": children}
            for reference, children in edges.items()
        ],
    }


def test_snapshot_preserves_scopes_relationships_and_actual_edges() -> None:
    snapshot = dependency_snapshot.make_snapshot(
        _sbom(), _sbom(development=False), **IDENTITY
    )
    resolved = snapshot["manifests"]["uv.lock"]["resolved"]
    photo = resolved["pkg:pypi/pillow@13.0.0"]
    assert photo == {
        "package_url": "pkg:pypi/pillow@13.0.0",
        "relationship": "direct",
        "scope": "runtime",
        "dependencies": ["pkg:pypi/example-runtime@1.0"],
    }
    assert resolved["pkg:pypi/example-runtime@1.0"]["scope"] == "runtime"
    assert resolved["pkg:pypi/example-runtime@1.0"]["relationship"] == "indirect"
    assert resolved["pkg:pypi/pytest@9.2.0"]["scope"] == "development"
    assert resolved["pkg:pypi/pytest@9.2.0"]["relationship"] == "direct"
    assert resolved["pkg:pypi/pytest@9.2.0"]["dependencies"] == [
        "pkg:pypi/example-helper@2.0",
        "pkg:pypi/example-runtime@1.0",
    ]
    assert resolved["pkg:pypi/example-helper@2.0"]["relationship"] == "indirect"
    assert snapshot["manifests"]["pyproject.toml"]["resolved"] == resolved


def test_snapshot_identity_is_stable_and_source_metadata_stays_private() -> None:
    snapshot = dependency_snapshot.make_snapshot(
        _sbom(), _sbom(development=False), **IDENTITY
    )
    assert snapshot["version"] == 0
    assert snapshot["sha"] == IDENTITY["sha"]
    assert snapshot["ref"] == IDENTITY["ref"]
    assert snapshot["job"] == {
        "id": IDENTITY["job_id"],
        "correlator": "countscape-uv-export-main",
        "html_url": IDENTITY["job_url"],
    }
    assert datetime.fromisoformat(snapshot["scanned"]).utcoffset().total_seconds() == 0
    encoded = json.dumps(snapshot)
    for private in ("private project", "secret event", "/private/photos", "bom-ref"):
        assert private not in encoded
    for name, manifest in snapshot["manifests"].items():
        assert manifest["file"]["source_location"] == name


@pytest.mark.parametrize(
    "invalid", ["local", "unknown_child", "unknown_parent", "missing"]
)
def test_snapshot_rejects_dependencies_it_cannot_represent(invalid: str) -> None:
    sbom = _sbom()
    if invalid == "local":
        sbom["components"][0]["purl"] = "pkg:generic/private@1?path=/private/source"
    elif invalid == "unknown_child":
        sbom["dependencies"][0]["dependsOn"].append("missing")
    elif invalid == "unknown_parent":
        sbom["dependencies"].append({"ref": "missing"})
    else:
        sbom["dependencies"].pop()
    with pytest.raises(ValueError):
        dependency_snapshot.make_snapshot(sbom, _sbom(development=False), **IDENTITY)


def test_snapshot_rejects_runtime_graph_not_in_complete_graph() -> None:
    runtime = _sbom(development=False)
    runtime["components"][0]["purl"] = "pkg:pypi/pillow@99.0.0"
    with pytest.raises(ValueError, match="runtime dependencies"):
        dependency_snapshot.make_snapshot(_sbom(), runtime, **IDENTITY)


@pytest.mark.parametrize(
    "override",
    [{"sha": "main"}, {"ref": "refs/heads/preview"}, {"job_url": "file:///private"}],
)
def test_snapshot_rejects_invalid_identity(override: dict) -> None:
    identity = IDENTITY | override
    with pytest.raises(ValueError):
        dependency_snapshot.make_snapshot(_sbom(), _sbom(development=False), **identity)


def test_cli_exports_both_graphs_without_network_and_writes_snapshot(
    tmp_path, monkeypatch
) -> None:
    calls = []

    def export(*options: str) -> dict:
        calls.append(options)
        return copy.deepcopy(_sbom(development=options == ("--all-groups",)))

    monkeypatch.setattr(dependency_snapshot, "export_sbom", export)
    output = tmp_path / "snapshot.json"
    arguments = ["--output", str(output)]
    for key, value in IDENTITY.items():
        arguments.extend([f"--{key.replace('_', '-')}", value])
    assert dependency_snapshot.main(arguments) == 0
    assert calls == [("--all-groups",), ("--no-default-groups",)]
    assert json.loads(output.read_text())["sha"] == IDENTITY["sha"]
