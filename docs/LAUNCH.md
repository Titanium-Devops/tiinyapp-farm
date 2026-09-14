# Launch day

Run this top to bottom. Everything in "Operator does" needs a person with credentials or a
Tiiny on the desk. Everything in "Already verified" was measured before launch day and does
not need repeating unless the code moved.

## Operator does

### 1. Give the deploy workflow its Cloudflare token. DONE, nothing to do

The token was added between the launch pass and 2026-09-13. Re-measured that day at 19:57 CDT
from Jason's MacBook Pro (Mac17,6), macOS 26.6.2, on home broadband in Central Texas: the last
six `Build and deploy the farm` runs on main all succeeded, the newest at 22:57 UTC for
`farm 0.1.3`. Deploy on merge works. Check it again after any secret rotation:

```sh
gh run list --repo Titanium-Devops/tiinyapp-farm --workflow "Build and deploy the farm" --limit 1
```

The rest of this step is the launch-pass text and no longer describes the repository.

Deploy on merge is wired in `.github/workflows/site.yml` and it has never worked. The repo
has `CLOUDFLARE_ACCOUNT_ID` but not `CLOUDFLARE_API_TOKEN`, so the `site` job fails on every
push to main with this:

```
In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment
variable for wrangler to work.
```

Create the token at https://dash.cloudflare.com/profile/api-tokens with the "Edit Cloudflare
Workers" template, scoped to the account that owns the `tiinyapp-farm` Worker (account id
`5a845e69fbed4f4e64e2176d86637680`, in `wrangler.toml`). The Worker needs Workers Scripts
edit, Workers KV edit, and R2 edit, which that template covers.

```sh
gh secret set CLOUDFLARE_API_TOKEN --repo Titanium-Devops/tiinyapp-farm
gh secret list --repo Titanium-Devops/tiinyapp-farm
```

Then prove it on a real push rather than trusting the secret list:

```sh
gh run list --repo Titanium-Devops/tiinyapp-farm --workflow "Build and deploy the farm" --limit 1
gh run watch <run-id> --repo Titanium-Devops/tiinyapp-farm
```

### 2. Set up the PyPI trusted publisher. DONE, nothing to do

The publisher was added between the launch pass and 2026-09-13. Re-measured that day at 19:57
CDT, same machine: the `Publish farm to PyPI` workflow succeeded for 0.1.2 at 22:34 UTC and for
0.1.3 at 22:57 UTC, and PyPI serves both. Cutting the next version is now a tag push and
nothing else:

```sh
curl -s https://pypi.org/pypi/tiinyapp-farm/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
```

The rest of this step is the launch-pass text and no longer describes the project.

`tiinyapp-farm` 0.1.0 and 0.1.1 are on PyPI, but the publish workflow did not put them
there. Both tag pushes failed with `invalid-publisher: valid token, but no corresponding
publisher`, so the next tag fails the same way until this is done once.

Go to https://pypi.org/manage/project/tiinyapp-farm/settings/publishing/ and add a GitHub
publisher with exactly these values, which are the claims the failed run printed:

| Field | Value |
| --- | --- |
| Owner | `Titanium-Devops` |
| Repository name | `tiinyapp-farm` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

The `pypi` environment already exists on the repo, so nothing is needed on the GitHub side.
Then cut the next version and watch it publish itself:

```sh
# bump project.version in pyproject.toml first
git tag v0.1.2 && git push origin v0.1.2
gh run list --repo Titanium-Devops/tiinyapp-farm --workflow "Publish farm to PyPI" --limit 1
```

A clean run ends with files at https://pypi.org/project/tiinyapp-farm/ whose upload time
matches the run.

### 3. Run the installer against a real Tiiny

This is the one leg nothing here can fake, because the machine that ran the pre-launch
checks has no Tiiny on it. Every device call so far was a fake. On a computer with a Tiiny
reachable, from a shell with nothing installed:

```sh
pip install tiinyapp-farm          # pipx install tiinyapp-farm on Homebrew Python or Debian
farm --version
farm device                        # base URL and API key, asked once, saved 0600
farm install titanium-tiiny-bot
farm start titanium-tiiny-bot
farm status
farm stop titanium-tiiny-bot
```

Then install one app that is not Titanium's own, so the catalog path gets exercised end to
end by a stranger's manifest shape:

```sh
farm install tiiny-bench && farm start tiiny-bench
open http://localhost:8425
farm stop tiiny-bench
```

What to watch for: `farm device` must refuse to echo the key, `farm status` must report the
version the app's health endpoint claims, and the start line must name the port it bound.

