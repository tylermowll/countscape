# Display Recipes

These are scenario patterns, not universal connector names or dimensions. The
[configuration guide](https://github.com/tylermowll/countscape/blob/main/docs/configuration.md)
is authoritative for schema and validation.

## Automatic discovery first

Use `display.mode = "auto"` for a normal GNOME/Wayland session. Run
`countscape doctor` for a redacted monitor count and broad layout traits, then
run `countscape calibrate` to create a numbered normalized-layout image without
reading the photo bank. Exact identifiers and geometry require
`--include-private`; use that only for local inspection and never share its
output.

## Single landscape display

Automatic discovery should require no profile. Start with
`photo_fit = "contain"` so cropping cannot be mistaken for a geometry issue.
Change to `cover` after the calibration matches the display.

## Portrait or mixed-orientation layout

Set rotation in GNOME Settings, then run `doctor` and `calibrate`. Countscape
uses the transform reported by Mutter. Avoid creating a fallback profile until
live discovery has been checked from the graphical user session.

## Mixed scale or staggered monitors

Keep GNOME's logical arrangement as the source of truth. Calibration should show
each logical region at its expected relative position. A large backing canvas is
normal when one display requires a higher scale, but Countscape enforces the
configured pixel limit.

## Mirrored displays

Mirroring is represented through live Mutter discovery: physical displays share
one logical region. Explicit profiles describe one connector per logical region
and are not a substitute for a mirrored Mutter response.

## Private fallback profile

Use an automatic fallback only when live discovery fails in an otherwise
supported session. Copy the profile shape from the canonical
[configuration guide](https://github.com/tylermowll/countscape/blob/main/docs/configuration.md),
then replace every example value with values observed locally. Keep the profile
private because it can fingerprint a machine setup.

## Propose a recipe

Open a [public issue](https://github.com/tylermowll/countscape/issues/new/choose)
with a synthetic, redacted scenario. Published wiki editing is collaborator-only.
Do not post actual connector names, serials, complete display dumps, screenshots
of personal desktops, or raw config. See [[Privacy]].
