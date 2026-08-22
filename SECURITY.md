# Security Policy

## Supported versions

Countscape is currently a development preview with no stable release. Security
fixes are applied to the default branch. Once releases exist, this section will
identify the supported release line explicitly.

## Reporting a vulnerability

Please do not open a public issue containing vulnerability details.

Use the repository's **Security** tab and **Report a vulnerability** to submit a
private report. If private vulnerability reporting is not available, open a
minimal public issue asking the maintainers to enable a private contact path;
do not include reproduction steps, exploit details, secrets, or affected user
data in that issue.

Include, when possible:

- the affected version or commit;
- the supported Ubuntu/GNOME environment used;
- impact and preconditions;
- minimal private reproduction steps; and
- any safe mitigation you have identified.

Relevant issues include command or unit injection, unsafe handling of event or
photo paths, unintended file deletion during uninstall, exposure of user photo
data, and ways for malformed images, configuration, Mutter responses, or state
files to escape the documented ownership boundaries.

The maintainers will assess the report, coordinate a fix and disclosure where
appropriate, and credit reporters who want attribution. Please allow time for a
safe fix before public disclosure.

## Scope notes

Countscape intentionally reads local photos and changes the current user's
GNOME wallpaper. Those actions are expected only for paths and integration the
user configured. It should not require root, modify source photos, discover
unrelated personal files, or remove unmanaged files.
