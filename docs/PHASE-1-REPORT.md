# Phase 1 report

Completed 2026-09-12, in the order in `docs/PHASE-1.md`, with the authorized Lite
patch fallback. No browser or GUI was launched. No release was published.

## What was built

1. **Manifest schema and validator.** `docs/manifest.schema.json` declares JSON
   Schema draft 2020-12 and all manifest fields from the spec. It supports Python
   module entries, direct command entries, and the explicitly requested null library
   entry. `python3 scripts/check-manifest.py <file>` uses only the standard library
   and validates the schema's keyword subset. Draft checksums require
   `--allow-pending` and a note in the description. Invalid IDs, multiline pitches,
   malformed versions, unknown fields, invalid dates, duplicate permissions, boolean
   integers and out-of-range ports are rejected.
2. **Three manifests.** All three validate with `--allow-pending`; all three are
   correctly refused without it. Each has `verified: false`, no invented screenshots,
   and `addedAt`/`updatedAt` of `2026-09-12`. Release limitations are explained below.
3. **Installer.** `farm/farm.py` is the single-file, standard-library implementation
   of install, update, start, stop, status, list, remove and device. Both
   `python3 farm/farm.py` and the pip-installed `farm` entry point work.
4. **Offline tests.** `tests/test_farm.py` provides 35 unittest tests, including the
   required local archive/catalog, checksum rejection, lifecycle, update and removal
   cases, plus negative manifest and archive tests.
5. **Lite packaging and lifecycle.** `farm-lite-patch/titanium-bot-lite-0.1.9.patch`
   contains the complete item 5 changes. A fresh application of that patch passes
   the upstream suite and reproduces the delivered archive byte for byte.

Installer behavior:

- Default catalog: `https://tinyapp.farm/manifests/`; `FARM_CATALOG` supports local
  directories and file URLs as well as HTTP(S).
- Installation displays name, pitch, permissions and requirements, then prompts
  once. `--yes` is available for explicit automation. Pending checksums cannot install.
- Downloaded SHA-256 and exact byte size are verified before extraction. Extraction
  refuses path traversal, links, special files and duplicate file entries, with
  download/extraction limits. GitHub archive wrapper directories are handled.
- Code lives in `~/tinyapps/<id>/<version>`, with atomic `current` and launcher
  registration in `launcher.json`. Data lives separately in `~/tinyapps/<id>/data`.
- Device base URL and key are both read without echo; configuration is written
  atomically as `~/tinyapps/device.json`, mode `0600`. Echoing input fallback is
  refused, and installer error output does not expose raw credential-bearing errors.
- Launchers set `TIINY_BASE`, `TIINY_KEY`, `TIINY_HOST`, `FARM_DATA_DIR`,
  `TIINY_DATA_DIR`, and shared `ONELANE_DIR=~/tinyapps/.onelane`. Story Lantern's
  existing data, database, safety-log and port environment variables are also set.
- Entries run without a shell, append stdout/stderr to `farm.log`, and record
  `farm.pid` plus timing/port metadata. A held runtime file lock distinguishes a
  running process group from a stale PID. Concurrent mutations are serialized.
- Stop sends SIGINT to the process group and escalates after five seconds. Tests
  cover an ignoring process and a forked child surviving its group leader.
- Updates install only newer versions, preserve data and old code, and stop the old
  process after successful download/verification/extraction. Restart is explicit.
  A failed checksum leaves the old running version untouched.
- Remove stops the app and retains data unless `--purge`. Removing the OneLane
  library leaves shared device locks intact. Library entries cannot be started.

## Manifest summaries and provenance

