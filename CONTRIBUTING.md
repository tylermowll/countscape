# Contributing to Countscape

Thanks for helping make Countscape more dependable. The project favors focused,
testable changes over broad platform promises.

## Before opening a change

- Search existing issues and the [implementation plan](docs/implementation-plan.md).
- Keep Ubuntu GNOME/Wayland as the supported platform unless a proposal includes
  both contract fixtures and live verification for another platform.
- Open an issue before a large behavior, schema, lifecycle, or dependency
  change so its compatibility and safety boundaries can be agreed first.
- Use [SECURITY.md](SECURITY.md), not a public issue, for vulnerabilities.

## Development setup

Install [`uv`](https://docs.astral.sh/uv/), then run from the repository root:

```bash
uv sync --locked
uv run python tools/privacy_check.py
uv run pytest
uv run ruff check .
uv build
```

Use `uv` for every Python dependency and command. If dependencies change,
update both `pyproject.toml` and `uv.lock` in the same pull request.

## Test safety

Automated tests must use temporary photo banks, configuration, generated output,
XDG roots, and fake GNOME/systemd adapters. They must never:

- modify source photos;
- read personal photo directories or machine-local configuration;
- call live `gsettings` or change the desktop wallpaper;
- install live user units; or
- rely on a contributor's username, home path, monitor identifiers, or display
  dimensions.

Cover failure behavior as well as the happy path. Time-related changes need
aware datetime, target-boundary, daylight-saving, suspend-like jump, and clock-
correction cases. Display changes need scale, transform, position, primary, and
mirroring coverage.

## Privacy

Do not contribute personal photos, real itineraries or private event details,
screenshots containing personal information, secrets, logs, generated
wallpapers, local configuration, or absolute machine paths. Use generated or
clearly licensed media only, and document its provenance.

Before submitting, inspect tracked files and build artifacts. Deleting private
material in a later commit does not remove it from Git history; contact a
maintainer immediately if private data is committed.

## Pull requests

Keep each pull request small enough to review and verify independently. Include:

- the behavior and reason for the change;
- tests or a clear reason tests are not applicable;
- documentation updates for changed commands, configuration, or paths;
- the exact automated checks run; and
- any real GNOME checks, clearly separated from simulated tests.

Do not describe commands or support as implemented before evidence exists.
Installation changes must include matching update, rollback, and uninstall
behavior.
