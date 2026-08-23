# Package and Integration Lifecycle

Countscape has three separate lifecycle layers:

1. the package in a persistent `uv tool` environment;
2. the user-scoped systemd integration created by `countscape install`; and
3. private configuration, source photos, generated output, cache, and state.

Replace the package first, then regenerate integration. Remove integration
before removing the package. These orders keep the service executable available
and make rollback predictable.

Run lifecycle changes sequentially. `countscape install` and
`countscape uninstall` must not overlap each other, `countscape render`,
`countscape apply`, or a timer-started service run. Wait for the active command
or service invocation to finish, then retry the lifecycle command. This
operating constraint is not a crash journal or power-loss durability guarantee.

> [!IMPORTANT]
> v0.1.0 publication is pending. Use only versions shown on both the
> [release page](https://github.com/tylermowll/countscape/releases) and PyPI.

Pre-v0.1 preview config and integration-state schemas have no migration path.
The v0.1 lifecycle manifest uses schema v2 and records the persistent systemd
user-unit link directory, so uninstall does not derive that directory from later
ambient XDG variables. Remove preview integration with the matching preview code
before installing v0.1, then run `countscape init --force` and re-enter the
private target and paths. Do not change an old schema number or copy preview
state into the v0.1 runtime directory.

## Install v0.1.0

```bash
uv tool install --python 3.14 "countscape==0.1.0"
countscape --version
countscape doctor
countscape install
```

The version is intentionally pinned. A floating package name can change the
installed code without making that change explicit.

## Upgrade to an exact version

Read the target release notes first, then replace `X.Y.Z` with a published
version:

```bash
uv tool upgrade --python 3.14 "countscape==X.Y.Z"
countscape --version
countscape doctor
countscape install
countscape status
```

The final `countscape install` is required even when the tool executable path
appears unchanged. It preflights the new package and regenerates the unit content
and timer schedule from the current environment and configuration.

## Reinstall the current version

Use a forced exact-version install when the tool environment may be damaged:

```bash
uv tool install --force --python 3.14 "countscape==X.Y.Z"
countscape --version
countscape doctor
countscape install
```

## Roll back

Choose a previously published version whose release notes say it accepts the
current configuration schema. For the initial release, the concrete rollback
target is:

```bash
uv tool install --force --python 3.14 "countscape==0.1.0"
countscape --version
countscape doctor
countscape install
countscape status
```

Package rollback does not rewrite private configuration. If `doctor` rejects the
current configuration, stop before reinstalling integration and follow the
recovery notes for the target release. Do not replace configuration with the
checked-in example: its target is deliberately unconfirmed.

## Change configuration safely

Use `countscape configure` for supported event, schedule, photo, and presentation
changes. Event and style changes take effect on the next timer run. Schedule
changes require integration regeneration:

```bash
countscape configure --countdown-refresh-seconds 60
countscape install
```

If XDG base-directory overrides or the config path change, rerun `doctor` and
`install` from the intended environment. The config records its runtime state
directory at initialization; the generated service loads that exact path from
config rather than resolving `XDG_STATE_HOME` again.

Do not change the runtime state, output, or cache directory underneath installed
integration. Run `countscape uninstall` first, make the private config change,
then run `doctor`, `render`, and `install`. Never move ownership markers or state
files to imitate that lifecycle.

## Remove Countscape

Remove desktop integration while the package command is still available:

```bash
countscape uninstall
```

Uninstall stops Countscape's managed timer and service, removes only the exact
validated user-manager links and unit sources, and verifies their absence. Each
light and dark wallpaper URI is restored only while it remains
Countscape-managed; a newer user choice is preserved. If restoration cannot be
proven safe, removal stops and asks you to choose another wallpaper before
retrying.

For a nondefault config, use its absolute path:

```bash
countscape uninstall --config "/absolute/path/config.toml"
```

If config is missing or corrupt, use only the runtime state directory recorded
in the user's own config or backup:

```bash
countscape uninstall --state-directory "/known/private/state/countscape"
```

`--state-directory` is a recovery path, not a directory-discovery mechanism. Do
not guess it, scan for it, or delete units and state manually.

After integration removal succeeds, remove the tool environment:

```bash
uv tool uninstall countscape
```

Configuration and source photos are always preserved. Countscape removes only
recognized generated, cache, state, and unit files after validating ownership.
It never deletes an entire configured directory. Review the paths in
[Configuration](configuration.md) before manually removing any preserved data.

## Recover from an interrupted change

- If package replacement succeeded but integration regeneration failed, keep the
  package installed and rerun `countscape install`. Countscape restores the
  prior digest-consistent unit and manifest bytes if publishing their replacement
  fails; after publication, a systemd failure leaves the complete new generation
  available for retry. Do not delete units or state by hand.
- If the new package cannot start, force-install the previous exact version,
  then run `doctor` and `install` again.
- If uninstall stops during wallpaper restoration, choose a non-Countscape
  wallpaper in GNOME Settings and rerun `countscape uninstall`.
- If uninstall stops during unit removal or user-manager reload, leave the
  ownership markers and manifest in place and rerun `countscape uninstall`.
  Countscape retains that evidence until destructive integration cleanup
  succeeds.
- If config is missing or corrupt, recover its recorded runtime state directory
  from the user's own config backup and pass it with `--state-directory`.
- Never delete unit, state, output, or cache files to bypass an ownership error.
  Follow [Troubleshooting](troubleshooting.md) and ask for help with redacted
  details instead.
