# Frequently Asked Questions

## Does Countscape upload my photos or event?

No. Normal operation is local and offline. Python and package dependencies may
need network access during installation. See [[Privacy]] and the
[security model](https://github.com/tylermowll/countscape/blob/main/docs/security-model.md).

## Does it modify or organize source photos?

No. Source photos are read-only inputs. Countscape does not rename, rewrite,
copy, or delete them, and it scans only supported files directly inside the
selected directory.

## Why are final wallpapers stored as data instead of cache?

GNOME may keep referencing the active file after ordinary cache cleanup. Final
wallpapers therefore live in persistent XDG data; the photo-only base is
rebuildable cache.

## Does Countscape require root?

No. It changes the current user's GNOME settings and creates systemd user units.
Installing missing Ubuntu host packages is outside Countscape itself.

## Can I use another desktop environment, X11, or another distribution?

The v0.1 support target is Ubuntu 26.04 GNOME/Wayland. Other environments are
not supported claims until fixtures and live evidence exist. Check
[[Tested GNOME Configurations]] for published evidence.

## Can I configure multiple simultaneous events?

Not in v0.1. One private config represents one countdown and photo pool.

## Why must the target include both an offset and an IANA timezone?

The offset identifies the exact instant; the IANA zone verifies the intended
wall time and daylight-saving rules. Countscape refuses a mismatch instead of
guessing.

## Why did a timer run without creating a new image?

Unchanged work is intentionally idempotent. If the visible countdown, selected
photo, layout, event, and style are unchanged, Countscape reuses the complete
output and avoids rewriting GNOME settings.

## Can I edit the systemd units?

Do not hand-edit them. Countscape records content digests and refuses to replace
or remove foreign or edited units silently. Change supported schedules through
the config, then rerun `countscape install`.

## What does uninstall keep?

It always preserves private config and source photos. It removes only validated
Countscape-managed integration, state, cache, and generated files when GNOME no
longer references them. See the
[lifecycle guide](https://github.com/tylermowll/countscape/blob/main/docs/lifecycle.md).

## How do I propose a wiki change?

Published wiki editing is collaborator-only. Open a
[public issue](https://github.com/tylermowll/countscape/issues/new/choose), name
the page, and use synthetic details. Do not post private data.
