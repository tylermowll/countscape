# Public Repository Readiness

Status: **public-repository checkpoint verified on 2026-08-22**; **v0.1 release
remains blocked**.

This is the current, cross-machine handoff for Countscape. It replaces the
earlier dated working audit. Live GitHub settings remain independently
verifiable because repository rules, environments, and Wiki publication do not
live in the source checkout.

## Scope

This audit answers two separate questions:

1. Is the source repository safe, understandable, and maintainable as a public
   project?
2. Is Countscape v0.1 ready to publish as a tagged GitHub and PyPI release?

The first is the active goal. The second remains a later release gate.

## Public-data conclusion

No private photos, event details, machine-local configuration, home paths,
secrets, generated wallpapers, caches, or personal email addresses were found
in the worktree or reachable repository history. The repository necessarily
contains deliberate public attribution: the GitHub owner in repository URLs and
CODEOWNERS, plus normal Git author display names. Commit email metadata uses
GitHub/noreply addresses.

The hero and social-preview graphics are synthetic, reviewed public assets with
exact-byte allowlisting and stripped metadata. Neither contains personal media
or event data.

## Product-evidence boundary

The checked-in hero and social-preview graphics are marketing assets, not
Countscape runtime output. This audit records only a redacted textual summary
of the supported-host baseline below; it does not publish the generated
wallpaper or a live-session screenshot. The artwork must not be treated as
runtime or platform validation.

## Completed public surface

- Canonical installation, configuration, lifecycle, troubleshooting, security,
  architecture, contribution, support, conduct, and release documentation.
- Privacy-first issue forms, pull-request guidance, CODEOWNERS, Dependabot, CI,
  CodeQL, and repository-native pre-commit and pre-push gates.
- A six-page GitHub Wiki whose reviewable publication source is tracked under
  `wiki/`.
- SHA-pinned and allowlisted GitHub Actions, read-only default workflow tokens,
  secret scanning and push protection, private vulnerability reporting, and
  immutable releases.
- A protected `pypi` environment limited to `v*` tags and maintainer review.
- Restartable release automation that verifies the tag, exact artifacts,
  checksums, deterministic release notes, PyPI state, and immutable GitHub
  release state before advancing.

## Engineering boundary

Countscape v0.1 is a hard cutover for Python 3.14 on Ubuntu 26.04 GNOME/Wayland.
It has no pre-release migration layer. Source photos remain immutable. Runtime
state, generated output, cache, configuration, user units, and the per-user
lifecycle manifest have separate documented ownership rules. Manifest schema v2
records the persistent systemd user-unit link directory so uninstall does not
derive it from later ambient XDG variables.

The operating-system user account is the local trust boundary. The current
implementation validates managed-directory ownership, unit paths and digests,
GNOME restoration, and allowlisted cleanup. Installation regeneration keeps the
managed unit sources and manifest digest-consistent: an incomplete publication
restores their exact prior bytes, while a later systemd failure leaves the
complete new generation available for retry. Uninstall retains the ownership
evidence needed for a clean retry until its destructive systemd work succeeds.
These focused guarantees do not claim power-loss transactions or recovery for
arbitrary systemd topologies.

The pure countdown, configuration, display, selection, and rendering core has
strong local automated evidence. The GNOME/systemd lifecycle is defensively
designed and now has targeted injected-failure coverage for regeneration and
destructive uninstall retry paths. Full live platform validation remains a
separate release gate.

## Verification evidence

The final local gate used Python 3.14.4 and the committed `uv.lock`:

- worktree, reachable-history, staged-content, and release-artifact privacy
  checks passed;
- all 24 local Markdown documents passed link validation;
- Ruff reported all 59 Python files formatted and no lint findings;
- all 347 tests passed with 90.39% branch coverage;
- `countscape-0.1.0-py3-none-any.whl` and
  `countscape-0.1.0.tar.gz` passed exact-set, metadata, and privacy validation;
  and
- isolated installs of both distributions exposed the expected `countscape
  0.1.0` version and working help command.

The aggregate branch-enabled coverage gate is useful but not uniform:
`install.py`, which owns the highest-risk lifecycle mutations, reported 81.1%,
and `render.py` reported 83.1%. The required lifecycle work therefore needs
targeted injected-failure tests rather than relying on the aggregate percentage
alone.

