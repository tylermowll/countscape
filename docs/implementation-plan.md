# Implementation Plan

## Outcome

Publish Countscape as a privacy-safe Ubuntu GNOME utility with fresh public Git
history, an installable package, user-owned photos and configuration, truthful
independent schedules, and reversible user-level integration.

The implementation is now a selective, generic port of the tested countdown,
rendering, Mutter, GNOME, and systemd design. The remaining work is release
hardening and live validation, not a rewrite.

## Current status

| Area | Implemented and tested in the current tree | Remaining release gate |
|---|---|---|
| Identity | Fresh `countscape` distribution, package, CLI, units, XDG paths, messages, generic fixtures, and public history | Repeat the reachable-object and artifact audit before each release |
| Package | Complete source distribution and wheel build and smoke-run in an isolated tool environment; the service invokes Python with `-m countscape` | Confirm default-branch CI and the live installed flow |
| Setup | `init` creates confirmed private config, stable seed, defaults, and a photo directory; paths and schedules are customizable | Exercise the packaged flow in a clean user profile |
| Configuration | Event, timezone, label, completion message, photo directory, fit, overlay, and both schedules can be changed atomically | Define compatibility policy before changing the schema after release |
| Storage | Config, source photos, persistent output, rebuildable cache, and state have separate XDG defaults | Verify custom-path ownership and cleanup live |
| Scheduling | Independently aligned second buckets, persistent wall-clock triggers, render reuse, and idempotent GNOME apply | Observe default and nonmatching intervals through suspend and login |
| Display/rendering | Aware countdown, deterministic selection, Mutter layouts, adaptive overlay, content-identified output, reuse, pruning, locking, and atomic writes | Verify a packaged build on single and mixed-orientation live layouts |
| Lifecycle | Preflighted repeatable install, unit/manifest integrity checks, configuration-owned markers, and conditional per-URI restoration | Rehearse update, pinned rollback, and uninstall from release artifacts |
| Project surface | Public-safe README, architecture, plan, contribution/security guidance, MIT license, package metadata, and CI workflow | Add a non-personal visual and keep default-branch CI green |
| Distribution | No release is claimed | Choose GitHub-only or GitHub plus PyPI, then tag verified artifacts |

The current automated baseline is:

```bash
uv sync --locked
uv run python tools/privacy_check.py
uv run pytest
uv run ruff check .
uv build
```

## Confirmed decisions

- The project, distribution, Python package, and command are Countscape /
  `countscape`.
- The code is licensed under MIT.
- The first supported platform is Ubuntu 26.04 GNOME/Wayland with Python 3.14
  and systemd user services.
- `uv` exclusively manages Python environments, dependencies, commands, locks,
  builds, tests, and tool installation.
- Source photos are immutable user inputs and are never shipped in the package.
- The user chooses the photo directory; Countscape does not search the home
  directory.
- Target arithmetic uses aware instants and retains an IANA timezone.
- Countdown refresh and photo rotation are independent aligned-second
  intervals, defaulting to 60 and 600 seconds. Whole-minute values and exact
  divisors of one minute are supported.
- Event label and completion message are customizable. Arbitrary countdown
  templates are deferred.
- Final wallpapers are persistent XDG data; only rebuildable intermediates use
  XDG cache.
- GNOME, Mutter, and systemd remain adapters around testable core logic.
- Installation is user-scoped, checkout-independent, and paired with
  conservative uninstall behavior.
- The public project remains one repository until a second real platform
  backend creates a reason to split it.

## Remaining decisions

- Whether version 0.1 is distributed from GitHub releases only or also through
  PyPI.
- Which generated or clearly licensed non-personal image will demonstrate the
  wallpaper in the README.
- Whether support expands beyond Ubuntu 26.04 after separate fixtures and live
  verification exist.

## Non-goals for version 0.1

- Other desktop environments or root-owned/system-wide installation.
- Photo downloads, synchronization, or recursive filesystem discovery.
- Network event tracking or automatic target changes.
- A graphical settings app, arbitrary templates, localization, or multiple
  events.
- Publishing earlier private Git history, media, event details, or rollout
  records.

## Phase 1 — Freeze the sanitized baseline

**Status:** Complete for the initial public source baseline. The same privacy,
object, clean-clone, and artifact checks remain mandatory for tagged releases.

This phase is the dependency for every public release step.

### Deliverables

1. Finish a file-by-file review of source, tests, fixtures, docs, config, and
   workflow files.
2. Remove caches, build products, generated images, local state, and all source
   photos from the proposed commit.
3. Add complete package license, project URL, author/maintainer, classifier, and
   supported-platform metadata without introducing unwanted personal data.
4. Run the privacy check for legacy identifiers, absolute local paths, and
   unintended media or runtime files in required clean-clone CI.
5. Initialize and publish only the fresh Countscape history; never attach the
   earlier repository as an ancestor or fork.

### Automated validation

- Locked sync, tests, Ruff, and build pass from a clean clone.
- Installing the built wheel into an isolated `uv tool` environment makes
  `countscape --help` work with no source checkout.
