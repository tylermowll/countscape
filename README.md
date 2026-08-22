# Countscape

Countscape turns a folder of your photos into a GNOME wallpaper with a
timezone-aware countdown overlaid on every display.

It is designed for a small, dependable job: work offline, leave source photos
untouched, understand mixed-orientation monitor layouts, and replace generated
wallpapers atomically.

> [!IMPORTANT]
> Countscape is a development preview. The package, setup flow, renderer, and
> user-scoped integration are implemented, but there is no tagged or PyPI
> release yet. A tagged release still needs live validation in a supported
> GNOME session and a final CI and artifact review of the release commit.

## Features

- A configurable event label, completion message, aware target instant, and
  IANA timezone.
- Independent countdown-refresh and photo-rotation intervals, with defaults of
  one minute and ten minutes.
- Local JPG, JPEG, and PNG photo pools with deterministic rotation.
- EXIF-aware `contain` or `cover` fitting on each logical monitor region.
- GNOME/Wayland layout discovery through Mutter, including physical mode,
  logical position, scale, transform, primary status, and mirroring.
- Text wrapping and adaptive sizing for long labels and small display regions.
- Atomic, content-identified generated files, reusable render output, and
  protection against concurrent render/apply operations.
- Read-only diagnostics, preview rendering, display calibration, GNOME apply,
  configuration, status, installation, and uninstall commands.
- User-scoped systemd integration that runs the installed package, not a source
  checkout.
- Conditional, per-URI restoration of the wallpaper that was active before
  Countscape.

## Supported platform

The initial support target is **Ubuntu 26.04 with GNOME/Wayland, systemd user
services, and Python 3.14**. Pure logic and desktop-adapter contracts run in
automated tests; final desktop integration checks require a real GNOME user
session. Other GNOME distributions may work, but they are not supported claims
yet.

Countscape uses the host tools `busctl`, `fc-match`, `gsettings`, `systemctl`,
and `systemd-analyze`. Countdown, selection, and rendering remain offline after
the Python dependencies are installed.

## Install the development preview

