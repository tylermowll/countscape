# Architecture

This document describes the current Countscape implementation.

For user-facing behavior, see [Installation](install.md),
[Configuration](configuration.md), [Lifecycle](lifecycle.md), and the
[security model](security-model.md).

## Product boundary

Countscape is an offline photo countdown wallpaper for Ubuntu GNOME/Wayland.
The core owns configuration validation, countdown math, photo selection,
display normalization, and rendering. Small adapters own Mutter discovery,
GNOME settings, and systemd user integration.

The v0.1 scope does not aim to support other desktop environments, fetch or sync
photos, track events over the network, or provide a general text-template
language.

## Components

1. **Configuration** loads versioned XDG-backed TOML and validates an aware event
   target, its IANA timezone, a recorded runtime-state directory,
   nonoverlapping storage paths, display profiles, independent schedules, a
   selection seed, and rendering style.
2. **Initialization and configuration** create private configuration, a stable
   random seed, and the selected photo directory; supported settings are
   rewritten atomically.
3. **Countdown** subtracts aware instants in UTC, rounds positive partial
   minutes up, and switches to the configured completion message at the target
   boundary.
4. **Photo pool** verifies direct-child JPG, JPEG, and PNG inputs without
   modifying them. A pool signature, stable seed, and independent time bucket
   determine the selected photo.
5. **Mutter adapter** reads
   `org.gnome.Mutter.DisplayConfig.GetCurrentState` through `busctl` and parses
   its typed JSON response.
6. **Display model** combines active physical modes with logical position,
   scale, transform, primary status, layout mode, and mirrored membership.
7. **Renderer** normalizes monitor geometry, performs EXIF-aware per-region
   photo fitting, wraps and sizes overlay text, caches the photo-only canvas,
   reuses unchanged complete output, and writes immutable content-identified
   PNGs atomically.
8. **GNOME adapter** reads and conditionally writes light/dark wallpaper URIs
   and picture options, retaining enough state for per-setting restoration.
9. **Runtime state** uses atomic JSON/text writes, configuration-owned directory
   markers, and a nonblocking operation lock.
10. **systemd integration** creates user-scoped service and timer units around
    the Python executable that contains the installed Countscape package.
11. **CLI** exposes initialization, diagnostics, render, apply, calibration,
    status, configuration, install, and uninstall operations.

## Data flow

```text
aware target + current aware instant ──> countdown bucket and text

photo directory + stable seed + independent bucket ──> selected photo

Mutter state ─┬─> validated logical layout ─┐
profile ──────┘                              │
                                              ▼
                                   complete render identity
                                     │              │
                              unchanged          changed
                                     │              │
                              reuse output    photo-only cache
                                                    │
                                          overlay per region
                                                    │
                                                    ▼
                                           atomic final PNG
                                     │              │
                               URI unchanged     URI changed
                                     │              │
                                no settings      GNOME apply
                                   write
```

## Configuration and storage

`countscape init` requires an ISO 8601 target with an explicit UTC offset and a
matching IANA timezone. It writes `event.confirmed = true`, generates a random
machine-local selection seed, and creates the photo directory. Existing config
is not overwritten without `--force`. A forced rewrite preserves the selection
seed when the existing configuration can be loaded, keeping managed-directory
ownership stable. Forced initialization refuses to replace config while managed
integration is active; uninstall must complete first.

Default paths honor absolute XDG base-directory overrides and otherwise use:

| Data | Default |
|---|---|
| Configuration | `~/.config/countscape/config.toml` |
| Source photos | `~/.local/share/countscape/backgrounds/` |
| Persistent final wallpapers | `~/.local/share/countscape/generated/` |
| Rebuildable photo-only cache | `~/.cache/countscape/` |
| Integration and GNOME state | `~/.local/state/countscape/` |
| User-unit sources | `~/.local/state/countscape/systemd/` |

`countscape init` records the resolved integration-state directory in
`[runtime].state_directory`. Installed commands load that path from the recorded
config, so the systemd user manager does not re-resolve lifecycle state from an
ambient `XDG_STATE_HOME`. Unit sources live under the recorded state's `systemd/`
child and are linked into the user manager. Lifecycle manifest schema v2 records
the persistent systemd user-unit link directory; uninstall validates and uses
that recorded directory rather than deriving it from later ambient
`XDG_CONFIG_HOME`. The v0.1 config requires `schema_version = 1`; pre-v0.1
preview config and state schemas are intentionally not migrated.

