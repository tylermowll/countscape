# Countscape Repository Constitution

This is the durable product contract for changes to behavior and invariants.
Use the relevant sections for the task. Current implementation details belong
in [Architecture](../../docs/architecture.md); publication and live-platform
evidence belong in the [dated audits](../../docs/audits/).

## 1. Purpose

Build a dependable, attractive Ubuntu GNOME wallpaper that combines local
photos with a user-configured countdown or current date and message. Keep the
product focused, offline, and reversible.

## 2. Privacy and data ownership

- Personal photos, overlay messages, event details, local configuration,
  generated wallpapers, secrets, logs, and machine state do not belong in the
  public repository or release artifacts.
- Source photos are user-owned, read-only inputs. Countscape never renames,
  rewrites, copies, or deletes them, including during tests and uninstall.
- The user explicitly selects a photo directory. Countscape does not crawl the
  home directory to infer one.
- Configuration, source photos, persistent output, rebuildable cache, and state
  have distinct, nonoverlapping paths with documented ownership and removal
  rules. Never use a personal username, home path, event, monitor resolution, or
  connector name as a universal default.
- Uninstall removes only validated Countscape-managed files and preserves user
  configuration and source photos.
- If integration ownership or wallpaper restoration cannot be proven, removal
  must stop safely and report the recovery step.
- Validate manifest paths against matching ownership markers and allowlisted
  filenames before removal. Validate user-unit paths and content digests before
  replacement or removal; never silently modify a foreign or user-edited unit.
- Restore light and dark GNOME URIs independently, preserving newer user choices.
  Do not delete generated output while restoration remains unresolved.

## 3. Time correctness

- Store a target with an explicit UTC offset and retain the matching IANA
  timezone.
- Calculate from aware instants, not formatted wall-clock strings or a cached
  decrementing counter.
- Require explicit user confirmation before integration starts for a target.
- Date mode requires an explicit message and IANA timezone without a fabricated
  target. Derive the displayed local calendar date from the actual aware instant.
- Define and test behavior before, at, and after the target, across daylight-
  saving transitions, suspend-like jumps, and clock corrections.
- Treat countdown refresh and photo rotation as independent schedules.
- Accept whole-minute intervals or sub-minute values that evenly divide one
  minute. Wakes with unchanged rendering inputs must reuse the render and avoid
  redundant GNOME settings writes.
- Keep installed schedule triggers aligned to the wall clock and preserve
  resume catch-up.

## 4. Rendering safety

- Preserve source-photo bytes and honor image orientation when rendering.
- Bound canvas allocations and reject invalid or overlapping layouts.
- Replace generated images and state atomically so GNOME never reads a partial
  file.
- Serialize render/apply operations and preserve the last known-good wallpaper
  when an operation fails.
- The render/apply lock does not serialize lifecycle changes. Run install,
  uninstall, and package replacement sequentially, without overlapping
  render/apply or an active timer-started service; follow
  [Lifecycle](../../docs/lifecycle.md).
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
- Use `org.gnome.Mutter.DisplayConfig.GetCurrentState` with physical modes and
  logical monitor membership; do not depend on `xrandr` under Wayland. Retain
  explicit display profiles as overrides and fallbacks.
- Prefer user-scoped integration and avoid root-owned services.
- Generate services around the installed package environment, never an editable
  source checkout or repository-local environment.

## 6. Python environment

- Target Python >=3.15.2 for v0.2 and later. The initial v0.1 release targeted
  Python 3.14.
- Use `uv` exclusively for environments, dependency changes, locks, commands,
  builds, and tests.
- Declare dependencies in `pyproject.toml` and commit `uv.lock`.
- Do not use bare `pip`, Poetry, or Conda in repository workflows.

## 7. Quality and publication

- Add automated tests with implementation and keep documentation synchronized
  with actual commands and paths.
- Clearly distinguish implemented behavior from proposed design.
- Run focused tests and static checks before claiming a change works.
- Use temporary XDG roots and fake desktop adapters in automated tests; never
  change live GNOME settings or access personal configuration and photos.
- Build releases from a clean clone and inspect source archives, wheels,
  screenshots, fixtures, metadata, and reachable Git objects for private data.
- Expand platform support only after contract fixtures and live-session
  verification exist.
- Installation must be repeatable and have an equally clear rollback and
  uninstall path.
- The checked-in example remains unconfirmed. Initialize private configuration
  or require explicit user confirmation instead of installing a sample target.
