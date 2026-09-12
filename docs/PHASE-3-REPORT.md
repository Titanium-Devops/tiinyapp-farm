# Phase 3 report

Completed the implementation in the order in `docs/PHASE-3.md`. Local checks pass.
No browser, Docker, Wrangler, or GUI was launched. No repository commit, deployment,
PR comment, release download, or PyPI publication was performed.

## 1. Submission checks

Added `.github/workflows/manifest-check.yml`, triggered by pull requests touching
`manifests/**`, and `scripts/check-submission.py`:

- Uses validation code and schema from the trusted base checkout; submitted files
  live in a separate checkout with persisted Git credentials disabled.
- Selects added/changed manifest paths using a NUL-delimited merge-base diff.
  Rename destinations are checked; deletions and unrelated paths are excluded.
- Calls `scripts/check-manifest.py` without `--allow-pending`, checks filename/ID
  agreement and catalog-wide ID uniqueness, and rejects invalid manifest paths.
- Reuses `Farm.download` and `Farm.unpack` for HTTP(S) download, SHA-256, exact byte
  size, bounded extraction, traversal/link/special-file rejection and archive root
  detection. Extracts into a temporary directory.
- Runs the new stdlib-only `scripts/scan-archive.py`: lists Python imports, checks
  network declarations, rejects subprocess/shell, ctypes and dynamic execution,
  and scans all regular files, including hidden files, for AWS/GitHub/OpenAI/Bearer
  and private-key patterns. Secret matches are redacted. Microphone access is
  reported as declared or not declared, not detected.
- Adds optional boolean `selfcheck` to the schema. True requires a runnable entry;
  its arguments receive `--selfcheck`. Lite now explicitly declares that support.
- A clean scan permits a declared selfcheck in `python:3.11-slim` with network
  disabled, a 120-second timeout, resource limits, an unprivileged user, read-only
  application files, no extra capabilities, and temporary writable storage.
  Nonzero exit or timeout fails. App stdout/stderr are withheld, and timed-out
  containers are removed. Docker is invoked only by CI; tests mock it locally.
- Any failed check fails the job; later changed manifests are still checked when
  the runner remains available. Results are retained as a JSON artifact.

Added `.github/workflows/manifest-comment.yml`, a separate trusted `workflow_run`
job with PR-comment permission and no checkout or execution of submitted code.
It reads the report as data and creates/updates one bot comment per PR with the
check/result/detail table. It escapes report cells, bounds output, handles missing
reports, and avoids replacing a current PR result with an obsolete head's result.
The PR check job has read-only permissions, including for fork submissions.

CI does not edit `verified`. Schema and contributor text explain that a maintainer
sets it in a follow-up commit after successful checks and manual review.

## 2. Site workflow

The existing site workflow already built the site and ran unittest before deploy;
those gates remain in order. Added the push `docs/**` ignore filter so docs-only
pushes skip deployment. PR builds/tests remain enabled.

## 3. Packaging and publication

Confirmed the existing `tiinyapp-farm` distribution name, Python >=3.11 requirement,
zero runtime dependencies, explicit `farm` package, and `farm.farm:main` console
entry. Added package classifiers and project URLs.

Added `.github/workflows/publish.yml` for `v*` tags. It checks that the tag matches
`project.version`, runs tests and the site build, builds wheel/sdist, and smoke-tests
an installed wheel outside the checkout. A separate publication job uses
`pypa/gh-action-pypi-publish` with `id-token: write`, the `pypi` environment and no
token secret.

Changed the generated Plant step 1 to `pip install tiinyapp-farm`, followed by the
git-clone fallback. README includes installation, submission and trusted-publisher
setup instructions without claiming that publication has already happened.

## 4. Contributor guide

Added `docs/SUBMIT.md` in plain words. It covers release archives, checksum/size,
permissions, offline selfchecks, local checks, PR results, draft rejection,
scanner limitations and manual verification. The generated seeds page links to
it, and the site builder copies it into the deployed documentation directory.

## 5. Verification

| Check | Result |
| --- | --- |
| `python3 -m unittest` | PASS: 84 tests, 15.335 seconds, local Python 3.14.6 |
| `python3 scripts/build-site.py` | PASS: 4 app pages; internal links covered by tests |
| `ruff check farm scripts tests` | PASS |
| `mypy --ignore-missing-imports farm scripts tests` | PASS: 11 source files |
| `python3 -m compileall -q farm scripts tests` | PASS |
| `actionlint` on all four workflows | PASS |
| `git diff --check` | PASS |
| Wheel and sdist build | PASS using the installed setuptools backend in a temporary source copy |
| Isolated wheel installation | PASS: offline/no-dependency installation and `farm --help` outside the checkout |

New tests cover hidden tokens plus undeclared sockets, secret families and chunk
boundaries, import aliases, forbidden execution, parse errors, traversal and links,
clean Lite-shaped wrapped/bare packages, download checksum/size mismatch, identity
and duplicate IDs, pending rejection, scan failure blocking selfcheck, and mocked
selfcheck success/failure/timeout. A real temporary Git repository tests divergent
base/head histories, rename destinations, deleted paths and filenames with spaces.

Existing catalog tests assumed exactly three apps and that Story Lantern was
pending. Concurrent workspace changes added Tiiny Bench and updated Story Lantern.
Tests now use catalog size dynamically and an explicit temporary pending fixture.
Those other contributors' manifest and `COLLAB-LOG.md` changes were preserved.

## Changed files and simplifications

- Workflows: `.github/workflows/manifest-check.yml`, `manifest-comment.yml`,
  `publish.yml`, and `site.yml`.
- Scripts: `scripts/scan-archive.py`, `check-submission.py`, `check-manifest.py`,
  and `build-site.py`.
- Metadata: `docs/manifest.schema.json`, `manifests/titanium-tiiny-bot.json`,
  and `pyproject.toml`.
- Documentation: `README.md`, `docs/SUBMIT.md`, and this report.
- Tests: `tests/test_submission.py`, `tests/test_farm.py`, and `tests/test_site.py`.

Reused the existing archive/download implementation and schema validator instead
of duplicating their logic. Kept the existing packaging entry point and site
build/test gates. Removed fixed catalog-count and live-draft assumptions from
tests. No runtime dependencies were added.

## Remaining external proof and risks

- The bundled Lite 0.1.9 archive imports subprocess and calls `subprocess.Popen`
  in `lite/server.py`. The scanner correctly rejects it. A clean fixture with
  Lite's archive/package shape passes; the actual bundled archive does not. Its
  upstream shell helper needs removal and a new release/checksum before that
  archive can pass this policy. The policy was not weakened to accommodate it.
- The orchestrator must prove the GitHub checks, fork PR comment and actual
  offline container execution on a PR. Validation scripts must first exist on
  the base branch; the comment workflow must exist on the default branch.
  Actionlint and local tests validate structure/logic, not live GitHub behavior.
- PyPI's trusted publisher and the GitHub `pypi` environment need maintainer setup
  before the first matching tag is published. Live OIDC publication is untested.
- Local verification used Python 3.14.6; CI explicitly runs Python 3.11. No remote
  release reachability or production deployment was tested in this phase.
- Static scanning is conservative and incomplete: computed aliases, generated or
  non-Python code and unknown secret formats can evade it. It may also flag safe
  uses of prohibited primitives. Manual review remains necessary; installed app
  permissions are declarations, not enforced sandbox restrictions.
