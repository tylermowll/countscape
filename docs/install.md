# Install Countscape

This is the canonical first-install guide for Countscape v0.1. For upgrades,
rollbacks, reinstalls, and removal, use [Lifecycle](lifecycle.md).

> [!IMPORTANT]
> v0.1.0 publication is pending. The package-index command below becomes valid
> only after v0.1.0 appears on the
> [GitHub release page](https://github.com/tylermowll/countscape/releases) and
> PyPI. Do not treat an untagged source revision as a published release.

## Requirements

- Ubuntu 26.04
- GNOME running on Wayland
- a systemd user manager
- [`uv`](https://docs.astral.sh/uv/)
- `busctl`, `fc-match`, `gsettings`, `systemctl`, and `systemd-analyze`

Countscape does not need root. A normal Ubuntu GNOME installation generally
provides the host commands. You can check them without changing the system:

```bash
command -v busctl
command -v fc-match
command -v gsettings
command -v systemctl
command -v systemd-analyze
```

## 1. Install an exact release

Use a persistent `uv tool` environment because the systemd service must keep a
stable Python executable after the shell exits:

```bash
uv tool install --python 3.14 "countscape==0.1.0"
countscape --version
```

Do not use an ephemeral runner for installation. Do not install an editable
checkout: `countscape install` deliberately rejects one.

## 2. Create private configuration

Initialize an aware target whose explicit offset agrees with its IANA timezone:

```bash
countscape init \
  --target "2030-01-01T12:00:00+00:00" \
  --timezone "Etc/UTC" \
  --label "Until the big day" \
  --after-message "It's here!"
```

If the target or timezone is omitted, Countscape prompts for it. Existing
configuration is preserved unless `--force` is explicitly supplied. Prefer
`countscape configure` for ordinary changes. `init --force` refuses to replace
config while managed integration is active; run `countscape uninstall` first.

The command creates the default photo directory:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/countscape/backgrounds/
```

It also writes `schema_version = 1` and records an absolute runtime-state
directory in the private config. The default is resolved from
`${XDG_STATE_HOME:-$HOME/.local/state}/countscape/` at initialization time, so
the installed service loads a durable path from config instead of depending on a
later ambient XDG state setting.

You can choose dedicated locations during initialization:

```bash
countscape init \
  --target "2030-01-01T12:00:00+00:00" \
  --timezone "Etc/UTC" \
  --photos "/path/to/photos" \
  --output "/path/to/generated-wallpapers" \
  --cache "/path/to/rebuildable-cache" \
  --state-directory "/path/to/runtime-state"
```

Photo, output, cache, runtime-state, and configuration directories must be
distinct and nonoverlapping. Output, cache, and state must be dedicated
subdirectories, not the filesystem root or home directory. `--state-directory`
records the durable location used for the install manifest, GNOME restoration
state, and linked user-unit sources; use the same private config for later
status and uninstall operations.

For a nondefault config file, pass the same absolute path to each command:

```bash
countscape init --config "/absolute/path/config.toml"
countscape doctor --config "/absolute/path/config.toml"
countscape install --config "/absolute/path/config.toml"
```

The first command prompts for any omitted required event values.

> [!WARNING]
> Pre-v0.1 preview config and integration state are unsupported and are not
> migrated. Remove preview integration with the matching preview code before
> installing v0.1, then recreate configuration with `countscape init --force`
> and re-enter the private target and paths. Do not add `schema_version = 1` to
> an old file or move old state into the new runtime directory.

## 3. Add photos

Add at least one `.jpg`, `.jpeg`, or `.png` directly inside the selected photo
directory. Scanning is nonrecursive. Countscape verifies supported files but
does not rename, rewrite, copy, or delete them.

## 4. Diagnose and preview

Run non-mutating diagnostics:

```bash
countscape doctor
```

Then render without changing GNOME:

```bash
countscape render
```

The command prints the generated image path. Inspect the image before enabling
automatic application. Use `countscape calibrate` if the display arrangement
needs investigation.

## 5. Install user integration

```bash
countscape install
countscape status
```

Installation preflights the configuration, photo pool, display layout, canvas
limit, font, and installed Python executable. It stores a oneshot service and
persistent wall-clock timer under `[runtime].state_directory/systemd/`, then
links them into the systemd user manager. No system service or root-owned file is
created.

To write the units without starting the timer:

```bash
countscape install --no-start
```

Inspect the service and timer with:

```bash
systemctl --user status countscape.timer
systemctl --user list-timers countscape.timer
journalctl --user-unit countscape.service
```

Continue with [Configuration](configuration.md), [Lifecycle](lifecycle.md), or
[Troubleshooting](troubleshooting.md).
