# Tested GNOME Configurations

This page records redacted live-session evidence, not guesses about compatible
systems. The canonical support target is defined in the
[install guide](https://github.com/tylermowll/countscape/blob/main/docs/install.md).

> **Current baseline:** Countscape 0.3.0 passed the recorded date-mode checks on
> Ubuntu 26.04 GNOME/Wayland with two logical monitors and a physical transform,
> without scaling or mirroring. See the
> [v0.3 release audit](https://github.com/tylermowll/countscape/blob/main/docs/audits/v0.3.0-release.md)
> for the tested behavior and publication verification.

## Evidence table

| Countscape | Ubuntu | GNOME | Wayland | Display class | Result | Evidence date |
|---|---|---|---|---|---|---|
| 0.1.0 | 26.04 | 50.1 | Yes | Mixed orientation with transform; 125% scaling; mirrored | Pass | 2026-08-23 |
| 0.2.0 | 26.04 target | Not recorded | Target only | Fresh live baseline not run | Publication exception | 2026-10-29 |
| 0.3.0 | 26.04 | Exact version not recorded | Yes | Date mode; two logical monitors with transform; no scaling or mirroring | Limited baseline passed | 2026-10-29 |

The [v0.1 readiness audit](https://github.com/tylermowll/countscape/blob/main/docs/audits/public-repository-readiness.md)
retains the historical transformed, scaled, and mirrored evidence. The
[v0.2 release audit](https://github.com/tylermowll/countscape/blob/main/docs/audits/v0.2.0-release.md)
records its maintainer-authorized publication exception; it supplies no fresh
live baseline. The v0.3 baseline does not establish new live scaling, mirroring,
suspend/resume, or rollback/uninstall coverage.

An entry can be marked passing only when the applicable live checks in the
[release checklist](https://github.com/tylermowll/countscape/blob/main/docs/release-checklist.md)
have evidence. A limited baseline covers only the checks named in its audit.
Automated fake-adapter tests alone do not establish desktop compatibility.

## Propose an entry

Open an [issue](https://github.com/tylermowll/countscape/issues/new/choose) with:

- exact published Countscape version;
- Ubuntu and GNOME versions;
- confirmation that the session is Wayland;
- a broad display class such as single landscape, portrait, mixed scale, or
  mirrored;
- pass/fail results for `doctor`, render, apply, timer, and uninstall; and
- a redacted summary of any limitation.

Do not include usernames, paths, source photos, overlay messages, event
information, connector identifiers, monitor serials, full config, raw journals,
or diagnostics created with `doctor --include-private` or raw state created with
`status --include-private`. Review even default-redacted JSON before posting. See
[[Privacy]]. Collaborators review accepted evidence before editing this page.
