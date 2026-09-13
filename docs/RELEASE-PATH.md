# The release-to-listing path

Brief from Jason, 2026-09-13 13:42 CDT. Build the release-to-listing path so a maker's new GitHub
release reaches the catalog without anyone typing a manifest by hand. Work on a branch, open a PR,
never push to main. Plain engineer's voice in commits and the PR. No em dashes anywhere. Spell it
Tiiny.

Context you can rely on. Each app is one JSON manifest in manifests/ with id, version, repo,
release.url, release.sha256, release.size, and requires/permissions. Listings install from the
release tarball at release.url, so every listed repo is public. PRs on the farm already run
manifest checks (checksum, archive scan, schema, no secrets) and a maintainer merges;
deploy-on-merge to Cloudflare works as of today (the CLOUDFLARE_API_TOKEN secret is set; the site
deploy run at 13:19 on 2026-09-13 proved it). The farm CLI is the tiinyapp-farm package on PyPI;
the trusted publisher is registered and the next tagged release proves the PyPI flow. Read
docs/APPS.md (or the schema and submission docs that exist) and the existing check workflow before
changing anything.

Build four things.

1. A scheduled poller. A workflow on an hourly cron that, for every manifest, reads repo, fetches
   the latest non-prerelease GitHub release, and when its tag is newer than the manifest version:
   downloads the tarball, computes sha256 and size itself (never trust maker-supplied numbers), and
   opens a PR that bumps version, release.url, release.sha256, release.size and updatedAt. One PR
   per app, reuse an open one rather than stacking. Skip apps whose manifest says "updates":
   "manual". Skip prereleases unless the manifest says "prereleases": true. Add both fields to the
   schema with those defaults.
2. A "Check for a new release" button on the app page, visible only to the signed-in maker of that
   app. It runs the exact same code path as the poller for that one app, right now, and shows the
   outcome in the maker's words: "v0.1.1 found, checks running, a maintainer will review it",
   "already listed at v0.1.1", or "no release newer than v0.1.0 on GitHub". Rate limit it per app
   to once a minute. Show the same status on Your apps.
3. A farm publish command in the CLI. Run by a maker after tagging: resolves their app id from the
   manifest in the current directory or an argument, finds the latest release, computes the
   numbers, and opens the bump PR using the maker's own gh login. Same verification as the poller.
   Prints the PR URL. (The CLI already has a `farm publish` that opens a submission PR through the
   site's API token; extend or split it so a release bump and a first submission both work, and say
   which in the report.)
4. The plumbing. A PR opened with the workflow's built-in GITHUB_TOKEN does not trigger the
   manifest checks, so the poller and the button must open PRs with a GitHub App token instead.
   Register a small farm-owned GitHub App, installed only on this repo, with contents and
   pull-requests write. Do not ask makers to install anything on their repos. Document the App's
   id, permissions and where the private key lives, never commit the key. NOTE FOR THE WORKER:
   creating the App and downloading its private key is a browser step only Jason can do. Write
   docs/GITHUB-APP.md with the exact settings (name, homepage, permissions, webhook off, where
   installed) and the two secret names the workflows read (FARM_APP_ID and FARM_APP_PRIVATE_KEY),
   build everything so it works the moment those two secrets exist, and report that they are the
   one thing outstanding.

Acceptance. A fake app repo with two releases drives the poller and the button in tests without
touching GitHub. The poller opens exactly one PR for a newer release and none for a listed one.
The checks workflow runs on a poller-opened PR (prove it with a real run against a throwaway
manifest once the App secrets exist, then close it; if they do not exist yet, prove it with a PR
opened by your own gh login and say so). farm publish opens a PR from a shell with only gh auth.
The schema rejects unknown updates values. Existing suite stays green.

First real use, once it works: OneLane (webdevtodayjason/onelane) and Story Lantern
(webdevtodayjason/story-lantern) are merged at version 0.1.1 but have no GitHub release yet, so
their listings still serve 0.1.0 tarballs that break on Tiiny 1.0 firmware. Jason, 2026-09-13
13:42: the agent MAY cut those two releases as the first real run, AFTER the checks have been
proven on the throwaway PR. Tag v0.1.1 on each repo at its current main (a GitHub release with
the tarball the manifest expects; read each repo's own release script or README for how its
tarball is built, and if a repo has a release script use it), then run the path and leave the two
bump PRs open for Jason to merge. Never merge on the farm.

Report back with the PR URL, the App registration details still needed, and anything you could
not verify.
