# Privacy When Asking for Help

Countscape is offline, but its local inputs and diagnostics can still reveal
personal information. Review everything before posting to issues or the wiki.

## Never publish

- source photos or generated wallpapers made from them;
- real event labels, targets, timezones, or completion messages;
- complete config or state files;
- selection seeds, ownership IDs, installation IDs, or manifests;
- usernames, home paths, hostnames, or custom XDG locations;
- photo filenames, pool signatures, or image metadata;
- monitor serials, connector identifiers, or raw Mutter responses;
- unreviewed screenshots or full journals;
- any `doctor --include-private` diagnostics or `status --include-private` raw
  state; or
- secrets, tokens, private correspondence, or unrelated log lines.

## Use safe replacements

- `~/<redacted>` or `<path>` for paths;
- `EXAMPLE-1` for a connector;
- generated geometric placeholder images;
- an invented future event with generic text;
- broad layout descriptions such as “two displays, one portrait”; and
- the smallest relevant, manually reviewed journal excerpt.

Redaction is safer than blurring an image: image metadata, thumbnails, or
unblurred regions may remain. Recreate visual issues with synthetic assets when
possible.

## Diagnostic reports

Run `countscape doctor` locally first and `countscape status` when integration is
involved. Their default output, including JSON, is redacted, but review it before
posting. Never publish either command with `--include-private`; construct a
shorter synthetic summary when in doubt.

The canonical redaction list is in
[Troubleshooting](https://github.com/tylermowll/countscape/blob/main/docs/troubleshooting.md),
and issue routing is in
[Support](https://github.com/tylermowll/countscape/blob/main/SUPPORT.md).

## Editing policy

Published wiki editing is collaborator-only. Propose a privacy-safe correction
through a [public issue](https://github.com/tylermowll/countscape/issues/new/choose).
Report vulnerabilities privately under the
[security policy](https://github.com/tylermowll/countscape/blob/main/SECURITY.md).
