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
Countscape runtime output. No privacy-safe example produced by the Countscape
renderer or visual evidence from a supported live GNOME session is currently
published. The artwork must not be treated as runtime or platform validation.

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
lifecycle manifest have separate documented ownership rules.

The operating-system user account is the local trust boundary. The current
implementation validates managed-directory ownership, unit paths and digests,
GNOME restoration, and allowlisted cleanup. It provides best-effort exact
rollback for a failed first install; it does not claim power-loss transactions
or arbitrary persistent/runtime systemd-link recovery.

The pure countdown, configuration, display, selection, and rendering core has
strong local automated evidence. The GNOME/systemd lifecycle is defensively
designed but is not yet proven robust end to end. Existing-install regeneration
and destructive uninstall phases still have failure windows that can leave the
recorded manifest, unit contents, manager state, or ownership markers unable to
support a clean retry.

## Verification evidence

The final local gate used Python 3.14.6 and the committed `uv.lock`:

- worktree, reachable-history, staged-content, and release-artifact privacy
  checks passed;
- all 24 local Markdown documents passed link validation;
- Ruff reported all 59 Python files formatted and no lint findings;
- all 308 tests passed with 90.79% branch coverage;
- `countscape-0.1.0-py3-none-any.whl` and
  `countscape-0.1.0.tar.gz` passed exact-set, metadata, and privacy validation;
  and
- isolated installs of both distributions exposed the expected `countscape
  0.1.0` version and working help command.

The aggregate branch-enabled coverage gate is useful but not uniform:
`install.py`, which owns the highest-risk lifecycle mutations, reported 78.0%,
and `render.py` reported 83.1%. The required lifecycle work therefore needs
targeted injected-failure tests rather than relying on the aggregate percentage
alone.

After pushing this checkpoint, verify the exact CI and CodeQL checks in the live
`main` ruleset and creation/update/deletion protection in the live `v*` tag
ruleset. These controls cannot be proven by cloning the repository alone.

## Separate v0.1 release blockers

These do not block completing the public source repository:

- complete the required lifecycle hardening and injected-failure coverage below;
- bound decoded source-photo allocations independently of the output-canvas
  limit and convert Pillow decoding and decompression-bomb failures into
  controlled Countscape errors;
- register the PyPI Trusted Publisher and confirm the project namespace;
- run the desktop-mutating Ubuntu 26.04 install/apply/timer/update/uninstall
  matrix with privacy-safe evidence, including a reviewed screenshot or redacted
  summary proving that Countscape rendered synthetic, nonpersonal inputs; never
  publish the generated wallpaper artifact itself;
- replace `Pending` in the v0.1 changelog with the release date;
- upload the reviewed social-preview PNG in GitHub's repository settings; and
- create the protected `v0.1.0` tag only after every release gate passes.

Never replace an immutable published artifact. Correct a released artifact with
a new version.

## Required lifecycle hardening

The public-repository pass deliberately avoided adding a generalized
transaction journal. Before v0.1, keep the lifecycle design small and explicit:

- support one persistent systemd user-unit topology and reject runtime, mixed,
  aliased, drop-in, or custom-linked installations before mutation;
- make existing-install regeneration retry-safe: if writing either unit, the
  manifest, linking, reloading, enabling, or restarting fails, preserve or
  restore a digest-consistent prior installation rather than leaving mixed
  generations;
- capture the exact managed links before `systemctl disable`, distinguish an
  absent unit from a user-manager transport failure, and reload the manager
  before inspecting recovery from a partial link failure;
- keep uninstall retryable after every destructive phase: bind validated output,
  cache, and state directories throughout cleanup; retain enough ownership and
  manifest evidence until unit removal and `daemon-reload` succeed; and delete
  only allowlisted files from directories whose ownership still matches;
- add injected-failure tests for existing-install regeneration and each
  destructive uninstall phase; and
- model any required crash recovery as a compact state machine. An explicit
  uninstall/install cutover is preferable to a broad compatibility layer.

The output lock filename is now reserved before Countscape adopts an existing
directory, preventing a preexisting user file from later being removed as
application state.

## Lower-priority resilience work

These observations do not replace the release gates above:

- profile large photo pools and reduce repeated full-pool image verification if
  timer-driven scans prove materially expensive, while preserving immediate
  source-change detection; and
- add directory durability synchronization or a broader crash journal only if a
  future release promises power-loss-durable transactions.
