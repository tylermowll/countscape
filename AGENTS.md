# Countscape agent instructions

Countscape is an offline photo wallpaper with a countdown or current date and
message for Ubuntu GNOME/Wayland. Python >=3.15.2 is required for v0.2 and later.

## Repository constraints

- Use `uv` for Python environments, dependencies, commands, locks, builds, and
  tests. Declare dependencies in `pyproject.toml` and commit `uv.lock`.
- This repository and its artifacts are public. Keep personal photos, private
  messages/events, config, state, logs, secrets, generated wallpapers, caches,
  and absolute user paths out of commits and release artifacts.
- Source photos are immutable user data: never rename, rewrite, copy, or delete
  them, including in tests and uninstall.
- Keep config, photos, persistent output, rebuildable cache, and state in
  distinct, nonoverlapping paths. Avoid personal or hardware-specific defaults.
- Calculate countdowns from timezone-aware instants and retain the IANA zone.
  Keep overlay refresh and photo selection independent; unchanged work must
  reuse output and avoid GNOME writes. Replace generated files atomically.
- Keep desktop behavior behind small adapters. Discover Wayland layouts through
  read-only Mutter DisplayConfig, retaining explicit profiles as overrides and
  fallbacks; preserve the full layout contract in the specification below.
- Use user-scoped GNOME/systemd facilities and an installed package environment
  for services, never an editable checkout or repository-local environment.
- Validate manifest paths, ownership markers, allowlisted filenames, and unit
  content digests before lifecycle changes. Preserve foreign or edited units,
  newer user wallpaper choices, config, and source photos. Restore GNOME URIs
  independently and stop cleanup if restoration remains unresolved.
- Keep normal operation offline after dependencies are installed. Automated
  tests use temporary XDG roots and fake desktop adapters, with no live GNOME
  changes or access to personal config and photos.

## Read for the task

Read the relevant sections when working on these areas:

| Task | Source |
|---|---|
| Product behavior or invariants | [Repository constitution](.agents/spec/constitution.md) |
| Rendering, time, display, or adapter changes | [Architecture](docs/architecture.md) and [security boundaries](docs/security-model.md) |
| Configuration or lifecycle changes | [Configuration](docs/configuration.md) and [lifecycle](docs/lifecycle.md) |
| Builds, publication, or support claims | [Release checklist](docs/release-checklist.md), [support](SUPPORT.md), and dated [release audits](docs/audits/) |
| Contribution workflow or agent guidance | [Contributing](CONTRIBUTING.md) and [agent conventions](.agents/README.md) |

The checked-in example has `event.confirmed = false`; never turn it into an
installable default target. Match support and publication claims to the dated
audits; source metadata and automated tests alone do not prove publication or
live GNOME compatibility.

## Verification

Set up with `uv sync --locked --all-groups`. During iteration, run checks that
match the change:

- Documentation: `uv run python tools/check_markdown_links.py` and
  `uv run python tools/privacy_check.py --history --staged`.
- Python: `uv run ruff format --check .`, `uv run ruff check .`, and affected
  tests with `uv run pytest`. Use the full branch-coverage command in
  [Contributing](CONTRIBUTING.md#development-setup) before committing.
- Packaging or release changes: the build, artifact audit, and installation
  checks in the [release checklist](docs/release-checklist.md).

The repository hooks and CI remain required gates. Enable them as documented in
[Contributing](CONTRIBUTING.md#development-setup); do not weaken checks to make a
change pass. Disposable local tests can be run and corrected within the task
without repeated approval. Record live GNOME checks separately as manual
evidence for only the tested release and configurations.
