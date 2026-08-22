# Public-release readiness audit — 2026-08-22

Status: **safe public-repository checkpoint; publication is not yet approved**.

This document is the cross-machine handoff for the v0.1 hard cutover. It records
what is complete, what was independently challenged, and the exact work that
must remain blocked. It contains no private configuration, paths, photos, event
details, connector identifiers, secrets, or raw diagnostics.

## Checkpoint scope

The repository now has one strict v1 contract:

- Python 3.14 on Ubuntu 26.04 GNOME/Wayland;
- `uv` for environments, locking, builds, tests, and tool installation;
- schema-versioned config, install manifest, GNOME state, render state, and
  ownership markers with no pre-release migration layer;
- separate config, immutable source-photo, persistent output, rebuildable cache,
  and runtime-state paths;
- a durable `uv tool install` environment for generated systemd user units;
- privacy-redacted `doctor` and `status` output by default, with explicit
  warnings on private opt-in output;
- ownership- and digest-checked install, update, recovery, and uninstall; and
- atomic state/output replacement and idempotent render/apply behavior.

Public documentation, community standards, issue forms, pull-request guidance,
CI, CodeQL, dependency updates, artifact checks, provenance, trusted-publishing
workflow, and immutable-release staging are present. The README hero is a
synthetic illustration with stripped metadata and a pinned reviewed digest.
The reviewed Wiki publication source is tracked under `wiki/`, and a
repository-native pre-commit hook is tracked under `.githooks/`.

## Adversarial findings and disposition

Every high- or medium-severity finding from the final reviews was resolved:

1. `init --force` now refuses to orphan active or unresolved integration state.
2. Default `status` and `doctor` redact raw state and config I/O errors; private
   details require `--include-private` and print a sharing warning.
3. Config-driven uninstall binds the config path, selection ownership, output,
   cache, and runtime state to the install manifest. Explicit state-directory
   recovery remains available when the final config cannot load.
4. Uninstall stops with evidence intact if GNOME still references a generated
   output or the owned cached base image.
5. State-only recovery refuses to report success while GNOME restoration state
   remains unresolved.
6. First-install failures transactionally roll back exact unchanged unit
   sources, the manifest, and newly created systemd links while preserving any
   foreign or changed artifact.
7. Generated unit sources live in runtime state and are linked into the user
   manager; they never depend on the checkout or repository `.venv`.
8. Static pre-release calibration output is no longer treated as managed data.
9. The privacy scanner now resolves nested files and tree-only Git refs, so
   crash-recovery refs cannot bypass or falsely fail the reviewed-media rule.
10. The release transaction is ordered as build/provenance, verified GitHub
    draft, PyPI trusted publication, draft re-verification, then one immutable
    GitHub publication. Required support scope, limitations, and exact artifact
    digests are enforced in the draft body.

Three read-only final reviews found no remaining high-severity issue. The
release workflow was re-reviewed after its transaction-order fix and had no
remaining high- or medium-severity finding.

## Verification evidence

The checkpoint was exercised on Python 3.14.6 with:

```text
292 tests passed
90.8% total branch coverage (90.0% gate)
CLI and config: 99%
GNOME adapter: 96.7%
display, models, and Mutter adapter: 100%
state: 99.0%
```

The suite uses temporary XDG roots, fake desktop/systemd adapters, and synthetic
images. It does not change live GNOME settings, source photos, or user config.

The same checkpoint also passed:

- locked dependency synchronization;
- worktree and complete reachable-history privacy inspection;
- all local Markdown-link checks;
- Ruff formatting and lint checks;
- an exact wheel and source-distribution build;
- distribution filename and embedded-metadata validation;
- release-artifact privacy inspection; and
- isolated wheel and source-distribution smoke tests outside the checkout.

## GitHub settings already applied

- Repository description and public topics are set.
- Issues and Wiki are enabled; Discussions and Projects are disabled.
- Squash merge, automatic branch deletion, and automatic merge are enabled;
  merge commits and rebase merging are disabled.
- Secret scanning, push protection, Dependabot alerts, Dependabot security
  updates, and private vulnerability reporting are enabled.
- The default Actions token is read-only and cannot approve pull requests.
- Immutable releases are enabled.
- The `pypi` environment exists and permits only `v*` tag deployments.

## Deliberately incomplete work

Do not describe any of these as complete:

1. **Required rulesets.** At audit time GitHub had no active ruleset. After the
   first pushed CI and CodeQL runs register their check names, protect `main`
   against deletion and non-fast-forward updates, require linear squash pull
   requests and the exact checks `Ubuntu 26.04 / Python 3.14` and
   `Analyze Python`, and protect `v*` tags from creation, update, deletion, and
   non-fast-forward changes except for the explicit maintainer bypass.
2. **GitHub Wiki publication.** GitHub has not initialized the Wiki Git
   repository. Create the first page in the GitHub UI, then publish the reviewed
   six-page source tracked under `wiki/`: Home, Privacy, FAQ, Display Recipes,
   Tested GNOME Configurations, and Community Troubleshooting. Canonical
   repository docs must remain authoritative, and editing must remain
   collaborator-only.
3. **PyPI trust registration.** The `countscape` project is not published. In
   PyPI, register the pending trusted publisher for owner `tylermowll`, repository
   `countscape`, workflow `release.yml`, and environment `pypi` before pushing a
   release tag.
4. **Live platform evidence.** A privacy-safe preflight saw a Wayland GNOME 50.1
   session and working background settings, but the sandbox could not reach the
   systemd user manager or Mutter display interface. The complete Ubuntu 26.04
   live install/apply/timer/uninstall matrix remains unrun.
5. **Social preview.** The reviewed hero is ready, but repository social-preview
   upload remains a GitHub UI action.
6. **Release.** No `v0.1.0` tag, GitHub release, or PyPI distribution exists.

The tracked `wiki/` directory is the reviewable publication source, not a second
canonical product manual. Remove it only if an equally reviewable automated Wiki
publication source replaces it.

## Resume order on another computer

1. Clone `main`, run `uv sync --locked --all-groups`, enable the tracked hook
   with `git config core.hooksPath .githooks`, and rerun the full `AGENTS.md`
   gate sequence.
2. Inspect the pushed CI and CodeQL runs; fix any host-only discrepancy before
   enabling required checks.
3. Apply the `main` and `v*` rulesets described above.
4. Initialize and publish the Wiki, then verify its privacy/editing policy.
5. Register the pending PyPI trusted publisher.
6. Complete and record the live Ubuntu 26.04 GNOME/Wayland matrix in
   `docs/release-checklist.md` without committing private evidence.
7. Only when every release blocker is cleared, create the protected `v0.1.0`
   tag and let the release workflow publish the already-reviewed artifacts.

If any artifact or public release needs correction after publication, increment
the version. Never replace an immutable asset in place.