Install [`uv`](https://docs.astral.sh/uv/), clone this repository, and create an
isolated tool installation:

```bash
git clone https://github.com/tylermowll/countscape.git
cd countscape
uv tool install .
countscape --help
```

The tool environment contains the installed application, so the repository is
not a runtime dependency. A pinned release installation command will replace
this development flow after the first tag is published.

## Set up your countdown

Run `init` and provide a target whose explicit UTC offset agrees with its IANA
timezone:

```bash
countscape init \
  --target "2030-01-01T12:00:00+00:00" \
  --timezone "Etc/UTC" \
  --label "Until the big day" \
  --after-message "It's here!"
```

If `--target` or `--timezone` is omitted, Countscape prompts for it. The command
creates private configuration and a stable selection seed, then creates the
default photo directory:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/countscape/backgrounds/
```

Add at least one `.jpg`, `.jpeg`, or `.png` file directly inside that directory.
Countscape does not search elsewhere, recurse into subdirectories, copy the
photos, or modify them.

You may choose locations and schedules during initialization:

```bash
countscape init \
  --target "2030-01-01T12:00:00+00:00" \
  --timezone "Etc/UTC" \
  --photos "/path/to/photos" \
  --output "/path/to/generated-wallpapers" \
  --cache "/path/to/rebuildable-cache" \
  --countdown-refresh-seconds 60 \
  --photo-rotation-seconds 600
```

The photo, output, and cache directories must not be the same, contain one
another, or otherwise overlap. Output and cache must be dedicated
subdirectories—not the filesystem root or your home directory—and configuration
cannot live inside the photo, output, or cache directory. Existing configuration
is preserved unless the `--force` flag is explicitly used. Prefer
`countscape configure` for an existing setup; `--force` replaces the private
configuration but retains a valid existing selection seed for ownership
continuity.

The checked-in
[`config/countscape.example.toml`](https://github.com/tylermowll/countscape/blob/main/config/countscape.example.toml)
is reference documentation. It deliberately has `event.confirmed = false` and
cannot run as-is; `countscape init` writes a private, confirmed configuration.

## Preview and install

Run read-only diagnostics first:

```bash
countscape doctor
```

Render without changing GNOME, then inspect the printed output path:

```bash
countscape render
```

Install and start the user timer only after reviewing the preview:

```bash
countscape install
```

Installation preflights the configuration, photo pool, current or fallback
display layout, canvas limit, font, and installed Python executable before it
creates `countscape.service` and `countscape.timer` under the systemd user
directory. It does not require root.

## Operate and customize

```bash
countscape status
countscape doctor --json
countscape apply
countscape calibrate
countscape calibrate --apply
journalctl --user-unit countscape.service
systemctl --user list-timers countscape.timer
```

`calibrate` creates a numbered layout image without reading the photo bank. If
you apply it, run `countscape apply` afterward to return to the countdown.

The most common customizations are available without editing TOML:

```bash
countscape configure --event-label "Until launch"
countscape configure --after-message "We made it!"
countscape configure --overlay-position center
countscape configure --photo-fit cover
countscape configure --photos "/path/to/another-photo-folder"
countscape configure \
  --countdown-refresh-seconds 60 \
  --photo-rotation-seconds 600
countscape configure \
  --target "2030-06-01T09:00:00-04:00" \
  --timezone "America/New_York"
```

Rerun `countscape install` after changing either schedule so the user timer is
regenerated. Changing an event or presentation setting takes effect on the next
timer run.

### Scheduling behavior

Countdown text and photo selection use separate timestamp buckets. Intervals of
at least 60 seconds must be whole minutes. A sub-minute interval must divide 60
evenly, which keeps short development schedules aligned with the wall clock.

The persistent timer uses `OnActiveSec=1s` for one run shortly after activation,
then `OnCalendar` for a wall-clock minutely trigger or an exact sub-minute
trigger based on the greatest common divisor when a shorter interval is
configured. `Persistent=true` catches a missed calendar trigger after the user
manager resumes. Either bucket can therefore advance independently.

Each run recalculates from the current aware instant. If the bucket-derived
countdown text and arrival state, selected photo and pool, layout, event, and
style are unchanged, Countscape reuses the complete existing output—even if a
bucket advanced without changing anything visible. A changed render receives a
new immutable `wallpaper-<24hex>.png` filename. Applying the same URI is
idempotent, so unchanged GNOME settings are not rewritten; after a successful
apply, older recognized generated files are pruned while the active output and
any saved local original are protected.

Countdown text is calculated at the start of its current bucket so it remains
stable for the configured refresh interval. An arrival detected at any service
run overrides that bucket immediately. Very small allowed intervals create a
correspondingly frequent user timer; the defaults are the recommended starting
point.

## Files and ownership

Defaults honor the XDG base-directory environment variables:

| Data | Default location | Uninstall behavior |
|---|---|---|
| Configuration | `${XDG_CONFIG_HOME:-$HOME/.config}/countscape/config.toml` | Preserved |
| Source photos | `${XDG_DATA_HOME:-$HOME/.local/share}/countscape/backgrounds/` | Preserved and never modified |
| Final wallpapers | `${XDG_DATA_HOME:-$HOME/.local/share}/countscape/generated/` | Recognized managed files removed only when safe |
| Rebuildable base cache | `${XDG_CACHE_HOME:-$HOME/.cache}/countscape/` | Recognized managed files removed |
| Integration state | `${XDG_STATE_HOME:-$HOME/.local/state}/countscape/` | Managed install state removed |
| User units | `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/` | Countscape units removed |

Final wallpapers live in XDG data rather than cache because GNOME may still
reference them after ordinary cache cleanup. Output and cache directories
receive ownership markers tied to the private configuration seed. Install state
records that identity; removal refuses a directory whose marker does not match.

## Uninstall

```bash
countscape uninstall
```

Uninstall stops and removes Countscape's user units. Each light or dark
wallpaper URI is restored only if that URI still points to a Countscape-managed
file; a newer wallpaper choice is preserved. Picture options are restored only
when both URIs and the option are still app-managed.

Removal validates the install manifest, unit-file digests, output/cache markers,
and current GNOME paths before deleting runtime files. If wallpaper restoration
cannot be resolved safely, uninstall stops and asks you to choose another
wallpaper and run it again. It does not guess or delete a file GNOME still
references.

Configuration and source photos are always preserved. Generated output is
removed conservatively: Countscape requires matching ownership state and never
deletes an entire configured directory.

To remove the development tool environment afterward:

```bash
uv tool uninstall countscape
```

## Development

```bash
uv sync --locked
uv run python tools/privacy_check.py
uv run pytest
uv run ruff check .
uv build
```

Tests use temporary photos, XDG directories, configuration, and fake desktop
adapters. They do not change the live wallpaper or user units.

See
[Architecture](https://github.com/tylermowll/countscape/blob/main/docs/architecture.md)
for the design and the
[Implementation Plan](https://github.com/tylermowll/countscape/blob/main/docs/implementation-plan.md)
for the remaining release gates. Contributions are welcome; start with
[CONTRIBUTING.md](https://github.com/tylermowll/countscape/blob/main/CONTRIBUTING.md).
Report security issues using
[SECURITY.md](https://github.com/tylermowll/countscape/blob/main/SECURITY.md).

Countscape is available under the
[MIT License](https://github.com/tylermowll/countscape/blob/main/LICENSE).
