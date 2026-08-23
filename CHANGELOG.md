# Changelog

All notable user-visible changes to Countscape are recorded here. The project
uses semantic versioning once releases are published.

## Unreleased

No post-v0.1 user-visible changes are recorded yet.

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