### 4. Let the standard library read the site. DONE, nothing to do

Someone widened the rule between the launch pass and 2026-09-13. Re-measured that day at
22:10 UTC from Jason's MacBook Pro (Mac17,6), macOS 26.6.2, Python 3.14.6, on home
broadband in Central Texas: `python3 scripts/check-live.py` answers **All 66 fetches
answered as expected**, both columns green, including `/docs/agents/` and `/` to the
default `Python-urllib` user agent. The red table under "The stranger sweep" below is the
launch-pass measurement and no longer describes the site. Run it again after any zone
change:

```sh
python3 scripts/check-live.py
```

Both columns stay green, or a zone change broke it again.

### 5. Deploy, with a sweep on each side of it

```sh
python3 scripts/check-live.py                 # before
python3 scripts/build-site.py && wrangler deploy
python3 scripts/check-live.py                 # after
```

The sweep fetches every public page as an anonymous visitor and fails loudly on anything
that is not 200, or not 302 for `/account/`. Run it with `--json` to keep a record.

### 6. Post the announcement

`docs/ANNOUNCE.md` holds the TiinyVerse post and a 280-character version. Both are drafts
for Jason to read before anything goes out.

## Already verified

Measured 2026-09-12 and 2026-09-13 UTC on Jason's MacBook Pro (Mac17,6), macOS 26.6.2,
Python 3.14.6, against the live site at https://tiinyapp.farm.

- A brand new user's path works on a Mac: `pip install tiinyapp-farm` (0.1.1 from PyPI),
  `farm install titanium-tiiny-bot -y`, `farm start titanium-tiiny-bot --port 7799`,
  `farm stop`.
- `farm start` with the default port taken answers
  `Port 7788 is already in use; use farm start titanium-tiiny-bot --port N.` and exits 1.
- All four catalog releases download and match their manifests. Fetched anonymously, each
  archive's byte count and SHA-256 equal the manifest values: `onelane` 0.1.0 (168709 B),
  `story-lantern` 0.1.0 (3676365 B), `tiiny-bench` 0.1.0 (2333494 B), `titanium-tiiny-bot`
  0.1.10 (433818 B).
- `FARM_CATALOG=https://tiinyapp.farm/manifests/ python3 farm/farm.py list` lists all four
  apps from the live catalog with no device configured.
- `python3 -m unittest`: 126 passed, 1 skipped, 24 s. `tests/test_share.py` and
  `tests/test_site.py` import Pillow, so the suite needs `python3 -m pip install pillow`;
  the skip is a Windows-only process identity test.
- `python3 scripts/build-site.py`: builds 4 app pages.
- The catalog holds 4 apps, every one by Jason Brashear or Titanium Computing.
- Trailing-slash redirects work: `/install`, `/catalog`, `/submit`, `/docs/agents` and
  `/apps/<id>` all 307 to the slashed form, so a pasted link without the slash still lands.

## The stranger sweep

`scripts/check-live.py` fetches every public page and file with no cookie and no session,
twice: once with a plain `Mozilla/5.0` user agent and once with whatever urllib sends by
default. Run it before the deploy and again after.

```sh
python3 scripts/check-live.py
python3 scripts/check-live.py --json     # keep the record
python3 scripts/check-live.py --origin https://staging.example
```

It expects 200 everywhere and 302 on `/account/`, prints a failure list, and exits 1 if
anything answers differently. App pages, share cards and manifests come from the
`manifests/` folder in the checkout, so a new app is swept without editing the script.

**Superseded.** The table below is the launch-pass run of 2026-09-12 21:47 CDT and is kept
as history. The same script on 2026-09-13 22:10 UTC, same machine, answers "All 66 fetches
answered as expected", so the python column is green now. Read this table only to see what
the Cloudflare rule used to do.

Run 2026-09-12 21:47 CDT from Jason's MacBook Pro (Mac17,6), macOS 26.6.2, Python 3.14.6,
on home broadband in Central Texas. 33 paths, 66 fetches, 25 of them wrong, all 25 in the
python column and all of them Cloudflare error 1010. The browser column is clean.

