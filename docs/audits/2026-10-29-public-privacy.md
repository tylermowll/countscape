# Public privacy audit: 2026-10-29

No leaked secrets or private personal data were found in the public Countscape
content checked below. This is a dated finding with an explicit scope; it is
not a guarantee that every possible credential or personal detail can be
detected.

This audit supplements the historical
[repository-readiness audit](public-repository-readiness.md) and the
[v0.1](public-repository-readiness.md#published-v010-evidence),
[v0.2](v0.2.0-release.md), and [v0.3](v0.3.0-release.md) publication records.
It does not add live GNOME platform evidence or change published artifacts.

## Checked surfaces and results

| Surface | Scope | Result |
|---|---|---|
| Local checkout | Worktree, exact staged index, and all locally reachable history | Privacy check passed |
| Fresh public Git mirror | Main, all three release tags, and all 24 retained pull-request head refs: 28 refs, 46 commits, 439 objects | History privacy check passed |
| Published packages | Wheel and source archive for each of 0.1.0, 0.2.0, and 0.3.0, downloaded from both GitHub and PyPI | All six distribution pairs were byte-for-byte identical and passed archive privacy checks |
| PyPI metadata | Current public project metadata, description, and release-file records | No privacy findings; author is Countscape contributors, with no author or maintainer email |
| GitHub discussions | All 24 issue/pull-request bodies, all seven issue comments, the sole review submission, and zero inline review comments | No findings from the privacy text checks |
| GitHub release notes | All three public release bodies | No findings from the privacy text checks |
| Workflow logs | Eight complete jobs, approximately 3,275 lines: latest CI, CodeQL, dependency graph, and all five v0.3.0 release jobs | No exposed credentials or private personal data found |
| GitHub secret scanning | All alerts returned by the repository API | Zero alerts |

The public main revision checked was
[`ca29285`](https://github.com/tylermowll/countscape/tree/ca29285eb10666b01b8b0f944a35990b0f445cca).
The current [GitHub releases](https://github.com/tylermowll/countscape/releases)
and [PyPI release history](https://pypi.org/project/countscape/#history) listed
only 0.1.0, 0.2.0, and 0.3.0 at the time of the check. Downloaded files matched
PyPI's published sizes and SHA-256 digests as well as their GitHub counterparts.
Exact distribution digests remain recorded in the release audits linked above.

The repository checks used `tools/privacy_check.py`, including
`--history --staged` for the checkout. A separate temporary public mirror
included the retained pull-request refs before running its history scanner;
an ordinary checkout's local refs do not necessarily include them. The artifact
scanner inspected each downloaded wheel and source archive without executing
the packages. Downloads and the mirror stayed outside the source checkout.

Workflow-log matches were reviewed individually. The only matches from the
repository privacy patterns were standard GitHub-hosted runner paths and a
literal redacted password marker. Additional checks for common PyPI, JWT,
OpenAI, Google API, Slack, temporary AWS credential, and credential-bearing URL
formats found no exposed values in those logs.

The sampled jobs came from the
[CI run](https://github.com/tylermowll/countscape/actions/runs/40934630080),
[CodeQL run](https://github.com/tylermowll/countscape/actions/runs/40934629953),
[dependency-graph run](https://github.com/tylermowll/countscape/actions/runs/40934629955),
and all five jobs in the
[v0.3.0 release run](https://github.com/tylermowll/countscape/actions/runs/40932600883).

## Intentional public attribution

Repository URLs and CODEOWNERS identify the public GitHub owner. Git history
contains public author display names, handles, and GitHub/noreply addresses.
These are visible attribution, so the project does not claim that no personal
identifier appears anywhere. No private email address was found in the checked
commit metadata or public package metadata.

The two approved documentation images are synthetic public artwork with
reviewed provenance and exact-byte privacy allowlisting; see
[Documentation Assets](../assets/README.md).

## Limits

- The scanner recognizes selected patterns and prohibited artifact types. It
  cannot identify every arbitrary credential, name, address, event detail, or
  encoded value. Zero GitHub alerts is additional evidence, not proof of absence.
- Workflow logs were sampled; the audit did not inspect every historical run
  or every Actions artifact.
- A fresh mirror covers the publicly advertised refs it fetched. Deleted or
  unreachable objects, earlier overwritten pull-request heads, external forks,
  cached copies, and third-party mirrors were not certified.
- The separate published GitHub Wiki repository, account profiles, and public
  provenance-attestation payloads were outside this audit. Tracked wiki source
  files were included in the source-history checks.
- Findings describe the checked state on this date. Later commits, uploads,
  comments, settings changes, or disclosures require another review.

Keep configuration, source photos, messages, state, generated wallpapers, and
private logs outside public reports. Follow the
[security model](../security-model.md) and
[private reporting policy](../../SECURITY.md) if new exposure is discovered.