The photo, output, cache, runtime-state, and configuration directories must be
pairwise separate and nonoverlapping. Output, cache, and state must be dedicated
subdirectories rather than the filesystem root or home directory.
Relative paths in a manually written configuration resolve from the
configuration file's directory. Final wallpapers are persistent data, not
cache, because GNOME may still reference one after cache cleanup.

The checked-in example is deliberately inactive with `event.confirmed = false`.
It documents the schema but cannot silently install a sample target.

## Time correctness

Configuration requires `event.target` to contain an explicit UTC offset and
requires the named IANA zone to produce the same wall time and offset. Runtime
math converts the target and current time to UTC before subtraction. This
avoids wall-clock subtraction errors across daylight-saving transitions.

Positive partial minutes round up, so the display does not show completion
early. At or after the target, the configured completion message replaces the
countdown. The value is recalculated from the current instant on every run;
there is no decrementing cached counter.

Labels and completion messages are trimmed, bounded to 160 characters, and
reject control characters. The renderer wraps both fields and reduces font
size until the overlay fits or reports a controlled failure.

## Independent scheduling

`schedule.countdown_refresh_seconds` and
`schedule.photo_rotation_seconds` are positive independent intervals. Values
of at least 60 seconds must be whole minutes; a sub-minute value must evenly
divide 60. These constraints allow the installed schedule to stay aligned with
the wall clock.

The renderer derives both buckets directly from the current aware timestamp. A
countdown boundary therefore does not rotate a photo early, and a photo
boundary can trigger a render without changing the countdown bucket. Before
arrival, countdown text is calculated from the start of its bucket so it stays
stable for the configured interval. At any run on or after the target, the
completion state overrides that bucket immediately.

The generated systemd timer uses `OnActiveSec=1s` for one run after activation,
then `OnCalendar` for persistent wall-clock scheduling. When the greatest common
divisor of the intervals is at least 60 seconds, the service wakes minutely and
lets the renderer skip unchanged buckets. When a sub-minute interval is present,
the calendar trigger uses the exact greatest-common-divisor second cadence.
`Persistent=true` catches a missed calendar trigger after the user manager
resumes. Changing a schedule requires reinstalling the user integration so this
trigger is regenerated.

Scheduling and rendering are separate decisions. Each invocation computes a
render identity from bucket-derived visible countdown text and arrival state,
the selected photo and photo-pool signature, display signature, canvas, event,
and style. Raw bucket numbers are not part of that identity, so a boundary that
does not change the visible selection can remain a true no-op. If the identity
and its output file still match, the existing complete PNG is returned without
rerendering.

## Photo selection and source ownership

Photo scanning is nonrecursive and accepts `.jpg`, `.jpeg`, and `.png` files.
Each candidate is opened for verification. Oversized decoded dimensions and
Pillow decode or decompression-bomb failures are reported as controlled input
errors. A fixed 50,000,000-pixel source limit is enforced during scanning and
again immediately before full render decoding. Selection builds a deterministic
ordering from source filenames and metadata, the pool signature, and the
machine-local seed, then indexes it with the photo bucket.

Source photos are read-only inputs. Rendering honors EXIF orientation but does
not rename, rewrite, copy, or delete them. A change to supported direct-child
files changes the pool signature on the next run.

## Display discovery and normalization

Under GNOME/Wayland, physical resolution alone is insufficient. Countscape
uses the active Mutter state to retain:

- physical mode dimensions;
- logical origin;
- scale;
- transform;
- primary status;
- mirrored connector membership; and
- layout mode.

An explicit profile can override discovery or provide a fallback. Logical
regions are normalized onto a nonnegative composite canvas using the largest
active backing scale. Shared edges are rounded consistently, overlaps are
rejected, and a configurable pixel limit prevents unexpectedly large image
allocations.

