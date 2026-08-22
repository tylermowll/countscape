# Tested GNOME Configurations

This page records redacted live-session evidence, not guesses about compatible
systems. The canonical support target is defined in the
[install guide](https://github.com/tylermowll/countscape/blob/main/docs/install.md).

> **Current evidence:** v0.1.0 live Ubuntu 26.04 validation is pending. No tested
> configuration is published yet.

## Evidence table

| Countscape | Ubuntu | GNOME | Wayland | Display class | Result | Evidence date |
|---|---|---|---|---|---|---|
| 0.1.0 pending | 26.04 | Pending | Required | Pending | Not run | Pending |

An entry can be marked passing only when the applicable live checks in the
[release checklist](https://github.com/tylermowll/countscape/blob/main/docs/release-checklist.md)
have evidence. Automated fake-adapter tests alone do not establish desktop
compatibility.

## Propose an entry

Open an [issue](https://github.com/tylermowll/countscape/issues/new/choose) with:

- exact published Countscape version;
- Ubuntu and GNOME versions;
- confirmation that the session is Wayland;
- a broad display class such as single landscape, portrait, mixed scale, or
  mirrored;
- pass/fail results for `doctor`, render, apply, timer, and uninstall; and
- a redacted summary of any limitation.

Do not include usernames, paths, source photos, event information, connector
identifiers, monitor serials, full config, raw journals, or diagnostics created
with `doctor --include-private` or raw state created with
`status --include-private`. Review even default-redacted JSON before posting. See
[[Privacy]]. Collaborators review accepted evidence before editing this page.
