# Can Jason announce tiinyapp.farm tomorrow? A launch gap analysis, 2026-09-13

## Verdict

Yes, with four things done first, and none of them is code. The farm works: farm 0.1.3 is on
PyPI, the whole owner path runs end to end from a clean virtual environment against the live
catalog, all 66 anonymous fetches answer as expected, 44 page loads across two browser engines
produce zero broken images, zero dead links, zero horizontal scroll and no console error that
is not an expected signed-out probe, the deploy-on-merge pipeline is green on its last six
pushes, and the submission checks post a readable results table on real pull requests. What is
not ready is the paperwork and one question only a Tiiny can answer. The repository is public
with no license while the farm requires every submitted app to declare one. The announcement
draft tells people nothing is reviewed, and every app page on the live site now reads
"Verified". Two of the four listed apps are pinned at 0.1.0 releases the brief says do not work
on Tiiny 1.0 firmware, and the draft's headline install command names one of them. And a fifth
app is sitting green and mergeable, which changes what the post says. Fix those four and the
announcement is true. Everything else on this page can ship broken and be fixed next week.

## How this was measured

One machine for every measured row: Jason's MacBook Pro (Mac17,6), macOS 26.6.2 (build 25G83),
Python 3.14.6, Node 22.23.1, home broadband in Central Texas, 2026-09-13 between 19:50 and
20:01 CDT. The site was the live one at https://tiinyapp.farm. The CLI came from the real PyPI
in a fresh virtual environment, never from this checkout. Browser work used playwright-core,
headless Chromium at 1440x900 and headless WebKit at 390x844, with no cookie and no session.
Screenshots of all 44 page loads are in `docs/launch-gap-shots/`.

No account was created, no form was submitted, no pull request was opened and nothing was
merged. Rows marked **planned** were reasoned about, not run, and say so.

## Blockers

Must be true before the post goes out.

| # | What | Owner | Next action | Time | Evidence |
| --- | --- | --- | --- | --- | --- |
| B-1 | The repository is public and has no license file. `pyproject.toml` declares none either, so PyPI shows `license: None`. Meanwhile the manifest schema makes `license` required and `docs/SUBMIT.md` step 1 tells makers to include theirs in the archive. The first stranger who opens a pull request is contributing under undefined terms | Jason | Add `LICENSE` at the repository root, add `license = "MIT"` and the matching classifier to `pyproject.toml`, commit to main | 10 min | **Measured** 20:00 CDT: `git ls-files` returns only the three font licenses under `site/fonts/`; PyPI JSON for tiinyapp-farm 0.1.3 reports `license = None` |
| B-2 | The catalog lists OneLane 0.1.0 and Story Lantern 0.1.0. Both repositories are at 0.1.1, and the brief says both 0.1.0 releases are known not to work on Tiiny 1.0 firmware. The announcement draft's headline command is `farm install story-lantern`, so the first thing a stranger runs would be the broken one | Jason, with a Tiiny on the desk | Install both from the live catalog on a machine with a Tiiny and see whether they work. If they do not, either land the 0.1.1 bumps (see B-2a) or change the post's example app to `titanium-tiiny-bot`, which is measured working | 20 min | **Planned.** This machine has no Tiiny, so nothing here can settle it. The refreshed announcement draft already uses `titanium-tiiny-bot` as its example, which removes the sharpest edge |
| B-2a | The 0.1.1 bumps that would fix B-2 are both red. Pull request 7 fails because OneLane's source tarball carries `examples/two_apps.py` and `tests/fake_device_test.py`, which import subprocess, and shell is forbidden. Pull request 8 fails because `device.py:39` in Story Lantern imports subprocess | Jason | Either move subprocess behind a lazy import the way Tiiny Brain did, and cut 0.1.2 tags, or publish a release asset that excludes examples and tests. A worker is replacing both pull requests tonight | 1 h | **Measured** 19:55 CDT from the check job logs: PR 7 job 103777168251 and PR 8 job 103777190409, both failing at "Validate submissions and TiinyVerse ownership", static scan FAIL with those exact file and line numbers |
| B-3 | The announcement draft contradicts the live site. It says "There are no reviews on anything yet, including my own four apps". All four manifests carry `verified: true` and all four app pages read "Verified" | Jason | Read the refreshed `docs/ANNOUNCE.md` in this commit, which fixes that line and the app count, then change whatever still sounds wrong and post it | 5 min | **Measured** 19:58 CDT: all four manifests parse with `verified: true`; the rendered page for titanium-tiiny-bot contains "Verified" |
| B-4 | Tiiny Brain 0.1.0 (pull request 9) is green, mergeable and clean, and would make the catalog five apps. Whether it is in changes the post's numbers and its list of apps | Jason | Decide, then merge before posting if in. It belongs in. See "The four open pull requests" below | 5 min | **Measured** 19:53 CDT: every check SUCCESS, `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`. Its archive downloaded here hashes to `0c0d7c50...b5a3d` at exactly 48424 bytes, which equals the manifest |