Live GitHub settings were rechecked on 2026-08-22. The active `main` ruleset
requires strict `Ubuntu 26.04 / Python 3.14` and `Analyze Python` checks, one
code-owner approval, last-push approval, resolved review threads, linear squash
merges, and deletion/non-fast-forward protection. The active `v*` tag ruleset
protects creation, update, deletion, and non-fast-forward changes. The `pypi`
environment accepts only `v*` tags and requires maintainer review. These
controls cannot be proven by cloning the repository alone.

## Supported-host baseline

The final wheel was exercised on 2026-08-22 on Ubuntu 26.04, GNOME 50.1,
Wayland, and a two-logical-monitor mixed-orientation layout with a physical
transform. A synthetic public source rendered to the discovered 3120x1920
canvas and was visually reviewed. `doctor`, unchanged apply reuse, live timer
execution, schedule regeneration from 5 to 10 and back to 5 seconds,
installation-identity preservation, unchanged reinstall, and reinstall under a
different ambient `XDG_CONFIG_HOME` all passed.

Temporary alias and drop-in fixtures under an external effective systemd user
unit root were each rejected before the timer stopped or managed evidence
changed. The final uninstall restored the exact prior GNOME-setting digest,
preserved the synthetic source bytes and modification time, removed the
validated units and links, and preserved configuration. The temporary tool
environment, fixtures, and generated output were then removed; no live
wallpaper or screenshot was retained in the repository.

This baseline does not cover a live scaled or mirrored layout and therefore is
not the complete release-platform matrix.

## Separate v0.1 release blockers

These do not block completing the public source repository:

- register the PyPI Trusted Publisher and confirm the project namespace;
- complete the desktop-mutating Ubuntu 26.04 matrix for scaled and mirrored
  layouts with reviewed privacy-safe evidence; the baseline above covers the
  current mixed-orientation and transformed layout, and the generated wallpaper
  artifact must never be published;
- replace `Pending` in the v0.1 changelog with the release date;
- create the protected `v0.1.0` tag only after every release gate passes.

Uploading the reviewed social-preview PNG in GitHub's repository settings is
optional repository polish. It affects link cards when the repository is shared,
not Countscape behavior, packaging, security, or v0.1 publication readiness.

Never replace an immutable published artifact. Correct a released artifact with
a new version.

## Completed focused robustness work

The follow-up robustness pass deliberately kept the design small and explicit:

- make existing-install regeneration retry-safe: restore the exact prior unit
  and manifest bytes if publication of the new digest-consistent trio fails;
  after publication, leave that complete new generation available for retry if
  linking, reloading, enabling, or restarting fails;
- distinguish an absent unit from a user-manager transport failure instead of
  treating every failed lookup as absence;
- discover every effective systemd user-unit root, reject external canonical
  units, aliases, and drop-ins before mutation, and remove only the exact
  path-and-target-validated standard links;
- keep uninstall retryable after every destructive phase: revalidate managed
  output and cache ownership before destructive cleanup, retain enough ownership
  and manifest evidence until unit removal and `daemon-reload` succeed, and
  delete only allowlisted files from directories whose ownership still matches;
- add injected-failure tests for existing-install regeneration and destructive
  uninstall phases; and
- reject source photos above a fixed decoded-pixel ceiling before allocating a
  full RGBA render buffer, while presenting Pillow decode and decompression-bomb
  failures as controlled Countscape errors.

The output lock filename is now reserved before Countscape adopts an existing
directory, preventing a preexisting user file from later being removed as
application state.

## Lower-priority resilience work

These observations do not replace the release gates above:

- profile large photo pools and reduce repeated full-pool image verification if
  timer-driven scans prove materially expensive, while preserving immediate
  source-change detection;
- enforce lifecycle-wide command exclusion or remove newly adopted ownership
  markers after a failed first install only if a future release expands beyond
  the documented sequential lifecycle contract; and
- add directory durability synchronization, a broader crash journal, or support
  for runtime, mixed, aliased, drop-in, and custom-linked systemd installations
  only if a future release explicitly adopts those guarantees.
