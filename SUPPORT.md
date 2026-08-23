# Support

Countscape is a focused Ubuntu GNOME desktop tool. This document explains what
the project supports and how to ask for help without publishing private data.

## Current support boundary

Published v0.1 releases are community-supported. A version counts as published
only when the exact version appears on both the GitHub release page and PyPI;
questions about other source revisions are handled as contributor issues.

The v0.1 target is:

- Ubuntu 26.04;
- GNOME on Wayland;
- Python 3.14 in a persistent `uv tool` installation;
- systemd user services; and
- local direct-child JPG, JPEG, or PNG photos.

Other distributions, X11, other desktop environments, containers, system-wide
services, remote photo providers, multiple simultaneous events, and graphical
configuration tools are outside the v0.1 support claim. Useful reports are still
welcome when they clearly identify an unsupported environment.

Support is community-maintained and has no guaranteed response time.

## Before opening an issue

1. Read [Installation](docs/install.md) or
   [Troubleshooting](docs/troubleshooting.md).
2. Confirm the exact installed version with `countscape --version`.
3. Run `countscape doctor` locally.
4. Check `countscape status` and the user-service journal when integration is
   involved.
5. Reproduce with synthetic event text and generated placeholder images when
   possible.
6. Search existing issues.

Open a public issue at
[GitHub Issues](https://github.com/tylermowll/countscape/issues/new/choose) only
after reviewing the privacy checklist below. Propose wiki corrections through
the same issue path; published wiki editing is restricted to collaborators.

## Safe issue template

```text
Countscape version:
Ubuntu version:
GNOME Shell version:
Session type (Wayland/X11):
Install method:
Command that failed:
Expected behavior:
Observed behavior:
Minimal reproduction using synthetic data:
Redacted doctor summary:
Redacted status summary (when integration is involved):
Redacted relevant journal lines:
Display class (single/multiple/mirrored; no serials):
```

Default `countscape doctor` and `countscape status` output, including JSON, is
redacted, but review either before posting. Never post either command's
`--include-private` output. Private doctor output contains event, path, font, and
display details; private status output contains raw timer and render state.
Include the smallest relevant journal excerpt, not an entire session log.

## Privacy checklist

Remove or replace:

- real photos, generated wallpapers, and screenshots containing personal data;
- event labels, dates, timezones, and completion messages;
- usernames, home paths, hostnames, and custom data roots;
- photo filenames and pool signatures;
- monitor serials, connector identifiers, and distinctive layouts;
- config seeds, ownership IDs, installation IDs, manifests, and state; and
- unrelated journal entries, tokens, credentials, or private correspondence.

Use generic placeholders such as `~/<redacted>`, `EXAMPLE-1`, and an invented
future event. Never upload a full private config.

## Security and conduct

If the issue could allow unintended access, command execution, file deletion,
data disclosure, ownership bypass, or unsafe restoration, do not report it
publicly. Follow [SECURITY.md](SECURITY.md).

For conduct concerns, follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Do not put
private incident details in a public support issue.