## Should

Announce anyway. Fix these this week.

| # | What | Owner | Next action | Time | Evidence |
| --- | --- | --- | --- | --- | --- |
| S-1 | Ten documentation pages are live and the header never mentions them. Every page's navigation is Apps, Catalog, Install, Submit an app, Sign in, including `/docs/` itself, which does not highlight where you are. Documentation is one footer link | Jason | Add Docs to the navigation list in `scripts/build-site.py` beside Install, and let `/docs/` mark itself current. Cheap enough to land before the post | 15 min | **Measured** 20:00 CDT: the nav and footer link sets are identical on `/`, `/catalog/`, `/install/`, `/docs/` and `/apps/onelane/`. Docs appears only in the footer |
| S-2 | Featured is the whole catalog. All four manifests carry `featured: true`, so the same four apps fill the "Featured, picked by the maintainers" shelf and the "All apps" list below it | Jason | Merging Tiiny Brain fixes half of this on its own, because it carries no `featured` flag and the shelf becomes four of five. Then pick one or two deliberately and clear the rest | 10 min | **Measured** 19:58 CDT from the four manifests and from the rendered home page, which shows OneLane, Story Lantern, TiinyBench and Titanium Tiiny Bot under Featured and again below |
| S-3 | No app in the catalog has a screenshot. All four pages end at "No screenshots yet" while the submit form asks makers for up to eight | Jason | Add two to `titanium-tiiny-bot` and two to `tiiny-bench` so the farm does what it asks of makers. Tiiny Brain already ships an icon and a header image, which is more art than any of the four | 30 min | **Measured** 19:58 CDT: `screenshots` is an empty array in all four manifests |
| S-4 | `docs/LAUNCH.md` sends the operator to fix two things that are already fixed. Step 1 says the deploy workflow has never worked for want of a Cloudflare token. Step 2 says the PyPI trusted publisher is not set up. Both are working today | Jason | **Fixed in this commit.** Steps 1 and 2 are now marked done with today's measurement, matching what step 4 already said. Read the go and no-go checklist below instead of walking LAUNCH.md tomorrow | done | **Measured** 19:57 CDT: the last six "Build and deploy the farm" runs on main all succeeded, the newest at 22:57 UTC; the publish workflow succeeded for 0.1.2 and 0.1.3, and PyPI serves both |
| S-5 | A wall-clock assertion can turn any pull request red. `test_health_trickling_response_cannot_exceed_readiness_deadline` asserts a deadline under 0.45 seconds and measured 0.4926 on a GitHub ubuntu runner at Python 3.9. It reddened pull request 8 for a reason that has nothing to do with pull request 8 | Jason | Widen the bound, or assert the number of polls instead of elapsed time. A flaky red on a stranger's first submission is the worst place for this to land | 20 min | **Measured** 19:55 CDT from job 103777190403: `AssertionError: 0.4925659789999983 not less than 0.45`, 66 tests, 1 failure |
| S-6 | The check bot reports a failed scan as raw JSON. The results comment's detail column prints `[{"file": "onelane-0.1.1/examples/two_apps.py", "line": 20, ...}]` where a sentence belongs. This is the same class of problem the use-check just fixed in the install prompt | Jason | Render the findings as one line per file and line number in plain words | 20 min | **Measured** 19:56 CDT from the bot comment on pull request 7 |
| S-7 | `farm start` does not name the port it bound. `docs/LAUNCH.md` step 3 tells the operator to watch for exactly that. It prints the pid and the log path and nothing else. `farm status` does carry the port | Jason | Add the port to the start line, or drop the expectation from LAUNCH.md | 10 min | **Measured** 20:01 CDT: `farm start story-lantern --port 7871` answered `Started story-lantern: pid 10955; log .../farm.log`. The app did bind 7871, confirmed by a 302 from `http://127.0.0.1:7871/` |
| S-8 | `farm release` is documented as a command on `/docs/cli/` and `/docs/publish/` and is not in the published package. Both sections carry a visible note saying it arrives with pull request 5 and is not live until that merges, which is honest. What is not marked is the on-page index at the top of `/docs/cli/`, which lists farm release beside ten commands that do exist | Jason | Mark it in the index too, or merge pull request 5 | 10 min | **Measured** 19:59 CDT: `farm --help` from PyPI 0.1.3 lists install, update, start, stop, remove, device, login, publish, status, list. `farm release` answers `invalid choice: 'release'`. The live page's note renders as `<p class="note">` |

