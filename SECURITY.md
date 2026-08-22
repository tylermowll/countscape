# Security Policy

## Supported versions

Countscape v0.1.0 publication is pending. Until it is published, security fixes
target the default branch and no packaged release is a supported security line.
After publication, this table must be updated as part of every release:

| Version | Supported |
|---|---|
| Default branch before v0.1.0 publication | Yes |
| Published v0.1 line | Pending |
| Unpublished builds and older lines | No |

Install only exact versions shown on both the
[GitHub release page](https://github.com/tylermowll/countscape/releases) and
PyPI. See the local-data and integration boundaries in
[docs/security-model.md](docs/security-model.md).

## Report a vulnerability

Do not open a public issue containing vulnerability details.

Use the repository's **Security** tab and **Report a vulnerability** to submit a
private report. If private vulnerability reporting is unavailable, open a
minimal public issue asking maintainers to enable a private contact path. Do not
include reproduction steps, exploit details, config, logs, secrets, screenshots,
photos, paths, event information, or affected user data in that issue.

Include privately, when possible:

- the affected published version or commit;
- the supported Ubuntu/GNOME environment used;
- impact and preconditions;
- minimal reproduction steps using synthetic data;
- whether source photos, config, state, wallpaper settings, or managed files were
  exposed or changed; and
- any safe mitigation you have identified.

Maintainers will assess the report, keep sensitive details private while a fix
is prepared, coordinate disclosure where appropriate, and credit reporters who
request attribution. No fixed response-time guarantee is offered, but public
disclosure should wait until a safe fix and release plan are available.

## In scope

Relevant issues include:

- command or generated-unit injection;
- unsafe event, config, photo, output, cache, or XDG path handling;
- source-photo mutation or unintended file deletion;
- exposure of user photos, event data, config, state, or paths;
- foreign-unit replacement or unsafe wallpaper restoration;
- ownership-marker, manifest, digest, or filename validation bypasses;
- malformed image, TOML, Mutter response, GNOME value, or state-file handling
  that escapes documented boundaries; and
- dependency behavior that materially compromises Countscape's local boundary.

## Expected behavior

Countscape intentionally reads direct-child images from a user-selected folder,
creates persistent local wallpaper output, reads the current GNOME display
layout, changes the current user's light/dark wallpaper settings, and manages a
user-scoped oneshot service and timer. Those actions are expected only for paths
and integration the user configured.

It should not require root, modify or discover unrelated source photos, upload
data, expose a network service, overwrite foreign units, or remove unmanaged
files. Ordinary setup failures and support questions belong in
[SUPPORT.md](SUPPORT.md), not private vulnerability reporting.