- The sdist and wheel member lists contain only intended distributable files.
- Tracked files and reachable Git objects contain no personal media, private
  event details, secrets, local paths, caches, or prior project identifiers.

### Acceptance criteria

- The first public commit is independently reviewable and has no inherited Git
  objects.
- The remote's default branch and CI refer only to the sanitized history.
- Deleting the staging checkout cannot affect any existing installation or
  private photo directory.

## Phase 2 — Package and lifecycle rehearsal

**Status:** Partial. The current wheel builds and its CLI smoke test passes in an
isolated tool environment; the complete temporary-profile lifecycle remains.

This phase validates the implemented package boundary on an isolated profile
before using a real desktop.

### Deliverables

1. Install the built wheel—not the working tree—into a temporary tool
   environment.
2. Run non-interactive `init` with temporary XDG roots, then also exercise the
   prompt path.
3. Populate a sanitized temporary photo bank and exercise doctor, render,
   repeated render reuse, configure, calibration, and status behavior.
4. Generate and verify user units containing an installed Python path with
   spaces and percent characters.
5. Rehearse reinstall/upgrade, an explicitly pinned rollback, and uninstall.

### Automated validation

- Tests cover missing, empty, invalid, nested, overlapping, relative, absolute,
  and space-bearing paths without changing source files.
- Tests cover naive targets, invalid zones, mismatched offsets, bounded display
  text, daylight-saving transitions, and exact boundaries.
- Tests prove repeated rendering reuses a valid output and invalidates on every
  relevant input change.
- Tests prove install and uninstall accept only matching ownership state and
  preserve configuration and source photos.

### Acceptance criteria

- Every documented command runs from the isolated package installation.
- Install, update, rollback, and uninstall leave a predictable, recoverable
  state without root or a source checkout.
- Source-photo hashes are unchanged.

## Phase 3 — Live GNOME validation

**Status:** Pending.

This phase begins only after the sanitized baseline and isolated lifecycle pass.

### Deliverables

1. Install the same verified wheel in a supported GNOME/Wayland user session.
2. Verify read-only Mutter discovery and a numbered calibration on a
   single-display layout.
3. Repeat on a mixed-orientation layout, including scale, transform, negative
   origin, primary status, and mirroring where hardware permits.
4. Observe the default 60/600 schedule, one nonmatching whole-minute pair, and
   one sub-minute pair whose greatest common divisor is smaller than either
   interval.
5. Exercise login, suspend/resume, dark/light URI behavior, journal output, and
   configuration changes.
6. Rehearse uninstall both while Countscape remains active and after manually
   changing one wallpaper URI.

### Manual acceptance criteria

- Countdown and photo transitions remain independent and current after login,
  suspend, and clock correction.
- Repeated unchanged polls do not rewrite the PNG or GNOME settings.
- Single- and mixed-monitor output matches calibration geometry and respects
  the configured fit.
- A partial user wallpaper change is preserved while the still-managed URI is
  restored independently.
- Source photos and configuration remain unchanged after uninstall.
- Old and new package versions are never scheduled simultaneously during
  rollback rehearsal.

## Phase 4 — Documentation and release

**Status:** Pending.

### Deliverables

1. Add a generated or clearly licensed, non-personal screenshot and record its
   provenance.
2. Replace the development-preview installation with a pinned release command.
3. Document package-channel update and pinned rollback commands that have been
   rehearsed in Phase 2 and Phase 3.
4. Record portable CI checks separately from live GNOME evidence.
5. Recheck the Countscape project and distribution name.
6. Protect the default branch and publish the exact verified source archive and
   wheel as `v0.1.0`; optionally publish those same artifacts through PyPI
   trusted publishing.

### Release acceptance criteria

- Every documented command exists and has been exercised where practical.
- CI passes from a clean clone with no private files or configuration.
- Public Git history, source archives, wheels, screenshots, fixtures, and logs
  pass privacy review.
- A clean user profile can initialize, preview, install, update, roll back, and
  uninstall the release.
- The application continues to operate offline after installation and setup.
- License, support scope, limitations, and security-reporting instructions are
  visible from the repository root.

## Risks and mitigations

- **Deleted private data remains in old Git history:** publish only the fresh
  Countscape history and audit all reachable objects.
- **A release contains local or private material:** build from a clean clone and
  inspect archive members, metadata, screenshots, fixtures, and logs.
- **GNOME references a deleted cache file:** keep final wallpapers in XDG data;
  reserve XDG cache for rebuildable intermediates.
- **Short intervals cause excessive timer activity:** allow only whole minutes
  or exact divisors of one minute, align triggers to the wall clock, document
  the greatest-common-divisor cadence, and retain safe defaults.
- **Uninstall follows tampered state:** validate the manifest and unit digests,
  require absolute non-root paths plus matching application, configuration
  ownership ID, and directory-kind markers, and remove only allowlisted names.
- **A user changes only one wallpaper URI:** restore each managed URI
  independently and leave newer choices alone.
- **Platform behavior differs:** keep the support statement narrow and require
  both adapter fixtures and live verification before expanding it.
- **The distribution name changes before release:** recheck the relevant
  namespace and use a distinct distribution name while preserving the
  Countscape project and CLI if necessary.
