# Configuration

`countscape init` creates a private, confirmed configuration. Prefer
`countscape configure` for supported changes; edit TOML only for settings that
the command does not expose.

The checked-in [example](../config/countscape.example.toml) is schema reference
only. It has `event.confirmed = false`, a placeholder seed, and generic paths, so
it cannot be installed as a target.

Every v0.1 config begins with:

```toml
schema_version = 1
```

Pre-v0.1 preview config and state are not migrated. Remove preview integration
with the matching preview code, recreate the config through
`countscape init --force`, and re-enter private settings. Changing the schema
number in an old file does not make its contents compatible. Forced
initialization refuses an active managed installation; uninstall it first.

## Location and XDG roots

The default configuration is:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/countscape/config.toml
```

Relative paths inside a manually written config resolve from the config file's
directory. Absolute paths are clearer for installed integration. If you use XDG
overrides, set them consistently for initialization, diagnostics, installation,
status, and uninstall, then rerun `countscape install` after changing them.

Treat the config as private. It contains the event label and instant, filesystem
paths, timezone, display details when profiles are present, and a stable random
selection seed.

## Runtime state

```toml
[runtime]
state_directory = "~/.local/state/countscape"
```

`init` resolves and records this directory. Its default honors `XDG_STATE_HOME`
at initialization time and otherwise uses `~/.local/state/countscape`. GNOME
restoration state and the installation manifest live here. Because the service
loads this recorded path from its absolute config, lifecycle state does not
depend on the systemd manager's ambient XDG environment. Validated service and
timer source files live under the state directory's `systemd/` child and are
linked into the user manager.

Choose a custom dedicated directory during initialization:

```bash
countscape init --state-directory "/path/to/runtime-state"
```

The command prompts for any omitted required event values. Runtime state is not
an ordinary presentation setting; uninstall existing integration before changing
its location.

Keep runtime state separate and nonoverlapping with the config directory, photos,
output, and cache. It must be a dedicated subdirectory, not the filesystem root
or home directory. Do not edit, move, publish, or reconstruct its files. If
config is later missing or corrupt, the known state directory from the user's own
config or backup is the explicit uninstall recovery input; see
[Lifecycle](lifecycle.md).

## Event

```toml
[event]
label = "Until the big day"
target = "2030-01-01T12:00:00+00:00"
timezone = "Etc/UTC"
confirmed = true
after_arrival_message = "It's here!"
```

`target` must be an ISO 8601 instant with an explicit UTC offset. Its wall time
and offset must agree with the named IANA `timezone`. This pairing prevents
daylight-saving ambiguity. Labels and arrival messages are trimmed, limited to
160 characters, and cannot contain control characters or newlines.

Change an event atomically through the CLI:

```bash
countscape configure \
  --event-label "Until launch" \
  --target "2030-06-01T09:00:00-04:00" \
  --timezone "America/New_York" \
  --after-message "We made it!"
```

## Storage

```toml
[wallpaper]
source_directory = "~/.local/share/countscape/backgrounds"
output_directory = "~/.local/share/countscape/generated"
cache_directory = "~/.cache/countscape"
max_canvas_pixels = 100000000
```

The paths have distinct ownership:

| Path | Owner and behavior |
|---|---|
| `source_directory` | User-owned, direct-child JPG/JPEG/PNG inputs; never modified |
| `output_directory` | Persistent Countscape output that GNOME may reference |
| `cache_directory` | Rebuildable Countscape photo-only cache |

Photo, output, cache, runtime-state, and configuration directories must be
pairwise separate and nonoverlapping. Output, cache, and state must be dedicated
subdirectories, not the filesystem root or home directory.
`max_canvas_pixels` is an allocation guard and cannot exceed 100,000,000.
It limits the generated composite canvas, not source-photo decoding. Countscape
also enforces a fixed, nonconfigurable 50,000,000-pixel ceiling on each source
image before full decode. This accepts common 48-megapixel and 8K inputs while
bounding a single RGBA expansion to about 191 MiB before decoder overhead.

Change only the photo directory through the current CLI:

```bash
countscape configure --photos "/path/to/photos"
```

Output and cache location changes require removal of existing integration first.
Run `countscape uninstall`, edit the private config, then run `doctor`, `render`,
and `install`. Do not repurpose a directory that contains unrelated files or a
foreign ownership marker, and do not delete the old marker by hand.

## Schedules

```toml
[schedule]
countdown_refresh_seconds = 60
photo_rotation_seconds = 600
```

The schedules are independent. An interval of at least 60 seconds must be a
whole number of minutes. A sub-minute value must divide 60 evenly. This keeps
systemd triggers aligned to wall-clock boundaries.

```bash
countscape configure \
  --countdown-refresh-seconds 60 \
  --photo-rotation-seconds 600
countscape install
```

Rerun `countscape install` after either interval changes so the timer is
regenerated.

## Selection seed

```toml
[selection]
seed = "private-random-value-created-by-init"
```

The seed makes photo order stable and identifies owned output/cache directories.
Do not publish or casually replace it. `init --force` preserves a valid existing
seed so ownership continuity is retained, but only after managed integration has
been uninstalled.

## Style

```toml
[style]
font = ""
overlay_position = "bottom"
margin_ratio = 0.05
font_ratio = 0.055
photo_fit = "contain"
```

- Empty `font` resolves a bold system font through fontconfig; otherwise use a
  font file path.
- `overlay_position` is `bottom` or `center`.
- `photo_fit` is `contain` (show the entire photo) or `cover` (fill and crop).
- `margin_ratio` must be greater than 0 and at most 0.25.
- `font_ratio` must be greater than 0 and at most 0.5.

The CLI exposes the most common presentation changes:

```bash
countscape configure --overlay-position center
countscape configure --photo-fit cover
```

## Display discovery and profiles

Automatic discovery is the default:

```toml
[display]
mode = "auto"
```

Countscape reads the current GNOME/Wayland layout through Mutter. A named profile
can be an automatic fallback or a forced override:

```toml
[display]
mode = "auto"
fallback_profile = "desk"

[[display.profiles.desk.monitors]]
connector = "EXAMPLE-1"
x = 0
y = 0
scale = 1.0
transform = 0
primary = true
physical_width = 1920
physical_height = 1080

[[display.profiles.desk.monitors]]
connector = "EXAMPLE-2"
x = 1920
y = 0
scale = 1.0
transform = 0
primary = false
physical_width = 1920
physical_height = 1080
```

With `mode = "auto"`, the profile is used only when live discovery fails. With
`mode = "profile"`, `fallback_profile` names the profile used unconditionally.
Profile positions are logical coordinates; widths and heights are active
physical-mode pixels; scale must be greater than 0; and the Mutter transform code
must be 0 through 7. Profiles describe one connector per logical region;
mirroring is represented only through live Mutter discovery.

Never copy connector names or dimensions as universal defaults. Use:

```bash
countscape doctor
countscape calibrate
```

Default `doctor` output reports only a redacted monitor count and broad traits
such as scaling, transforms, and mirroring. The calibration image shows the
normalized layout. Exact connectors, coordinates, dimensions, and identifiers
require `countscape doctor --include-private`; use that only for local inspection
and never share its output. Keep every explicit profile private, and treat it as
a local recipe rather than a portable value.

## Validate every change

```bash
countscape doctor
countscape render
```

If the schedule, config path, package environment, or effective XDG roots
changed, also run:

```bash
countscape install
countscape status
```
