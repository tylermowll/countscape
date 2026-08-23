# Public Repository Readiness

Status: **public-repository checkpoint verified on 2026-08-22**; **Countscape
0.1.0 published and independently verified on 2026-08-23**.

This is the current, cross-machine handoff for Countscape. It replaces the
earlier dated working audit. Live GitHub settings remain independently
verifiable because repository rules, environments, and Wiki publication do not
live in the source checkout.

## Scope

This audit answers two separate questions:

1. Is the source repository safe, understandable, and maintainable as a public
   project?
2. Was Countscape v0.1 published and verified as a tagged GitHub and PyPI
   release?

Both checkpoints are complete. The source repository passed its privacy and
maintainability gates. Protected tag `v0.1.0`, its exact GitHub and PyPI
artifacts, the public-index installation, and recorded live-platform evidence
were verified separately.

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
destructive uninstall retry paths. Live platform validation is recorded
separately below.

## Verification evidence

The final local gate used Python 3.14.4 and the committed `uv.lock`:

- worktree, reachable-history, staged-content, and release-artifact privacy
  checks passed;
- all 24 local Markdown documents passed link validation;
- Ruff reported all 60 Python files formatted and no lint findings;
- all 348 tests passed with 90.39% branch coverage;
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

## Published v0.1.0 evidence

Protected annotated tag `v0.1.0` dereferences to
`ba7d44276b25e7c66813d82a526bee606884ba96`. The canonical
[tag-triggered release run](https://github.com/tylermowll/countscape/actions/runs/32614131456)
completed successfully after independently recovering against the already
published files. The public
[GitHub release](https://github.com/tylermowll/countscape/releases/tag/v0.1.0)
is non-prerelease and immutable, with the original three assets unchanged.

The public [PyPI release](https://pypi.org/project/countscape/0.1.0/) exposes
exactly two unyanked distributions:

- `countscape-0.1.0-py3-none-any.whl`, 45,873 bytes, SHA-256
  `b35024538c8d972e8ee9ed0fb4631973e84222d3d5a4b7c53c8a1a4a597fda76`;
  and
- `countscape-0.1.0.tar.gz`, 38,931 bytes, SHA-256
  `565db30780592ce92f9d7e9891a77b577dd23484df97e4b3036f36cd9346f9a2`.

PyPI's Integrity API exposes a valid publish-attestation bundle for each file.
Both identify GitHub repository `tylermowll/countscape`, workflow `release.yml`,
and environment `pypi`; independent cryptographic verification with
`pypi-attestations` passed. A fresh Python 3.14 tool installation resolved
`countscape==0.1.0` and Pillow from the public PyPI index and passed version,
top-level help, and lifecycle-subcommand help checks under temporary XDG roots.
It did not apply a wallpaper or alter display configuration.

## Supported-host baseline

A v0.1.0 wheel built from runtime commit `1a45605` was exercised on 2026-08-22
on Ubuntu 26.04, GNOME 50.1, Wayland, and a two-logical-monitor
mixed-orientation layout with a physical transform. A synthetic public source
rendered to the discovered 3120x1920 canvas and was visually reviewed. `doctor`,
unchanged apply reuse, live timer execution, schedule regeneration from 5 to 10
and back to 5 seconds, installation-identity preservation, unchanged reinstall,
and reinstall under a different ambient `XDG_CONFIG_HOME` all passed.

Temporary alias and drop-in fixtures under an external effective systemd user
unit root were each rejected before the timer stopped or managed evidence
changed. The final uninstall restored the exact prior GNOME-setting digest,
preserved the synthetic source bytes and modification time, removed the
validated units and links, and preserved configuration. The temporary tool
environment, fixtures, and generated output were then removed; no live
wallpaper or screenshot was retained in the repository.

The same runtime wheel was then exercised on 2026-08-23 under two additional
temporary Mutter configurations. With both displays at 125% scale, redacted
`doctor` output reported two logical monitors, scaling, and the existing
transform; the rendered 3120x1920 synthetic wallpaper was visually reviewed.
With both physical displays mirrored through a shared mode, `doctor` reported
one mirrored logical monitor and the rendered 1920x1080 synthetic wallpaper was
visually reviewed.

The original display arrangement was restored between cases and after the final
case. The persistent GNOME monitor-configuration digest and modification time
were unchanged, as were the synthetic source bytes and modification time. The
temporary tool installation, private config, generated wallpapers, cache, and
state were removed. No raw monitor state, generated wallpaper, or live-session
screenshot was retained in the repository.

The release-preparation changes after `1a45605` are documentation-only; package
runtime code is unchanged. The protected tag workflow built, audited, and
smoke-tested the exact wheel and source archive now published on both channels.
The separate public-index installation recorded above verifies distribution,
not additional live-display coverage; the transformed, scaled, and mirrored
evidence remains tied to the identical runtime code described here.

## v0.1 publication result

Publication completed through the protected `pypi` environment and PyPI Trusted
Publishing. An interrupted first attempt was recovered without moving the tag,
rebuilding the distributions, or replacing draft assets: the recovery path
required the original run ID, artifact ID and digest, tag target, release ID,
filenames, metadata, and file hashes before upload. PyPI was verified before the
existing GitHub draft became public and immutable. The original tag-triggered
workflow then recovered against those exact public files and completed green.

The temporary main-branch environment allowance was removed immediately after
publication; the `pypi` environment again accepts only `v*` tags. The one-time
workflow-dispatch recovery jobs were removed after use. The durable workflow fix
retains push access only where the PyPI job must reverify a mutable GitHub draft
immediately before upload, with a focused regression test.

Uploading the reviewed social-preview PNG in GitHub's repository settings
remains optional repository polish. It affects link cards when the repository
is shared, not Countscape behavior, packaging, security, or release validity.

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
