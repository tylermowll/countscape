# Security and Privacy Model

This document describes Countscape's local trust boundaries. It complements the
vulnerability-reporting policy in [SECURITY.md](../SECURITY.md).

## Product boundary

Countscape is a single-user desktop tool. It reads user-selected local photos,
renders local wallpaper files, reads the active GNOME/Wayland display layout,
changes the current user's GNOME wallpaper settings, and manages two systemd user
units. It does not require root, provide a network service, upload photos, or use
telemetry. Network access may be needed only to install Python and package
dependencies; normal operation remains offline.

The operating-system user account is the trust boundary. A hostile process
already running as that same user can access the user's photos, GNOME settings,
systemd user manager, and Countscape files. Ownership and digest checks are
corruption defenses, not isolation from an equally privileged process.

## Sensitive data

The following are private even though not all are secret credentials:

- source photos and their filenames or metadata;
- event labels, targets, timezones, and completion messages;
- configuration and absolute filesystem paths;
- generated wallpapers and screenshots;
- display identifiers and machine layout details;
- selection seeds, ownership markers, installation state, and journals; and
- `doctor --include-private` diagnostics and `status --include-private` raw state.

None belongs in the public repository, release artifacts, wiki, or public issue
attachments. Synthetic examples must not copy a real event or machine layout.

## Ownership boundaries

| Data | Owner | Countscape behavior |
|---|---|---|
| Configuration | User | Created or atomically updated; preserved on uninstall |
| Source photos | User | Read and verified; never renamed, rewritten, copied, or deleted |
| Final wallpapers | Countscape | Atomically created as persistent data; removed conservatively |
| Rebuildable cache | Countscape | Atomically managed and removable after ownership validation |
| Runtime and integration state | Countscape | Stored at the config-recorded path; records prior GNOME state, installation identity, paths, and digests |
| User units | Countscape | Generated, hashed, and validated before replacement or removal |

Photo, output, cache, config, and state paths are deliberately separate. Output
and cache directories carry ownership markers bound to the private configuration
seed. Cleanup uses allowlisted filenames and refuses a mismatched marker.

## Desktop integration safety

- Mutter display discovery is read-only.
- GNOME wallpaper values are saved before the first managed change.
- Light and dark wallpaper URIs are restored independently only while they still
  point to known Countscape output.
- A newer user wallpaper choice is preserved.
- Restoration failure remains explicit; uninstall stops before deleting a file
  GNOME might still reference.
- User units run the installed package environment and do not require a source
  checkout or privileged system service.
- Unit sources live under the config-recorded runtime state directory and are
  linked into the systemd user manager.
- The service loads the recorded runtime state path from config rather than
  deriving lifecycle state from ambient systemd XDG variables.
- Foreign or user-edited units are not silently replaced or removed.

## Input and rendering safety

Countscape treats config, image files, Mutter responses, and persisted state as
fallible input. It validates aware timestamps, bounded text, storage separation,
image readability, display geometry, canvas allocation, state shape, paths,
ownership markers, generated filenames, and unit digests. Output and state are
replaced atomically, and render/apply operations are serialized.

Pillow and the host desktop stack still process local files and system responses.
Keep dependencies current, use only photos you trust, and report unexpected file
access, deletion, command construction, or parser behavior privately.

## User responsibilities

- Select a dedicated photo directory intentionally.
- Review a render before installing automatic application.
- Keep private config, state, diagnostics, and generated output out of public
  reports.
- Do not hand-edit generated units or move ownership markers.
- Choose a non-Countscape wallpaper if uninstall asks for restoration recovery.
- Install only exact versions published through the project's documented release
  channels.

## Report a vulnerability

Do not post exploit details or affected data publicly. Follow the private process
in [SECURITY.md](../SECURITY.md). Ordinary setup questions belong in
[SUPPORT.md](../SUPPORT.md).