## Nice

Neither blocks nor needs this week.

| # | What | Owner | Next action | Time | Evidence |
| --- | --- | --- | --- | --- | --- |
| N-1 | An unknown maker URL returns bare JSON instead of the site's own 404 page. `/makers/nobody/` answers 404 with `{"error":"That maker was not found."}` as `application/json`, so a mistyped maker link shows a browser's raw JSON view | Jason | Return the built 404 page for `/makers/*` misses, keeping JSON only when the request asks for it | 20 min | **Measured** 19:52 CDT by curl and again in both browser engines, where the page has no title and no images |
| N-2 | Tiiny Brain cannot be moved off its port and the manifest has no way to say so. `cockpit.py:705` reads the port from `sys.argv[1]` with a default of 8500 and the archive never mentions `TIINYAPP_PORT`. The `port` field understands a flag, an environment variable, or null, and has no word for a bare positional argument | Jason | Add `--port` to `cockpit.py` and set `{"argv": "--port"}` in the manifest. Until then `farm start tiiny-brain --port N` will not move it, though 0.1.3 diagnoses the failure instead of hiding it | 20 min | **Measured** 19:51 CDT by reading the released archive, not a local checkout: grep for TIINYAPP_PORT across the unpacked tarball returns nothing |
| N-3 | `/submit/done/` logs a 401 to the browser console when signed out. It is the session probe doing its job, and nothing visible breaks | Jason | Swallow the expected 401 so a clean page has a clean console | 10 min | **Measured** 19:54 CDT in both engines: one console error on that page, none on the other twenty |
| N-4 | `scripts/check-live.py` does not sweep the documentation site. It covers 33 paths including `/docs/agents/`, and the sitemap lists `/docs/` and nine more pages it never fetches | Jason | Add the docs pages to the path list so a broken docs deploy fails the sweep | 15 min | **Measured** 19:50 CDT: the sweep reports 33 paths and 66 fetches; the live sitemap lists 19 URLs including ten under `/docs/` |
| N-5 | `SPEC.md` names the wrong device config path. It says `~/tiinyapps/device.json`; the code and the live install page both say `~/.tiinyapps/device.json` | Jason | One word in SPEC.md. Carried from the use-check as row F-6 | 2 min | **Measured** 20:01 CDT: a real run wrote `~/.tiinyapps/device.json` and created no `device.json` under `~/tiinyapps` |

## The four open pull requests

| PR | What | State | Read |
| --- | --- | --- | --- |
| 5 | The release path. An hourly poller, a "Check for a new release" button, and `farm release` | All nine checks green, mergeable and clean | Not needed for launch, and the documentation already tells readers it is not live. It needs two GitHub App secrets before any of it works, per `docs/GITHUB-APP.md`. Merging it without those secrets leaves the poller reporting that it is switched off, which is safe but pointless. Leave it until after the announcement |
| 7 | OneLane 0.1.1 | Static scan FAIL | Subprocess in `examples/two_apps.py:20` and `tests/fake_device_test.py:17`. The GitHub source tarball carries the whole repository, examples and tests included, so the scan sees code the app never runs. Being replaced tonight |
| 8 | Story Lantern 0.1.1 | Static scan FAIL, plus one flaky test | Subprocess in `device.py:39`, which is real application code, not a test. Needs the Tiiny Brain treatment: one lazy import behind the thing that needs it. Being replaced tonight |
| 9 | Tiiny Brain 0.1.0 | All nine checks green, mergeable and clean | **It belongs in the launch catalog.** See below |

### Tiiny Brain

Merge it. Four reasons, three of them measured here rather than taken from the pull request.