The selected photo is fitted independently into every non-mirrored logical
region. `contain` preserves the whole photo with black unused space; `cover`
fills the region by cropping. Mirrored physical displays share one logical
region.

## Rendering and atomicity

The photo-only cache is invalidated by the display signature, pool signature,
selected photo, canvas dimensions, and fit mode. A later photo bucket that
selects the same unchanged photo can reuse that base. A changed final render
copies the base and draws current text on each logical region.

Images are saved to a same-directory temporary file, flushed, and moved over
the final name with `os.replace`. GNOME therefore sees either the previous
complete image or the next complete image. A file lock rejects concurrent
render or apply operations. It does not coordinate lifecycle changes:
`install` and `uninstall` must not overlap render/apply or another lifecycle
invocation and must be retried sequentially.

Final wallpapers use immutable `wallpaper-<24hex>.png` names derived from the
complete render identity. Calibrations use `calibration-<24hex>.png` names
derived from the normalized layout. A changed render therefore gets a new URI;
a true visual no-op reuses the prior file.

The apply path holds the output lock across render, GNOME settings, and cleanup.
Only after GNOME accepts the output does Countscape prune older files that match
its strict generated-name patterns. Cleanup protects the just-applied output,
any current managed path, any saved original local wallpaper path, and a small
recent set. A render-only preview is not pruned before the user has had a chance
to inspect it.

## GNOME application and restoration

Before its first settings change, Countscape atomically records the existing
`picture-uri`, `picture-uri-dark`, and `picture-options` values. Single-monitor
output uses `zoom`; multi-monitor output uses `spanned`. If the desired state is
already applied and matches Countscape's state, the adapter performs no GNOME
settings or state writes.

GNOME changes use a small persisted transaction. If a settings update or final
state write fails, the adapter attempts to restore the values observed
immediately before that apply. An incomplete transaction remains explicit
rather than being silently discarded. Recognized managed URIs are kept in a
bounded most-recent-first history so long-running minute-level use does not
grow integration state without limit.

Uninstall evaluates the light and dark URIs independently: each is restored
only while it remains a known Countscape URI. Picture options are restored only
when both URIs and the current option remain app-managed. This preserves newer
user choices.

## Installation and removal safety

Installation preflights configuration, photos, display layout, canvas size,
font, and the running Python executable before writing unit sources under the
recorded runtime state and linking them into the user manager. The service
invokes that executable with `-m countscape`; neither a repository path nor a
checkout-local virtual environment is embedded.

The stable private selection seed is also the output/cache ownership identity,
so rendering, calibration, install, and uninstall use the same marker schema.
Install separately records a stable installation ID, the exact expected unit
paths, and hashes of the generated unit contents. It refuses to overwrite
foreign or edited units. Regenerating managed integration snapshots its prior
unit generation and manifest. If publication of the complete digest-consistent
trio fails, it restores the exact prior bytes. A later systemd failure leaves the
complete new generation in place so the same command can be retried.

Uninstall validates the manifest, unit ownership, absolute directory paths,
marker application, ownership identity, and directory kind before stopping
integration. It checks the manager's loaded names and drop-ins and scans the
effective user-unit roots reported by systemd, rejecting external Countscape
units, aliases, and drop-ins. It then stops the managed timer and service,
removes only the exact user-manager links whose paths and targets were
validated, reloads the manager, and verifies that both managed unit names are
absent. GNOME restoration must then reach a resolved state; otherwise removal
stops and asks the user to choose another wallpaper before retrying.

After resolution, cleanup rereads GNOME and never deletes a currently referenced
path. It removes only recognized unit, state, cache, calibration, render
metadata, lock, and content-addressed wallpaper names—not an entire directory.
Configuration and source photos are preserved. Ownership markers and the
installation manifest remain available until destructive systemd cleanup
succeeds, keeping an interrupted uninstall safely retryable.

## Platform boundary

Countdown, selection, configuration, display normalization, and rendering are
testable without a graphical session. Mutter, GNOME, and systemd interactions
are isolated behind subprocess adapters and exercised with fakes in automated
tests.

Ubuntu 26.04 GNOME/Wayland is the initial support target. Broader support needs
saved adapter fixtures plus live verification; the current source does not make
that claim.
