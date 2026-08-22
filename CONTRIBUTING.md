# Contributing to Countscape

Thanks for helping make Countscape dependable, private, and pleasant to use.
The project favors focused, testable changes over broad platform claims.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). Ordinary
support belongs in [SUPPORT.md](SUPPORT.md); vulnerabilities must follow the
private process in [SECURITY.md](SECURITY.md).

## Before proposing a change

- Search existing issues before opening a new one.
- Open an issue before a large behavior, schema, lifecycle, dependency, or
  platform change so compatibility and safety boundaries can be agreed first.
- Keep Ubuntu 26.04 GNOME/Wayland as the supported target unless a proposal
  includes contract fixtures and live verification for another platform.
- Do not describe a command, release, platform, or integration as supported
  before evidence exists.
- Propose community-wiki corrections through an issue. The published GitHub Wiki
  is collaborator-maintained and is not the canonical product specification.

## Development setup

Install [`uv`](https://docs.astral.sh/uv/), clone the repository, and run from its
root:

```bash
uv sync --locked --all-groups
uv run python tools/privacy_check.py --history
uv run python tools/check_markdown_links.py
uv run ruff format --check .
uv run ruff check .
uv run pytest \
  --cov=countscape \
  --cov-branch \
  --cov-report=term-missing \
  --cov-config=.coveragerc
```

Use `uv` for every Python environment, dependency, command, lock, build, and
test. Do not use bare `pip`, Poetry, or Conda. If dependencies change, update
`pyproject.toml` and `uv.lock` in the same pull request.

The normal development environment is for tests and repository commands. Do not
install user integration from an editable checkout. A manual integration test
must use a built wheel in a persistent tool environment and must be performed
only in an intentionally selected GNOME test account:

```bash
uv build --no-sources --clear --out-dir dist
uv run python tools/release_check.py \
  --artifacts dist/*.whl dist/*.tar.gz \
  --write-checksums dist/SHA256SUMS
uv run python tools/privacy_check.py \
  --history \
  --artifacts dist/*.whl dist/*.tar.gz
uv tool install --force --python 3.14 dist/countscape-0.1.0-py3-none-any.whl
countscape --version
countscape doctor
```

Do not run `countscape install` against a contributor's everyday desktop as part
of an automated test.

## Test safety

Automated tests must use temporary photo banks, configuration, generated output,
XDG roots, and fake GNOME/systemd adapters. They must never:

- modify source photos;
- read personal photo directories or machine-local configuration;
- call live `gsettings` or change the desktop wallpaper;
- install live user units; or
- rely on a contributor's username, home path, connector identifier, monitor
  serial, or display dimensions.

Cover failure behavior as well as the happy path. Time-related changes need
aware-datetime, target-boundary, daylight-saving, suspend-like jump, and clock-
correction cases. Display changes need position, scale, transform, primary, and
mirroring coverage. Rendering changes need missing, empty, invalid, portrait,
landscape, transparent, and long-text inputs.

Installation changes must include matching exact-version update, rollback,
reinstall, and uninstall behavior. Automated tests must never change the live
desktop; real GNOME evidence is recorded separately using the template in
[docs/release-checklist.md](docs/release-checklist.md).

## Privacy

Do not contribute:

- personal photos or generated wallpapers made from them;
- real itineraries, event labels, targets, or private messages;
- screenshots containing personal information;
- config, state, ownership IDs, selection seeds, logs, or secrets;
- usernames, home paths, hostnames, connector identifiers, or machine-local
  display dumps; or
- editor settings, caches, environments, or generated build output.

Use generated or clearly licensed media only, document its provenance, strip
unneeded metadata, and use synthetic event data. Before submitting, inspect
tracked files and build artifacts. Deleting private material in a later commit
does not remove it from Git history; contact a maintainer immediately if private
data is committed.

Default `countscape doctor` and `countscape status` output, including JSON, is
redacted, but users must still review it before posting. Never ask for either
command's `--include-private` output in a public issue. Follow the redaction list
in [docs/troubleshooting.md](docs/troubleshooting.md).

## Documentation ownership

Repository documentation is canonical:

- [docs/install.md](docs/install.md) for first installation;
- [docs/configuration.md](docs/configuration.md) for the schema and settings;
- [docs/lifecycle.md](docs/lifecycle.md) for update, rollback, and uninstall;
- [docs/security-model.md](docs/security-model.md) for trust boundaries;
- [docs/architecture.md](docs/architecture.md) for implementation design; and
- [docs/release-checklist.md](docs/release-checklist.md) for publication claims.

Keep those documents synchronized with changed commands, paths, config, or
behavior. The published GitHub Wiki is a narrow, community-oriented layer that
must link back to canonical repository docs rather than duplicate or override
them. Wiki editing remains collaborator-only; propose changes through the issue
tracker.

## Pull requests

Keep each pull request small enough to review and verify independently. Include:

- the behavior and reason for the change;
- tests or a clear reason tests are not applicable;
- documentation updates for changed commands, config, or paths;
- the exact automated checks run;
- any live GNOME checks, clearly separated from simulated tests;
- privacy and artifact-review notes when media, fixtures, packaging, or release
  files change; and
- lifecycle evidence when installation changes.

Do not mix cleanup, dependency updates, and behavior changes unless they are
inseparable. Preserve unrelated work already present in the branch.

## Releases

Maintainers publish releases only after every applicable gate in
[docs/release-checklist.md](docs/release-checklist.md) has evidence. A version in
source metadata is not proof that a tag or package has been published. Release
notes must distinguish automated adapter tests from live Ubuntu GNOME results.
When immutable GitHub releases are enabled, automation must create a draft,
attach the exact tested wheel, source archive, and checksums, verify the complete
draft, publish those same artifacts to PyPI, reverify the draft, and publish the
existing draft once. Published assets are never replaced; a correction requires
a new version.
