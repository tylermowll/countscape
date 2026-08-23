# Release Checklist

This checklist is the publication gate for Countscape. Complete it from a clean
release candidate, retain redacted evidence, and do not claim a tag, package, or
live platform validation before it exists.

The current cross-machine status and unresolved blockers are recorded in the
[public-repository readiness audit](audits/public-repository-readiness.md).

## 1. Define the release

- [ ] Choose the exact version and intended tag, for example `0.1.0` and
  `v0.1.0`.
- [ ] Confirm package and runtime version metadata agree.
- [ ] Move user-visible changes from `Unreleased` into the release section of
  [CHANGELOG.md](../CHANGELOG.md).
- [ ] Review installation, upgrade, rollback, and uninstall instructions for the
  exact release.
- [ ] Confirm [SECURITY.md](../SECURITY.md) names the supported release line.
- [ ] Replace pending-release wording in package-description content with
  exact-channel guidance that remains true after publication; tagged wheel and
  source-archive descriptions cannot be corrected in place.

## 2. Clean-tree verification

Use a clean clone or worktree containing only the proposed release commit:

```bash
uv sync --locked --all-groups
uv run python tools/privacy_check.py --history
uv run python tools/check_markdown_links.py
uv run ruff format --check .
uv run ruff check .
uv run pytest \
  --cov=countscape \
  --cov-branch \
  --cov-report=term-missing \
  --cov-config=.coveragerc
uv build --no-sources --clear --out-dir dist
uv run python tools/release_check.py \
  --artifacts dist/*.whl dist/*.tar.gz \
  --write-checksums dist/SHA256SUMS
uv run python tools/privacy_check.py \
  --history \
  --artifacts dist/*.whl dist/*.tar.gz
```

- [ ] All commands pass with the committed lock.
- [ ] The working tree remains clean.
- [ ] Source archive and wheel members are enumerated and reviewed.
- [ ] Built metadata and README rendering are reviewed.
- [ ] The wheel and source archive each install and expose `countscape --version`.
- [ ] The built command's version exactly matches the intended tag.
- [ ] No source photo, event, config, generated wallpaper, cache, log, absolute
  user path, secret, or editor state appears in either artifact.
- [ ] Tracked files, screenshots, fixtures, metadata, all reachable refs, and Git
  objects are reviewed for private data.
- [ ] Documentation links resolve and the synthetic hero and social-preview card
  have provenance, no embedded personal metadata, and appropriate accessible
  text where rendered in repository content.

## 3. Automated behavior gates

- [ ] Countdown tests cover before, at, and after target boundaries.
- [ ] Time tests cover daylight-saving changes, backward corrections, and
  suspend-like jumps.
- [ ] Photo/render tests cover missing, empty, invalid, portrait, landscape,
  transparent, oversized decoded sources, Pillow decoding failures, and long-text
  inputs.
- [ ] Display tests cover single, mixed orientation, scaling, transforms, and
  mirroring.
- [ ] Schedule tests cover independent boundaries, unchanged reuse, and exact
  wall-clock timer generation.
- [ ] Installation tests cover update, exact-version rollback, unit ownership,
  GNOME restoration, safe uninstall refusal, regeneration rollback, and
  retryability after injected destructive-phase failures.
- [ ] Config tests require `schema_version = 1`, reject pre-v0.1 preview config,
  and validate a distinct recorded runtime-state directory.
- [ ] Lifecycle tests prove the generated service loads the config-recorded state
  path and uninstall recovery accepts an explicit known `--state-directory`
  without guessing from ambient XDG variables.
- [ ] Automated tests use temporary XDG roots and fake desktop adapters only.

## 4. Live Ubuntu 26.04 evidence

Run these checks in a real supported graphical user session. Do not store
personal photos, full configs, usernames, home paths, monitor serials, or raw
journals as public evidence.

Copy this template into private release notes, replace every `NOT RUN`, and
publish only a redacted summary:

```text
Countscape live validation
Release candidate: 0.1.0 / <commit>
Date (UTC): YYYY-MM-DD
Tester reference: <non-personal identifier>

Environment
- Ubuntu release: 26.04
- GNOME Shell version: <version>
- Session type: Wayland
- Python version: 3.14.x
- uv version: <version>
- Countscape version: <version>
- Install source and artifact digest: <redacted-safe value>

Baseline
- clean exact-version tool install: NOT RUN
- init with aware target and private temporary photos: NOT RUN
- doctor: NOT RUN
- render without GNOME mutation: NOT RUN
- user confirmation of preview: NOT RUN
- install and immediate timer run: NOT RUN
- status and service journal healthy: NOT RUN

Display cases
- single landscape display: NOT RUN
- portrait transform: NOT RUN
- mixed orientation: NOT RUN
- fractional/integer scaling used: NOT RUN
- mirrored layout: NOT RUN
- explicit fallback profile: NOT RUN

Lifecycle
- unchanged apply is a no-op: NOT RUN
- independent countdown/photo bucket boundary: NOT RUN
- resume after missed timer trigger: NOT RUN
- exact-version reinstall and integration regeneration: NOT RUN
- rollback to previous supported version: NOT RUN / NOT APPLICABLE
- newer user wallpaper choice preserved: NOT RUN
- uninstall restores eligible original URI: NOT RUN
- uninstall preserves config and source-photo bytes: NOT RUN

Result: NOT RUN
Failures or release blockers: <none recorded>
Evidence location: <private or redacted-safe reference>
```

- [ ] At least one complete baseline result passes on Ubuntu 26.04 GNOME/Wayland.
- [ ] Every display case claimed in release notes has live evidence.
- [ ] Source-photo hashes before and after match for exercised inputs.
- [ ] Any failure is fixed and rerun, or explicitly blocks publication.

## 5. Publish and verify

- [ ] Create the signed or otherwise protected `vX.Y.Z` tag from the reviewed
  commit.
- [ ] Create the GitHub release as a draft from the verified tag, with changelog,
  support scope, known limitations, and artifact digests.
- [ ] Confirm automation replaced the complete draft title and body with the
  deterministic, dated changelog section and exact tested artifact digests.
- [ ] Attach exactly the tested wheel, source archive, and `SHA256SUMS` to the
  draft; do not rebuild or substitute an asset.
- [ ] Verify the complete draft, attached filenames, checksums, notes, and tag.
- [ ] Only after draft verification, publish the same reviewed artifacts to PyPI
  through the approved release workflow.
- [ ] After PyPI succeeds, reverify the draft and publish that existing draft
  once. Never create a different public release from the tag.
- [ ] Treat the published GitHub release and its assets as immutable. Never
  replace an asset in place; publish a new version for any correction.
- [ ] Install from the public package index using the exact README command in a
  clean tool environment.
- [ ] Verify `countscape --version`, `doctor`, render, and integration install from
  the public artifact.
- [ ] Verify package links for source, issues, documentation, changelog, and
  security.
- [ ] After both channels and the public-install verification succeed, update
  time-sensitive status records on the default branch without implying that
  tagged artifacts can be changed in place.

## 6. Repository community settings

- [ ] Private vulnerability reporting is enabled and tested without disclosing a
  real vulnerability.
- [ ] Issue forms and the pull-request template point to the privacy and security
  policies.
- [ ] Branch protection requires the release checks.
- [ ] The GitHub Wiki is restricted to collaborator editing.
- [ ] Published wiki pages match the reviewed publication copy.
- [ ] Community wiki pages link back to canonical repository documentation and
  direct proposed changes to the issue tracker.

## 7. After release

- [ ] Confirm the default branch starts a new `Unreleased` changelog section.
- [ ] Confirm the support table and rollback examples still name real versions.
- [ ] Record the redacted live-validation summary without machine-local details.
- [ ] Triage installation feedback without asking users to publish private config,
  photos, generated wallpapers, or unredacted diagnostics.