| Manifest | Version | Entry | Requirements | Permissions / license |
| --- | --- | --- | --- | --- |
| Titanium Tiiny Bot | `0.1.9` prepared patch; inspected source `0.1.8` | `python -m lite --port 7788`; supports `--selfcheck` | Python 3.11, port 7788, chat + TTS, 57 NPU units | microphone, files, network, device; `NOASSERTION` |
| Story Lantern | `0.1.0` from `lantern.py` | `python -m lantern`; supports `--selfcheck` | Python 3.9, port 8420, chat + image + TTS, 89 NPU units | files, network, device; `NOASSERTION` |
| OneLane | proposed `0.1.0`, not an observed upstream version | `null`, tagged `library` | No listening ports or required model residency; no asserted upstream Python minimum | files, network, device; MIT |

Titanium's source was read from `/Users/sem/code/titanium-bot-lite`; its version
file contained `0.1.8`, while its README still said `0.1.5`. The patch aligns both
with `0.1.9`, incrementing only the final component. Its requested model/permission
values are those in the Phase 1 brief. No license file or remote URL was present.

`gh api` requests for both external repos failed because shell network access is
restricted. Read-only web retrieval provided the
[Story Lantern README](https://github.com/webdevtodayjason/story-lantern), but raw
source and release requests were unavailable. Existing local checkouts were then
read; their configured origin URLs match the requested GitHub repositories:

- `/Users/sem/code/tiiny/lantern`, origin
  `https://github.com/webdevtodayjason/story-lantern.git`, local HEAD
  `13d56a33bac7745f63e5c5e38f8e7ba04b3ebae0`.
- `/Users/sem/code/tiiny/onelane`, origin
  `https://github.com/webdevtodayjason/onelane.git`, local HEAD
  `f344c62dd375eb947ad8b92e4637b76192841a69`.

The local Story Lantern source provides the version, environment contract and
entry point; its README declares model residency and Python requirements. Voice
input is described as future work, so microphone permission is not asserted.
OneLane's source and MIT license were read directly. It is a reusable library,
not a service; its source declares no release version. Neither checkout had local
tag refs. These observations do not prove the current remote release state.

## Lite patch and archive

The sandbox refused the attempted write to the external `lite/VERSION` with
`PermissionError: Operation not permitted`. The external repo remains at `0.1.8`.
All changes were made in a temporary copy, then delivered as the authorized unified
diff. Application instructions are in `farm-lite-patch/README.md`.

The patch changes:

- `scripts/release.py` (new): deterministic, standard-library tar.gz builder with
  sorted members, normalized metadata and stable gzip headers. Packages only
  `lite/`, `brand/`, and `README.md`, including `lite/VERSION`. Excludes vendor,
  data, tests and caches; refuses symlinks.
- `lite/server.py`: adds `--stop`, private `data/lite.pid` and a stable `.lite.lock`;
  distinguishes stale PIDs; refuses a second process sharing the data directory;
  explicitly restores SIGINT handling even when inherited from an ignoring shell.
  CLI cleanup gets a shared one-second deadline, preserving normal embedded
  `App.close()` behavior. Daemon workers cannot keep the CLI waiting on an active
  turn or voice request.
- `lite/VERSION`: `0.1.8` to `0.1.9`.
- `README.md`: install-with-farm instructions, stop behavior, data locations and
  release packaging instructions; fixes the stale displayed version.
- `.gitignore`: excludes generated `dist/`.
- `tests/test_config.py`: updates existing version expectations.
- `tests/test_farm_release.py` (new): 11 packaging and real-process lifecycle tests.

Delivered archive: `farm-lite-patch/titanium-tiiny-bot-0.1.9.tar.gz`.
Builder output in the Lite tree: `dist/titanium-tiiny-bot-0.1.9.tar.gz`.
Size: **433,852 bytes**, **74 archive members**.

SHA-256:

```text
58dca3dbb5d573c3c0c3ffefb8fd615d6ef87f013d19de384ffe4f2bcb3cc715
```

The patch was dry-run against the original repo, applied to a fresh temporary copy,
and every changed file compared byte for byte with the tested edit. Rebuilding
from that fresh application produced the identical delivered archive. The archive
was then installed by `Farm.install` through a temporary local catalog containing
its actual checksum and size. Running the installed `python -m lite --selfcheck`
with `TIINY_MODEL=echo` returned `ok: true` and `budgetPassed: true`:
35.89 MB RSS, 23,490 door resource bytes, 56.44 ms initialization, and a 23-character
reply. This was headless and used no real device.

## Verification

| Check | Result |
| --- | --- |
| `python3 -m unittest`, farm, Python 3.14.6 | 35 run, 35 passed, zero skips |
| `/opt/homebrew/bin/python3.12 -m unittest`, farm, Python 3.12.11 | 35 run, 35 passed, zero skips |
| Original Lite baseline, Python 3.14.6 | 88 run, 84 passed, 4 skipped |
| Patched Lite, Python 3.14.6 | 99 run, 95 passed, 4 skipped |
| Fresh application of delivered Lite patch, Python 3.14.6 | 99 run, 95 passed, 4 skipped |
| Three manifest CLIs | Pass with `--allow-pending`; each fails correctly without it |
| Local pip build/install, no dependency download | Passed; installed `farm --help` works |
| `ruff check farm scripts tests` | Passed |
| `mypy --check-untyped-defs --follow-imports=skip farm/farm.py scripts/check-manifest.py` | Passed |
| New Lite release script and tests, Ruff | Passed |
| New Lite release script, mypy including untyped bodies | Passed |
| Lite server lint comparison | One pre-existing finding, unchanged; no new findings |
| Python compilation; diff/whitespace checks | Passed |
| Fresh-patch archive reproducibility and installed echo selfcheck | Passed |

The four Lite skips are the existing loopback-listener CLI test and three real
HTTP tests (JavaScript adapter, door/events, echo). The sandbox denies socket
binding. In-memory HTTP contracts, Node syntax/voice contracts, and real-process
shutdown tests still run. New shutdown tests replace only the socket listener;
they use the actual CLI, actual App worker, a blocked turn holding the app lock,
and real SIGINT/`--stop` subprocesses, with a two-second deadline. One also starts
with SIGINT ignored to reproduce shell-background behavior.

An initial Lite baseline command resolved to the system Python 3.9, below Lite's
3.11 requirement, and encountered two upstream HTTPError cleanup errors. It was
rerun with the explicit supported Python 3.14 binary; the supported baseline and
all final runs above pass. Python 3.11 itself is not installed here and was not
executed. No real Tiiny inference, microphone input, or GUI behavior was tested.

## Deviations, decisions and remaining limits

1. **No commits:** staging failed because `.git/index.lock` is not writable in this
   sandbox. Changes are left uncommitted under the brief's explicit fallback.
2. **Lite delivered as a patch:** external writes are denied. The patch, tested
   archive and application instructions are delivered inside this repo. No claim
   is made that the external working tree has been updated.
3. **Upstream reads used existing checkouts:** `gh api` was attempted but blocked;
   remote web fallback was incomplete. Checkout provenance is recorded above;
   remote freshness and release availability remain unverified.
4. **All release checksums remain `pending`, sizes `0`:** no release was published
   or successfully fetched. Descriptions explain that zero is unknown draft size.
   Story Lantern and OneLane use future `archive/refs/tags/v<version>.tar.gz` URLs.
   Lite uses the planned custom release asset under `releases/download/v0.1.9/`
   so its release can contain only the requested packaged files. The locally built
   hash is not falsely assigned to an unverified remote download.
5. **Unspecified metadata is explicit:** OneLane's `0.1.0` is a proposed first farm
   version, not an invented upstream observation. Titanium's
   `Titanium-Devops/titanium-bot-lite` GitHub destination is provisional because
   the local checkout has no remote. Titanium and Story Lantern use `NOASSERTION`
   because no license was found. Maintainer confirmation is needed before release.
6. **Schema conventions:** date fields use `YYYY-MM-DD`; local release fixtures
   may use file URLs; `requires.python` can be absent when upstream declares no
   minimum. Null entries require the library tag in the validator. Pending notes
   and selfcheck support use the existing description field rather than adding
   speculative manifest fields. The validator implements this schema's subset,
   not a general-purpose JSON Schema library. Runtime installation checks the
   fields it consumes; full catalog validation is the separate validator.
7. **Launcher contract:** foreground POSIX processes are supported. Apps must keep
   the inherited runtime-lock descriptor open; self-daemonizing apps and programs
   that close all inherited descriptors are not supported. The shared lock path
   is `.onelane`, avoiding collision with the installed `onelane` library.
8. **Story Lantern integration limit:** environment mapping makes its existing
   entry/data contract usable, but upstream hardcodes device management HTTP port
   8800 and does not use OneLane. Passing a shared lock directory alone cannot
   guarantee serialization for it. No edits to that external repo were authorized.
9. **Shutdown tradeoff:** host shutdown is bounded; already-issued device work may
   continue, and voice-model release may not complete. Lite already marks unfinished
   persisted turns failed on restart. These limits are described in its README.
10. **Distribution and discovery:** the pip package was built and installed locally,
    not published to PyPI. Setuptools is build-only; runtime dependencies remain
    empty. A remote catalog listing must expose an array of IDs or manifest links;
    the default public catalog and actual remote downloads were not live-tested.
11. **Scope and concurrent work:** site building and submission CI are later phases.
    Concurrent changes added `docs/APPS.md`, a Tiiny Bench launch note in `SPEC.md`,
    and `site/assets/gen/hero-test.png`; these were left untouched. Tiiny Bench is
    named in those launch notes but has no Phase 1 manifest, consistent with the
    requested three-app scope and its pending selfcheck/release. OMX runtime state
    also appeared during the session and was not removed.

## Files delivered by this task

- `.gitignore`, updated `README.md`, and `pyproject.toml`.
- `docs/manifest.schema.json` and this report.
- `scripts/check-manifest.py`.
- `manifests/titanium-tiiny-bot.json`, `manifests/story-lantern.json`,
  `manifests/onelane.json`.
- `farm/__init__.py`, `farm/farm.py`.
- `tests/__init__.py`, `tests/test_farm.py`.
- `farm-lite-patch/README.md`, `farm-lite-patch/titanium-bot-lite-0.1.9.patch`,
  `farm-lite-patch/titanium-tiiny-bot-0.1.9.tar.gz`.

The implementation keeps the runtime in one file, reuses the apps' existing
configuration and data environment contracts, and introduces no runtime dependency,
shell launcher, device daemon, or duplicate OneLane implementation.

## Phase 1b

Completed 2026-09-12 from `docs/PHASE-1B.md`, entirely through CLI tools. No browser
or GUI was launched and no commit was attempted, as required by the brief.

### Changes

- `farm device --base URL --key-stdin` imports piped credentials without a terminal.
  `TIINY_BASE` and `TIINY_KEY` also support a one-shot persistent import. Explicit
  options override environment values; incomplete scripted input fails without
  prompting. With neither flags nor device environment values, both hidden prompts
  remain. Atomic writes and mode `0600` are preserved; keys never need an argument.
- Startup rejects already-listening declared ports before spawning, preventing an
  existing server from satisfying the new child's readiness check. It then waits
  up to ten seconds, checking child exit before and after probes. An optional
  manifest `health` path selects HTTP GET on the primary port; remaining ports use
  TCP. Without declared ports, a short child-liveness check remains. Failed startup
  reports the last ten log lines, terminates the process group, and clears its
  records. HTTP probes have a wall-clock bound as well as socket timeouts, including
  malformed, truncated and trickling-response handling.
- `farm start <id> --port N` overrides the primary port, validates its range, and
  exports `TINYAPP_PORT`. Lite also receives `TIINY_PORT` and a corrected explicit
  `--port` argument; Story Lantern receives `PORT`. Secondary ports remain declared.
  `process.json` records effective ports, and status displays those values.
- Status queries health for the running version, compares with the currently
  installed manifest, and prints e.g. `running 0.1.8, installed 0.1.9: restart to
  update`. It supports older process records lacking the health field. When health
  or its version is unavailable, output labels that condition and falls back to
  the recorded launch version. Apps without health use their launch version.
- Lite already returned its packaged version from `/api/health`; that behavior now
  has explicit regression coverage and a manifest declaration. The refreshed Lite
  patch adds `TINYAPP_PORT` fallback below `TIINY_PORT` and explicit CLI options.
  Both a cumulative patch for original `0.1.8` and an incremental Phase 1b patch
  for the inspected external `0.1.9` checkout are supplied. External sources were
  not modified. Application instructions are in `farm-lite-patch/README.md`.

### Verification and simplifications

- `python3 -m unittest` (Python 3.14.6): **57 run, 57 passed, zero skips**.
- `/opt/homebrew/bin/python3.12 -m unittest`: **57 run, 57 passed, zero skips**.
- `ruff check farm scripts tests`, mypy with untyped body checking for the launcher
  and validator, Python compilation, and diff whitespace checks passed.
- All three manifests validate; the two pending manifests require `--allow-pending`.
  The Lite manifest's checksum and byte size match the delivered archive.
- Patched Lite suite: **102 run, 98 passed, four existing socket tests skipped**.
  Compilation and echo-mode selfcheck passed. Rebuilding from the cumulative patch
  reproduces the archive byte for byte. The incremental patch dry-runs and applies
  to a temporary copy of the external checkout; changed files match tested sources.
- Regression coverage includes real subprocess CLI pipe input, exit code 1 and log
  output, delayed child death, busy-port rejection without spawning, timeout cleanup,
  multiple-port readiness, health failures, strict deadline handling, port environment
  and Lite argument precedence, legacy process records, and live-version mismatch.
- Three initial baseline failures came from tests assuming the Lite checksum was
  still `pending`; it had already been populated before this task. Pending fixtures
  are now explicit. Existing fake lifecycle apps declare no listening port because
  they do not create a listener; separate readiness tests exercise network behavior.
- Reused existing environment, manifest, process-record and atomic-write mechanisms;
  runtime remains standard-library-only with no new dependency or launcher layer.

Refreshed archive: `farm-lite-patch/titanium-tiiny-bot-0.1.9.tar.gz`, **434,057 bytes**,
74 members; SHA-256:

```text
49ad7e973fef53f7c3049f7a39a2dfb29509a8e6ce25e760f996889d76cda797
```

### Changed files and remaining limits

Changed `farm/farm.py`, `tests/test_farm.py`, new `tests/test_device.py`,
`docs/manifest.schema.json`, `scripts/check-manifest.py`,
`manifests/titanium-tiiny-bot.json`, `README.md`, this report, and the Lite patch
README, cumulative patch, incremental patch and archive under `farm-lite-patch/`.
That artifact directory is already gitignored; its delivered files remain on disk.

The sandbox rejects loopback socket binding (confirmed by a direct CLI probe).
Farm tests therefore exercise actual subprocesses and lifecycle cleanup with
simulated TCP/HTTP transports; a real HTTP listener/busy-port end-to-end run could
not be performed here. No real Tiiny device, inference, microphone or GUI was used.
The public release remains unpublished/unverified; the manifest identifies the
local artifact, not a verified remote download. Port preflight cannot atomically
reserve a port until an independently launched app binds it; readiness additionally
checks the launched process remains alive. Other apps must honor `TINYAPP_PORT`
to support an override. HTTP probe threads are daemonized so a pathological response
cannot prevent the CLI from exiting at its deadline.