| path | want | browser status | browser bytes | browser ms | python status | python bytes | python ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/` | 200 | 200 | 12874 | 104 | 403 | 17 | 41 |
| `/catalog/` | 200 | 200 | 4206 | 77 | 403 | 17 | 43 |
| `/install/` | 200 | 200 | 4895 | 74 | 403 | 17 | 43 |
| `/submit/` | 200 | 200 | 19725 | 62 | 403 | 17 | 114 |
| `/submit/done/` | 200 | 200 | 19735 | 66 | 403 | 17 | 45 |
| `/docs/agents/` | 200 | 200 | 9915 | 60 | 403 | 17 | 43 |
| `/llms.txt` | 200 | 200 | 6349 | 61 | 200 | 6349 | 68 |
| `/robots.txt` | 200 | 200 | 66 | 137 | 403 | 17 | 46 |
| `/sitemap.xml` | 200 | 200 | 667 | 61 | 403 | 17 | 43 |
| `/catalog.json` | 200 | 200 | 6801 | 88 | 200 | 6801 | 63 |
| `/categories.json` | 200 | 200 | 380 | 66 | 200 | 380 | 129 |
| `/site.webmanifest` | 200 | 200 | 317 | 60 | 403 | 17 | 41 |
| `/assets/site.css` | 200 | 200 | 26744 | 70 | 403 | 17 | 42 |
| `/assets/farm.js` | 200 | 200 | 11772 | 64 | 403 | 17 | 45 |
| `/assets/session.js` | 200 | 200 | 1924 | 64 | 403 | 17 | 125 |
| `/brand/og-image.png` | 200 | 200 | 459872 | 105 | 403 | 17 | 49 |
| `/brand/favicon.ico` | 200 | 200 | 16406 | 73 | 403 | 17 | 47 |
| `/docs/SUBMIT.md` | 200 | 200 | 6619 | 87 | 403 | 17 | 49 |
| `/docs/manifest.schema.json` | 200 | 200 | 7298 | 136 | 403 | 17 | 44 |
| `/manifests/` | 200 | 200 | 2925 | 61 | 200 | 2925 | 53 |
| `/account/` | 302 | 302 | 0 | 65 | 403 | 17 | 55 |
| `/apps/onelane/` | 200 | 200 | 6980 | 76 | 403 | 17 | 113 |
| `/apps/onelane/card.png` | 200 | 200 | 342216 | 95 | 403 | 17 | 52 |
| `/manifests/onelane.json` | 200 | 200 | 1647 | 62 | 200 | 1647 | 57 |
| `/apps/story-lantern/` | 200 | 200 | 7392 | 78 | 403 | 17 | 114 |
| `/apps/story-lantern/card.png` | 200 | 200 | 459982 | 112 | 403 | 17 | 46 |
| `/manifests/story-lantern.json` | 200 | 200 | 2111 | 59 | 200 | 2111 | 68 |
| `/apps/tiiny-bench/` | 200 | 200 | 7365 | 72 | 403 | 17 | 45 |
| `/apps/tiiny-bench/card.png` | 200 | 200 | 374750 | 176 | 403 | 17 | 52 |
| `/manifests/tiiny-bench.json` | 200 | 200 | 2059 | 63 | 200 | 2059 | 64 |
| `/apps/titanium-tiiny-bot/` | 200 | 200 | 7053 | 74 | 403 | 17 | 43 |
| `/apps/titanium-tiiny-bot/card.png` | 200 | 200 | 287995 | 149 | 403 | 17 | 44 |
| `/manifests/titanium-tiiny-bot.json` | 200 | 200 | 1789 | 91 | 200 | 1789 | 66 |

Two things to know before reading the numbers. The byte counts in the browser column are
367 bytes larger than a `curl` fetch of the same page, because Cloudflare injects its Web
Analytics beacon into HTML for some clients and not others. And the millisecond column is
network time from one house in Texas, so it says the site is up, not that it is fast.

### Why the python column is red

Cloudflare answers `Python-urllib/3.x` with `error code: 1010` on most of the site. It is
the browser integrity check refusing a user agent it does not like. Something already
exempts the paths the installer needs, which is why `/llms.txt`, `/catalog.json`,
`/categories.json`, `/manifests/` and every `/manifests/<id>.json` answer 200 in both
columns, and why `/api/*` reaches the Worker. Everything a person or an assistant would
read is refused.

The one that matters is `/docs/agents/`. The prompt in the submit help modal tells a maker
to hand their assistant `Read https://tiinyapp.farm/docs/agents and publish this project`.
An assistant that fetches it with Python's standard library gets 403 and no explanation.
The `farm` CLI is fine, it sends `tiinyapp-farm/<version>`, and so are curl, requests and
node.

Operator action: in the Cloudflare dashboard for the `tiinyapp.farm` zone, find the
configuration rule that already exempts the catalog paths and widen it to the whole site,
or turn the browser integrity check off for this zone. The CLI stopped depending on a
permissive user agent in 0.1.1, so nothing on the farm needs that check. Re-run the sweep
after; both columns should go green.

## Found in the launch pass

Ordered by what a first outside maker hits first. Four are fixed on this branch, the rest
need a decision.

1. **Fixed. The AI path in the release-link help modal numbered its second step 4.**
   `scripts/submit-page.html:64`. The modal a maker opens from Release URL showed steps "1"
   then "4" on the "I ask an AI assistant" tab. It is now 2.
2. **Fixed. A CI deploy would have shipped different routing than a hand deploy.**
   `.github/workflows/site.yml:56`. `cloudflare/wrangler-action@v3` installs wrangler 3.90.0
   by default, and wrangler 3 does not understand `run_worker_first` in `wrangler.toml`. It
   warned `Unexpected fields found in assets field: "run_worker_first"` and would have
   deployed without worker-first routing for `/api/*`, `/account/*`, `/makers/*` and
   `/media/*`, which is sign-in, publishing and maker pages. The action is now pinned to the
   wrangler the operator deploys with by hand, 4.131.1.
3. **Fixed. `farm --version` printed 0.1.0 from a checkout.** `farm/farm.py:1016`. The
   fallback for a source run was a literal left at 0.1.0. It now reads `pyproject.toml`, so
   the README's `python3 farm/farm.py` path reports the version it actually is.
4. **Fixed since the launch pass.** The footer no longer links `/docs/SUBMIT.md` at all:
   on 2026-09-13 it carries Submit an app, AI guide and Manifest schema, none of which
   download. `/docs/SUBMIT.md` is still served as `text/markdown`, so keep it out of
   footers. Original entry: **the footer's only contributor-guide link downloads a file.** `scripts/build-site.py:167`
   links `/docs/SUBMIT.md`, which Cloudflare serves as `content-type: text/markdown`. Chrome
   and Safari download that instead of showing it, so the first maker who clicks Contributor
   guide gets a file in their Downloads folder. Fixing it properly means either a built HTML
   page at `/docs/submit/` or adding `/docs/*.md` to `run_worker_first` and rewriting the
   content type in the Worker. Next action: build the HTML page in the next site pass, since
   the routing change touches the one list that controls sign-in.
5. **Fixed since the launch pass.** All four manifests now carry `"verified": true` and the
   app pages read "Verified". Original entry: **nothing in the catalog is reviewed,
   including Titanium's own apps.** All four manifests
   carry `"verified": false`, so every app page reads "Not reviewed yet" while
   `docs/SUBMIT.md` tells makers a maintainer sets `verified: true` after review. A newcomer
   reads both and concludes nobody reviews anything. Next action: Jason reviews the four and
   sets `verified: true` in a follow-up commit, or the copy stops promising it for launch.
6. **Featured is the whole catalog.** All four manifests carry `"featured": true`, so the
   home page shows the same four apps under "Featured, picked by the maintainers" and again
   under "All apps". The first outside app lands below four Titanium apps in a shelf labelled
   as a maintainer's pick. Next action: pick one or two to feature, or drop the shelf until
   there are apps to choose between.
7. **The API calls an app a seed.** `docs/agents.txt` documents `POST /api/seeds` and
   `PUT /api/seeds/<id>`, which is the word the style lock retired, on the surface an
   assistant reads. Renaming the route breaks the 0.1.1 CLI already on PyPI and the Worker
   routes in `worker/seeds.mjs`, so this is a deliberate carry, not an oversight. Next
   action: leave it until a CLI release can add the new route with the old one aliased.
8. **No app has a screenshot.** Every app page ends at "No screenshots yet", including the
   flagship. The submit form asks makers for up to eight. Next action: add two to
   `titanium-tiiny-bot` and `tiiny-bench` so the form's ask is something the farm does too.
9. **Fixed since the launch pass**, re-measured 2026-09-13: all 66 fetches green, both
   columns. Original entry: **Cloudflare refuses the Python standard library on every page
   a person reads.**
   `scripts/check-live.py` found it. 25 of 66 anonymous fetches answered `error code: 1010`
   to the default `Python-urllib` user agent, including `/docs/agents/`, the page the submit
   help modal tells makers to hand their assistant. The installer's own paths are already
   exempt. See "Why the python column is red" above for the dashboard action.
10. **Fixed. The test suite printed "Farm token saved." after it said OK.**
    `tests/test_farm.py:233`. The login test let the CLI's own line escape to stdout, which
    reads like the suite wrote to `~/.tiinyapps/token`. It never did, it uses a temporary
    directory. The test captures that line now and asserts it.