The archive is what the manifest says it is. Downloaded from the release URL on this machine, it
hashes to `0c0d7c50565c78f9ff5f07d5057011005034742aa4012026d1773b54b90b5a3d` at exactly 48424
bytes, which matches the manifest byte for byte. Every check on the pull request passed,
including the offline selfcheck, and the results comment says so in the same table a stranger
would get.

It is the only submission that did the subprocess work voluntarily. The author split the PDF
scanning half out of the archive and moved poppler and tesseract behind a lazy import so
`archive.py` imports no subprocess at all. That is exactly what pull requests 7 and 8 are red
for not doing, and it is a useful thing to point at when the first outside maker hits the same
wall.

It fixes the featured shelf by existing. It carries no `featured` flag, so the home page becomes
four featured out of five apps instead of four out of four, and the shelf starts meaning
something.

The test it changes is not a weakened test. `test_home_uses_featured_editorial_items_and_ledger_rows`
built the featured list as a filtered, capped subset and then asserted that every app in the
catalog is featured, which cannot both be what the test means. The two assertions that carry the
real invariant are untouched: the count of featured articles still has to equal the filtered
list, and the count of catalog rows still has to equal every manifest. Removing the contradiction
is the right fix, and the pull request says so up front instead of burying it.

Two things to settle before or just after merging. Its manifest carries `verified: false`, which
is what `docs/SUBMIT.md` tells submitters to do, so its page will read "Not reviewed yet" beside
four that read "Verified". That is honest and it shows the review step is real, but it is Jason's
call whether the fifth app launches reviewed. And `farm start tiiny-brain --port N` will not move
it, for the reason in N-2.

## Go and no-go, tomorrow morning

Ten minutes, top to bottom, from a checkout of main on the Mac. Stop at the first no.

```sh
cd ~/code/tiinyapp-farm && git checkout main && git pull
```

1. **The site answers everyone.** `python3 scripts/check-live.py` ends with "All 66 fetches
   answered as expected" and exits 0. Anything else is a no. About 8 seconds.
2. **PyPI serves the CLI people will install.**
   `curl -s https://pypi.org/pypi/tiinyapp-farm/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"`
   prints 0.1.3 or newer. About 2 seconds.
3. **A stranger's install works.** In a scratch directory:
   `python3 -m venv v && ./v/bin/pip install tiinyapp-farm && ./v/bin/farm list`
   lists every app in the catalog. About 10 seconds.
4. **The license exists.** `ls LICENSE` finds a file and `grep license pyproject.toml` finds a
   line. This is B-1 and it is the one item that is pure typing. Instant.
5. **The announcement is true.** Open `docs/ANNOUNCE.md`, read the refreshed draft, and check
   three things against the live site: the number of apps, whether it claims anything is
   unreviewed, and which app the headline install command names. About 3 minutes.
6. **Decide Tiiny Brain.** If in, merge pull request 9 and watch the deploy go green:
   `gh run list --repo Titanium-Devops/tiinyapp-farm --workflow "Build and deploy the farm" --limit 1`.
   Then reload https://tiinyapp.farm/apps/tiiny-brain/ and confirm the page exists. About 3
   minutes.
7. **The firmware question.** If a Tiiny is on the desk, `farm install story-lantern` and
   `farm start story-lantern` and see whether it works. If no Tiiny, the refreshed draft already
   leads with `titanium-tiiny-bot`, so this is not a stop. This is B-2.
8. **Post it.**

Nothing in that list needs the Cloudflare dashboard, a GitHub secret or a PyPI setting. All
three were open questions in `docs/LAUNCH.md` and all three were measured working today.

## What this could not measure

- **Anything that needs a Tiiny.** No device on this machine. Whether the four listed apps do
  useful work against real firmware, and specifically whether OneLane 0.1.0 and Story Lantern
  0.1.0 fail on Tiiny 1.0 as the brief says, is untested here. That is B-2 and it is the one leg
  only an operator with hardware can walk.
- **Anything behind a sign-in.** No account was created, so email codes, GitHub sign-in,
  TiinyVerse profile verification, the submit form itself, media upload, `farm publish` with a
  real token and the pull request it opens were read and never exercised. The submission path is
  proven from the other end instead: pull requests 7, 8 and 9 all ran the real checks and all
  three carry the bot's results table.
- **`farm update` actually installing a newer version.** Every app is at its catalog version, so
  every update takes the no-op path.
- **Windows and Linux.** macOS only, though the test matrix covers both on every pull request.
