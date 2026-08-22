## Summary

<!-- Explain the behavior change and why it is needed. -->

## Verification

<!-- List the exact commands run and separate simulated checks from live GNOME checks. -->

- [ ] `uv run python tools/privacy_check.py --history`
- [ ] `uv run python tools/check_markdown_links.py`
- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] Tests appropriate to the change pass.
- [ ] Build and artifact audit pass when packaging is affected.

## Privacy and safety

This pull request is public. Do not include personal photos, private event details, machine-local configuration, credentials, generated wallpapers, caches, logs, usernames, absolute home paths, private display identifiers, or unredacted screenshots.

- [ ] I reviewed the complete diff and newly added files for personal or machine-local data.
- [ ] Tests use temporary XDG roots, synthetic media, and fake desktop adapters.
- [ ] Source photos and user configuration remain untouched.
- [ ] Documentation and support claims match verified behavior.
- [ ] Installation changes include update, rollback, and uninstall coverage.
