# Troubleshooting

Start with non-mutating diagnostics and keep private data out of public reports.
For project support boundaries and an issue template, see [SUPPORT.md](../SUPPORT.md).

## Safe diagnostic sequence

```bash
countscape --version
countscape doctor
countscape status
systemctl --user status countscape.timer
journalctl --user-unit countscape.service
```

Default `countscape doctor` and `countscape status` output is redacted; JSON also
includes a privacy marker. Review either before sharing. Never publish either
command's `--include-private` output: private doctor output adds event, path,
font, photo, and display details, while private status output exposes raw timer
and render state.

## Configuration does not exist

For a first setup with no existing integration, create config with:

```bash
countscape init
```

If you intentionally use a nondefault file, pass its same absolute path to
`doctor`, `render`, `configure`, and `install`. The installed service records the
config path supplied during installation.

If integration already exists, do not initialize over the missing config. Obtain
the exact runtime state directory from the user's own config or backup and use
the explicit removal recovery path first:

```bash
countscape uninstall --state-directory "/known/private/state/countscape"
```

Do not guess or search for a state directory, and do not delete units or state
manually. Pre-v0.1 preview config/state are not migrated; remove preview
integration with its matching code, then recreate configuration through v0.1
`countscape init --force`.

The same ordering applies to any forced reinitialization: `init --force` refuses
while managed integration is active, so complete `countscape uninstall` first.

## Target and timezone disagree

The ISO 8601 target needs an explicit offset and an IANA zone that describes the
same wall time and offset. Check daylight-saving status on the target date, not
just the current date. For example:

```text
target = "2030-06-01T09:00:00-04:00"
timezone = "America/New_York"
```

Use `countscape configure --target ... --timezone ...` to update both together.

## No usable photos

- Put at least one `.jpg`, `.jpeg`, or `.png` directly in the configured photo
  directory.
- Subdirectories are not scanned.
- Confirm the current directory with your private config; do not paste its path
  into a public issue without redaction.
- Remove or repair images that normal image verification cannot open. Countscape
  leaves every source file untouched.

## A host command is missing

`doctor` checks `busctl`, `fc-match`, `gsettings`, `systemctl`, and
`systemd-analyze`. These normally come from the Ubuntu GNOME base system. Install
the missing Ubuntu package through your normal system-management process, then
rerun `doctor`. Countscape does not attempt privileged host-package installation.

## Mutter display discovery fails

Confirm that the command runs inside the graphical user's GNOME/Wayland session.
Remote shells and non-GNOME sessions may not have the required session bus.

```bash
countscape doctor
countscape calibrate
```

If live discovery is unavailable in an otherwise supported session, configure a
private fallback profile using [Configuration](configuration.md). Do not publish
raw connector names or a complete monitor dump without reviewing it.

## The layout or crop looks wrong

1. Run `countscape calibrate` and inspect the printed image path.
2. Run `countscape calibrate --apply` only if you want to inspect it as the live
   wallpaper.
3. Verify monitor order, scaling, portrait transforms, and mirroring in GNOME
   Settings.
4. Try `countscape configure --photo-fit contain` to distinguish cropping from a
   layout issue.
5. Run `countscape apply` afterward to restore the countdown wallpaper.

## The timer is inactive

Regenerate integration and inspect it:

```bash
countscape doctor
countscape install
countscape status
systemctl --user status countscape.timer
systemctl --user list-timers countscape.timer
```

Do not hand-edit the generated units. Countscape validates their content digest
and refuses to overwrite or remove foreign or modified files silently.

## A service run failed

Read the user-service journal locally:

```bash
journalctl --user-unit countscape.service
```

Common causes are a moved config, empty or invalid photo pool, unavailable
graphical session, invalid display response, missing font, or a changed managed
directory marker. Correct the underlying error and run `countscape apply`; rerun
`countscape install` when the config path, schedule, package, or XDG roots changed.

## Nothing changed after a timer run

That can be correct. Countdown and photo selection use independent timestamp
buckets. When visible text, selected photo, pool, layout, event, and style are
unchanged, Countscape reuses the complete output and avoids rewriting the same
GNOME URI.

## Another operation is already running

Countscape serializes render and apply operations. Wait for the current oneshot
service invocation to finish, then retry. If the message persists, inspect the
user-service status and journal rather than deleting the lock or state files.

## Uninstall stops before cleanup

Countscape stops safely when it cannot prove that wallpaper restoration or file
removal is safe. Choose a non-Countscape wallpaper in GNOME Settings, then retry:

```bash
countscape uninstall
```

Do not manually delete a generated wallpaper that GNOME may still reference.
Configuration and source photos remain preserved.

## Custom XDG roots do not match

`init` resolves `[runtime].state_directory` from the effective `XDG_STATE_HOME`
and stores it in config. The service loads that recorded path from config. Run
initialization, diagnostics, installation, status, and uninstall with the same
intended config and XDG roots. After changing an override:

```bash
countscape doctor
countscape install
countscape status
```

Do not move ownership markers or integration state between roots by hand.

## Redact before opening an issue

Review every line and attachment. Replace or remove:

- usernames, home paths, hostnames, and custom XDG paths;
- event labels, targets, timezones, and completion messages;
- photo filenames, signatures, contents, and generated wallpapers;
- monitor serials, connector identifiers, and distinctive layout details;
- journal lines unrelated to Countscape;
- configuration seeds, ownership IDs, installation IDs, and state-file content.

Use generated placeholder images for visual reproductions. If the problem may be
a vulnerability, do not open a public issue; follow [SECURITY.md](../SECURITY.md).
