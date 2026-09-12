# Phase 2 report

Completed in phase order on 2026-09-12: static builder, approved design styling,
deployment configuration, tests and this report. The site is built locally in
`site/dist/`. It has not been deployed or committed.

## 1. Site builder

Added `scripts/build-site.py`, using only the Python standard library. Run:

```sh
python3 scripts/build-site.py
python3 -m unittest
```

The builder reads and validates every `manifests/*.json`, produces one field plot
and `/apps/<id>/` page per manifest, and copies the original manifest bytes to
`/manifests/<id>.json`. `/manifests/` serves HTML links understood by the existing
installer at its default catalog URL, `https://tiinyapp.farm/manifests/`.

Generated output includes the field, three app pages, `/plant/`, `/seeds/`, the
catalog index, `404.html`, sitemap, robots file, schema, stylesheet, hero and brand
assets: 19 files, including eight HTML pages. Rebuilds remove stale output.
`--today YYYY-MM-DD` makes badge tests reproducible; normally the build uses UTC.
`--output PATH` selects a different generated-output directory.

App pages explain the full manifest: description, requirements, models, NPU units,
ports, permissions, install and start commands, actual launcher entry, screenshots,
author, license, homepage, repository, tags, dates, verification, archive URL,
checksum, byte size and optional health endpoint. Libraries explicitly have
nothing to start. Pending and unpublished release notes remain visible.

Verified follows the manifest boolean. New means an added date from today through
29 days ago, excluding future dates. Library follows a null entry. Badges can
coexist. No JavaScript is needed or shipped.

**Input discrepancy:** Phase 2 says four manifests, but this checkout contains only
Titanium Tiiny Bot, Story Lantern and OneLane. `docs/APPS.md` explicitly defers
Tiiny Bench until it has a selfcheck and release, and the existing manifest test
expects three. No fourth app or release metadata was invented. The builder's
four-manifest behavior is tested with a temporary fourth seed, including its page,
manifest copy, screenshot, command entry and removal on rebuild. Four real app
pages remain dependent on the missing Tiiny Bench manifest.

## 2. Design and phone sizing

Added `site/assets/site.css` using all ten color tokens verbatim from
`site/design/mockup-approved.html`: night, soil, fence, hay, cyan, mint, ink, mute
and berry. Fraunces and Nunito load through Google Fonts with Georgia and system
fallbacks. Cards retain the mockup's gradient, fence, badges and planted-row detail.

The supplied 1600 by 1066 JPEG is served unchanged as `/assets/hero.jpg`, never a
data URI. The footer links the Titanium Bot mark and “Brought to you by Titanium
Bot” to `https://titanium.bot`; “Built for” and the supplied Tiiny logo link to
`https://tiiny.ai`. All supplied brand SVGs are copied unchanged.

Static sizing at 390 px:

- The page has 24 px padding on each side: 342 px available.
- Field cards use one column; 18 px padding and 1 px borders leave 304 px inside.
- Step cards also use one column. Grid minimums are capped at 100% of available width.
- Navigation, badge rows, install rows and footer marks wrap. Children have
  `min-width: 0`; links and images have `max-width: 100%`.
- Commands and checksums wrap with `white-space: pre-wrap` and
  `overflow-wrap: anywhere`, without truncation or horizontal scroll containers.
- Hero text remains in normal flow through 700 px. The desktop overlay starts at
  701 px, so long phone copy cannot overlap or escape the hero image.
- Every interactive element is an anchor with at least 44 px width and height.
  There are no small icon buttons. Keyboard focus and a skip link are provided.

These constraints support a no-overflow layout at 390 px by static reasoning.
No rendered measurement or screenshot fidelity score is claimed. The local
visual-verdict state records that screenshot comparison was not run because of
the explicit browser/GUI prohibition.

Mockup copy was adjusted where source evidence differs: no unsupported promise
that nothing leaves the house, no fabricated verification, and no claim that all
apps already cooperate with OneLane. Farmhand setup installs from the source
checkout without assuming a published package exists.

## 3. Deployment handoff

Added `wrangler.toml` for Worker `tiinyapp-farm`, assets at `./site/dist`, custom
domain `tiinyapp.farm`, trailing-slash HTML routes and a custom 404 response.
No Worker JavaScript is necessary for this static site.

Added `.github/workflows/site.yml`. It builds and runs the full unit suite on
main pushes and pull requests. Only a push to main reaches
`cloudflare/wrangler-action@v3` with `command: deploy`, which runs the requested
wrangler deployment. It reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`
from repository secrets. The orchestrator must set those secrets, ensure the
Cloudflare zone is active and perform the first deployment by hand.

Configuration was checked against Cloudflare's official
[static-site and custom 404 documentation](https://developers.cloudflare.com/workers/static-assets/routing/static-site-generation/)
and [custom-domain configuration](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/).
Documentation was retrieved as text; no browser was launched.

## 4. Verification

| Check | Result |
| --- | --- |
| `python3 scripts/build-site.py` | Passed, three supplied apps, 19 generated files |
| `python3 -m unittest` | Passed, 68 tests in 14.707 seconds |
| `python3 -m unittest tests.test_site` | Passed, 11 site tests; repeated after final logo sizing |
| `ruff check farm scripts tests` | Passed |
| `mypy --follow-imports=silent farm scripts` | Passed, four source files |
| `mypy --follow-imports=silent scripts/build-site.py tests/test_site.py` | Passed, two source files |
| `python3 -m compileall -q scripts tests farm` | Passed |
| `actionlint .github/workflows/site.yml` | Passed |
| Git whitespace check and final source whitespace scan | Passed |

Site tests cover all generated pages, full manifest presentation, byte-identical
copies, every internal HTML link and fragment, hero and both marks, font and token
references, no em dashes or single-i brand spelling in generated HTML, no embedded
images or JavaScript, badge boundaries, four-manifest generation, screenshot and
command entries, escaped text, stale-page removal, installer catalog parsing,
sitemap coverage, schema field documentation, phone CSS constraints, deployment
settings and invocation from outside the repository.

## Changed files and remaining limits

- `scripts/build-site.py`: stdlib static builder and shared HTML rendering.
- `site/assets/site.css`: shared responsive styling using the approved tokens.
- `wrangler.toml`: Workers assets and custom-domain configuration.
- `.github/workflows/site.yml`: build, test and main-only deployment.
- `tests/test_site.py`: 11 static-site contract tests.
- `docs/PHASE-2-REPORT.md`: this report.

Generated `site/dist/` remains ignored by the existing `dist/` rule and is rebuilt
by CI. Existing manifests, installer code and approved mockup were not changed.
Shared templates and one stylesheet avoid duplicated page sources, framework
code, client rendering and new Python dependencies.

Remaining limits: Tiiny Bench has no manifest; source manifests describe pending
or unpublished releases, unconfirmed licenses and no farmhand verification.
External release availability was not tested. New badges reflect the last build
and need a rebuild to age out. Browser rendering, live Cloudflare routing, DNS,
credentials and deployment remain untested as required. No browser, GUI or
wrangler process was launched; no commit was attempted.
