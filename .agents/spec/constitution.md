# Countscape Repository Constitution

## 1. Purpose

Build a dependable, attractive Ubuntu GNOME wallpaper that combines local
photos with a user-configured countdown. Keep the product focused, offline, and
reversible.

## 2. Privacy and data ownership

- Personal photos, event details, local configuration, generated wallpapers,
  secrets, logs, and machine state do not belong in the public repository or
  release artifacts.
- Source photos are user-owned, read-only inputs. Countscape never renames,
  rewrites, or deletes them.
- The user explicitly selects a photo directory. Countscape does not crawl the
  home directory to infer one.
- Generated images, cache, configuration, and integration state have distinct,
  documented ownership and removal rules.
- Uninstall removes only validated Countscape-managed files and preserves user
  configuration and source photos.
- If integration ownership or wallpaper restoration cannot be proven, removal
  must stop safely and report the recovery step.

## 3. Time correctness

- Store a target with an explicit UTC offset and retain the matching IANA
  timezone.
- Calculate from aware instants, not formatted wall-clock strings or a cached
  decrementing counter.
- Require explicit user confirmation before integration starts for a target.
- Define and test behavior before, at, and after the target, across daylight-
  saving transitions, suspend-like jumps, and clock corrections.
- Treat countdown refresh and photo rotation as independent schedules.
- Keep installed schedule triggers aligned to the wall clock and preserve
  resume catch-up.

## 4. Rendering safety

- Preserve source-photo bytes and honor image orientation when rendering.
- Bound canvas allocations and reject invalid or overlapping layouts.
- Replace generated images and state atomically.
- Serialize render/apply operations and preserve the last known-good wallpaper
  when an operation fails.
- Do not leave GNOME pointing at an output that ordinary cache cleanup may
  remove.

## 5. Platform boundary

- Ubuntu 26.04 GNOME/Wayland is the initial supported platform.
- Keep countdown, selection, configuration, display normalization, and
  rendering testable without a graphical session.
- Isolate Mutter discovery, GNOME settings, and systemd user integration behind
  adapters.
- Use Mutter's read-only current-state interface and retain mode, logical
  position, scale, transform, primary status, layout mode, and mirroring.
- Prefer user-scoped integration and avoid root-owned services.

## 6. Python environment

- Target Python 3.14 for the initial release.
- Use `uv` exclusively for environments, dependency changes, locks, commands,
  builds, and tests.
- Declare dependencies in `pyproject.toml` and commit `uv.lock`.
- Do not use bare `pip`, Poetry, or Conda in repository workflows.

## 7. Quality and publication

- Add automated tests with implementation and keep documentation synchronized
  with actual commands and paths.
- Clearly distinguish implemented behavior from proposed design.
- Run focused tests and static checks before claiming a change works.
- Build releases from a clean clone and inspect source archives, wheels,
  screenshots, fixtures, metadata, and reachable Git objects for private data.
- Expand platform support only after contract fixtures and live-session
  verification exist.
- Installation must be repeatable and have an equally clear rollback and
  uninstall path.
