# Changelog

All notable user-visible changes to Countscape are recorded here. The project
uses semantic versioning once releases are published.

## Unreleased

No unreleased changes are recorded yet.

## 0.3.0 - 2026-10-29

### Added

- A current-date overlay with a custom message and explicit IANA timezone,
  including target-free initialization through `countscape init --mode date`.
- Mode and message controls in `countscape configure`, retaining a valid
  inactive countdown event so it can be resumed later.
- Local-calendar date formatting from the actual aware instant, independent of
  countdown buckets and photo rotation, with reuse while visible content is
  unchanged.
- Fontconfig matching against the displayed Unicode characters to improve
  message-glyph selection from installed fonts.

### Fixed

- Exact-version upgrade instructions now replace an existing uv tool receipt
  pin with `uv tool install --force`; `uv tool upgrade` retains the old pin and
  can reject a different requested version.

Existing countdown configs remain readable. The new optional `[overlay]` table
requires v0.3 or later; restore a compatible private countdown-config backup
before rolling back to v0.2.0. Platform support remains Ubuntu 26.04
GNOME/Wayland with Python >=3.15.2, and live compatibility claims remain limited
to the [recorded release evidence](https://github.com/tylermowll/countscape/blob/main/docs/audits/v0.3.0-release.md).

## 0.2.0 - 2026-10-29

### Changed

- Require Python >=3.15.2, replacing the Python 3.14 requirement. The supported
  desktop target remains Ubuntu 26.04 GNOME/Wayland.
- Require Pillow >=13 and raise development and build dependency floors to the
  versions validated for this release. Dependency requirements use minimum
  versions; the committed lock records the exact development environment.
- Refresh the dependency lock and pinned GitHub Actions used for validation,
  provenance, and publication.
- Submit the resolved dependency graph from `uv` in CI while Dependabot's
  updater lacks Python 3.15 support, preserving dependency-alert coverage.
- Update installation and upgrade commands for Python 3.15.2 while retaining an
  explicit v0.1.0 rollback with Python 3.14. Configuration and integration-state
  schemas are unchanged.

Live GNOME evidence remains limited to the release and configurations recorded
in the [readiness audit](https://github.com/tylermowll/countscape/blob/main/docs/audits/public-repository-readiness.md). Automated
checks for this dependency update do not establish new live-platform evidence.
The maintainer authorized publication with the fresh live baseline recorded as
NOT RUN; the exception applies only to v0.2.0. See the
[release validation record](https://github.com/tylermowll/countscape/blob/main/docs/audits/v0.2.0-release.md).

## 0.1.0 - 2026-08-23

Initial public release for the supported Ubuntu GNOME/Wayland platform.

### Added

- Private initialization with aware event targets, matching IANA timezones, and
  confirmed user configuration.
- Deterministic local JPG/JPEG/PNG rotation on an independent schedule.
- EXIF-aware `contain` and `cover` rendering across normalized GNOME/Wayland
  display layouts.
- Mutter discovery for physical modes, logical positions, scaling, transforms,
  primary status, layout mode, and mirroring.
- Adaptive wrapped countdown overlays and completion messages.
- Atomic, content-identified final wallpapers, photo-only cache reuse, unchanged
  render reuse, and serialized render/apply operations.
- Read-only diagnostics, rendering, apply, calibration, configuration, status,
  user-scoped installation, and conservative uninstall commands.
- Persistent wall-clock scheduling with independent countdown and photo buckets.
- Conditional per-URI GNOME restoration and ownership-validated cleanup.
- Versioned private configuration and XDG-backed separation of config, photos,
  output, cache, recorded runtime state, and user units.

### Security and privacy

- Source photos remain read-only and are never renamed, rewritten, copied, or
  deleted.
- Generated output and state are replaced atomically.
- Managed directories use config-bound ownership markers and strict filename
  allowlists.
- Generated user units are content-hashed; foreign or edited units are refused.
- Managed unit regeneration keeps unit sources and the manifest
  digest-consistent across failures, and uninstall retains validated ownership
  evidence until destructive systemd cleanup succeeds.
- Lifecycle manifest schema v2 records the persistent systemd user-unit link
  directory for uninstall; pre-v0.1 integration state is not migrated.
- Source images have a fixed 50,000,000-pixel decode ceiling, and Pillow decode
  and decompression-bomb failures are reported as controlled input errors.
- Automated tests use temporary XDG roots and fake desktop adapters.
- Repository and release privacy checks screen for disallowed private and
  machine-local artifacts.
