# AGENTS.md

## Repository identity

Countscape is an offline photo countdown wallpaper for Ubuntu GNOME/Wayland.
Read `.agents/spec/constitution.md` before changing the project.

The repository is intentionally public and must contain no personal photos,
private event details, machine-local configuration, secrets, generated
wallpapers, caches, or absolute user paths.

## Environment and dependencies

- Target Python 3.14 on Ubuntu 26.04.
- Use `uv` exclusively for Python environments, dependencies, commands, locks,
  builds, and tests. Do not use bare `pip`, Poetry, or Conda.
- Declare dependencies in `pyproject.toml`, commit `uv.lock`, and run repository
  commands through `uv run`.

## Non-negotiable implementation rules

- Represent every target as a timezone-aware instant and retain its IANA zone.
  Never perform countdown math with naive local datetimes.
- Treat source photos as immutable user data. Never rename, rewrite, copy, or
  delete them, including during tests and uninstall.
- Keep personal configuration, state, photos, caches, and generated output out
  of source control and release artifacts.
- Keep config, source photos, persistent output, rebuildable cache, and state in
  distinct, nonoverlapping paths with documented ownership.
- Never hard-code a username, home directory, checkout path, event, monitor
  resolution, or connector name as a universal default.
- Keep countdown refresh and photo selection as independent timestamp buckets.
  Accept whole-minute intervals or sub-minute values that evenly divide one
  minute so wall-clock scheduling stays exact. If the user timer wakes more
  often than a bucket changes, unchanged renders and GNOME applies must remain
  idempotent.
- Replace generated wallpaper and state files atomically so GNOME never reads a
  partial file.
- Prefer user-scoped `systemctl --user` and GNOME `gsettings`; do not require
  root when user-session facilities suffice.
- Generate services around the installed package environment, never a source
  checkout or repository-local `.venv`.
- Keep GNOME, Mutter, and systemd behavior behind small adapters so core logic
  remains testable without a graphical session.
- On GNOME/Wayland, discover active layout through the read-only Mutter
  `org.gnome.Mutter.DisplayConfig.GetCurrentState` interface. Use physical
  mode, logical position, scale, transform, primary status, layout mode, and
  mirroring together. Do not depend on `xrandr` under Wayland.
- Retain explicit display profiles as overrides and fallbacks.
- Validate manifest paths against matching ownership markers and allowlisted
  filenames before uninstalling anything.
- Validate generated user-unit paths and content digests; never replace or
  remove a foreign or user-edited unit silently.
- Restore GNOME URIs independently so a newer user choice is preserved.
- Stop removal when GNOME restoration remains unresolved rather than deleting a
  possibly referenced file.
- Keep the application functional offline after dependencies are installed.

## Product status

The package, `countscape init`, XDG data split, independent second-based
schedules, render reuse, idempotent GNOME apply, installed-package service, and
ownership-marker uninstall are implemented. Do not describe PyPI publication,
a tagged release, broader platform support, or live release validation as
complete until evidence exists.

The checked-in example intentionally has `event.confirmed = false`. Do not turn
it into an installable default target; user configuration must be generated or
explicitly confirmed.

## Verification

Run checks appropriate to the change, normally:

```bash
uv sync --locked --all-groups
uv run python tools/privacy_check.py --history
uv run python tools/check_markdown_links.py
uv run ruff format --check .
uv run ruff check .
uv run pytest --cov=countscape --cov-branch --cov-report=term-missing --cov-config=.coveragerc
uv build --no-sources --clear --out-dir dist
uv run python tools/release_check.py --artifacts dist/*.whl dist/*.tar.gz
uv run python tools/privacy_check.py --history --artifacts dist/*.whl dist/*.tar.gz
```

- Test before, at, and after the target and across daylight-saving changes.
- Test missing, empty, invalid, portrait, landscape, transparent, and long-text
  image/render inputs.
- Test single, mixed-orientation, scaled, transformed, and mirrored layouts.
- Test independent interval boundaries, unchanged reuse, and backward or
  suspend-like clock changes.
- Use temporary XDG roots and fake desktop adapters in automated tests.
- Never let tests change live GNOME settings, source photos, or user config.
- Pair installation documentation and tests with update, rollback, and
  uninstall coverage.
- Treat live GNOME checks as manual platform evidence, not portable CI claims.
- Review package members and reachable Git objects for privacy before
  publication.
