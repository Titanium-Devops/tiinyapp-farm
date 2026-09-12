# Phase 4 report

Implemented the six steps in order: accounts, TiinyVerse proof, site submissions, CI ownership gate, seed cards, then offline tests and configuration. The implementation is ready for orchestrator provisioning and deployment; it has not been deployed or exercised against live services.

No browser, Wrangler, Docker, or GUI was launched. No repository commit was attempted. Existing Docker selfcheck commands remain in CI; local tests mock those commands and never run them.

## 1. Farm accounts

- Email and GitHub both create or recover `user:<id>` records. While signed in, completing the other method links it to the same account. An identity belonging to another account is refused; there is no automatic account merging.
- Email codes are cryptographically random six-digit strings, valid for 10 minutes, limited to three sends per rolling hour per normalized address and five verification attempts per challenge. Only salted HMAC hashes are stored. Resend uses `Titanium Bot <farm@tiinyapp.farm>`.
- GitHub OAuth requests `read:user` only, checks a signed browser-bound state cookie, expires state after 10 minutes, and consumes it once. The OAuth access token is used to fetch the profile and is never persisted.
- Sessions use signed `__Host-farm` cookies with Secure, HttpOnly, SameSite=Lax and a 30-day lifetime. Server-side session records expire and logout revokes them. Mutating routes require the farm Origin.
- Email identity indexes use a stable SHA-256 of the normalized address, independent of the session-signing secret. Rotating the secret invalidates sessions and outstanding challenges without creating new email identities.

## 2. TiinyVerse proof

- Only `https://www.tiinyverse.com/users/<uuid>` profiles are accepted. The challenge is `farm-` plus six hexadecimal characters and expires after 24 hours.
- Verification uses the required User-Agent, a 10-second deadline, a 200 KiB streaming cap, HTTP 200 only, and no redirects. It searches for the exact challenge with token boundaries.
- Display names come from the profile H1, with an Open Graph title fallback; missing names fail closed. The user record stores the profile URL, decoded display name and verification timestamp. `tvowner:<uuid>` indexes the owner.
- An already-claimed profile is refused at both link and verification. `/api/owners?profile=<url>` returns `{verified, name}` without exposing email or account details.

## 3. Seed submissions

- A signed-in, TiinyVerse-verified maker can submit the form without using GitHub. The Worker accepts a direct public HTTPS gzip archive URL or one tar.gz upload, each capped at 50 MiB. Redirecting release URLs are refused. Upload bodies have a 30-second deadline.
- The Worker computes SHA-256 and exact byte size, builds the manifest, sets `verified: false`, and supplies `author.name`, `author.url` and `author.tiinyverse` from the verified profile. The source repository is optional.
- The JavaScript validator reads the same JSON schema and implements its keywords and the Python validator's semantic checks. Archives still undergo the existing extraction and source checks in CI.
- Uploads are stored at `seeds/<id>/<version>/<file>` in `farm-seeds`, served through `/seeds-files/<id>/<version>/<file>` with attachment and nosniff headers. Static assets continue through the existing asset binding.
- The farm token creates a unique branch, a manifest commit following the Lore message protocol, a PR, and the `from-the-site` label. No user OAuth token is used for submission.
- `/seeds/mine/` reads the authenticated maker's submissions, check-run conclusions, commit statuses and latest reviewer states. It reports pending, merged, closed, failed and temporarily unavailable states. Public check/status endpoints are read without Authorization so the bot token needs no Checks or Commit statuses permission.
- Retrying a successfully created submission returns the existing PR. Label failures preserve the PR and archive; resubmitting the same form retries the label. If PR creation has an uncertain outcome, the branch and archive are retained and duplicate submission is blocked for maintainer reconciliation.

## 4. CI gate and compatibility

`manifest-check.yml` invokes the trusted base-branch checker, which requires `author.tiinyverse` and asks the farm owner endpoint before downloading any archive. Missing/unverified owners, display-name mismatches, timeouts and invalid responses fail closed. The rejection is one plain sentence:

> The seed must name a verified TiinyVerse owner and their current farm display name.

Hand-made PRs pass the same gate as site submissions. The schema recognizes `author.tiinyverse`; its presence is enforced at submission time rather than breaking legacy catalog reads. Existing manifests are unchanged, and no owner proof was fabricated. All four existing catalog pages still build. Changing a legacy manifest now requires real owner proof.

## 5. Cards and status page

`/seeds/` keeps the approved Fraunces/Nunito fonts and existing color tokens. Three cards sit in a row on desktop and stack below 900px: Your farm account, Prove your Tiiny, Plant a seed. The page includes visible signed-out instructions, associated labels, live status messages, disabled proof/planting controls until their prerequisites are met, 44px minimum controls, check explanations and the “Do I need GitHub? No.” FAQ.

Only `/seeds/` and `/seeds/mine/` load the small client module. The rest of the catalog remains static. Profile and review text are inserted with textContent, not HTML. No framework or dependency was added.

## 6. Verification

- `node --test tests/worker.test.mjs`: **19 passed**, no failures. Fetch-injected Resend, TiinyVerse and GitHub fakes cover both auth doors and linking, CSRF/replay, email limits and expiry, session expiry/rotation/logout, profile claims and limits, owners lookup, manifests, R2 uploads and checksums, restricted bot-token usage, private status, failure recovery, concurrent code redemption, stale KV isolation and streaming cancellation.
- `python3 -m unittest`: **87 passed**, no failures. After the final site assertions and optional-fixture guard, the affected site/submission tests were rerun successfully.
- `python3 scripts/build-site.py`: **four app pages built**, plus the new seeds and private-status shells.
- `ruff check` on changed Python sources/tests, `node --check` on all Worker modules and the client module, Python compile checks, and `git diff --check`: passed.
- Site tests check internal links, signed-out content, input labels, locked controls, responsive grid rules, existing design tokens, retained assets and bindings. There is no configured TypeScript typecheck; the implementation is plain JavaScript.
- The pre-existing test of an ignored local Lite release archive now skips when that optional archive is absent, so clean CI checkouts do not fail for a developer-local artifact. Archive/scanner fixture tests remain active. The archive was present for this run, so that test passed locally.

## Orchestrator setup

Set these **Worker secrets**:

| Secret | Purpose |
| --- | --- |
| `SESSION_SECRET` | A fresh cryptographically random secret of at least 32 characters; signs sessions, OAuth state and code hashes. |
| `GITHUB_CLIENT_ID` | OAuth app client ID. |
| `GITHUB_CLIENT_SECRET` | OAuth app secret. |
| `RESEND_API_KEY` | Sending key for the verified `tiinyapp.farm` domain. |
| `FARM_GITHUB_TOKEN` | Farm bot fine-grained token restricted to `Titanium-Devops/tiinyapp-farm`: Contents read/write, Pull requests read/write, and GitHub's implicit metadata access. |

Register the OAuth callback as `https://tiinyapp.farm/api/auth/github/callback`. Configure and verify the Resend sending domain and the `farm@tiinyapp.farm` sender. Ensure the repository label `from-the-site` exists. Use a bot PAT or suitable installation token, not the Actions `GITHUB_TOKEN`, so submitted PRs trigger checks; installation tokens require external rotation before expiry.

Create the `FARM` KV namespace and replace `REPLACE_WITH_FARM_KV_NAMESPACE_ID` in `wrangler.toml` with its real ID. Create the R2 bucket `farm-seeds`, bound as `SEEDS`. The config retains the static assets as `ASSETS` and sends `/api/*` and `/seeds-files/*` through the Worker first.

The configuration also declares `FARM_COORDINATOR` and its SQLite Durable Object migration. This is intentional: KV does not provide atomic claims or strongly consistent one-time redemption. The coordinator serializes mutations using durable storage as the authoritative record and mirrors writes into `FARM` KV. Read-only owner/account/status requests bypass the mutation queue. KV mirrors may lag or miss writes when KV throttles; do not treat a KV-only snapshot as a complete backup or remove the coordinator. Provision support for the declared migration when deploying.

Existing CI deployment secrets remain `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Land the trusted checker and deploy/provision the owner API before exercising submission PRs. After a maintainer merges a seed, the existing main-branch workflow rebuilds and deploys the catalog.

## Remaining limits and live checks

- Live Resend delivery, OAuth configuration, actual TiinyVerse markup, GitHub permissions/labeling and Cloudflare bindings/migration were not exercised. Verify those with real configured services after deployment. Node tests do not prove Cloudflare's memory/CPU behavior for a full 50 MiB upload; include that in deployment smoke checks.
- No browser or GUI rendering was performed. Responsive geometry, fonts, tokens and controls were checked from source and generated HTML; visual fidelity and interactive browser behavior remain unverified.
- The single coordinator suits an early, low-volume farm. Mutation requests queue behind bounded uploads and remote requests. Public check/status reads have GitHub's anonymous rate limit; the UI reports unavailable results and offers refresh.
- The site currently creates new catalog IDs. Existing-ID updates use maintainer assistance or hand-made PRs with the same owner gate. A verified TiinyVerse profile cannot be reassigned through these routes.
- For `submission uncertain`, inspect the durable `seed:<id>@<version>` record, locate the PR by its saved branch, and reconcile its PR number/URL/state before allowing a retry. Do not delete its archive or branch until the remote outcome is known. Failed pre-PR submissions record their branch for cleanup if best-effort deletion fails.
- Expired auth records are rejected on reads; there is no periodic durable-record pruning job yet.

## Changed files and simplifications

- `worker/index.mjs`, `worker/proof.mjs`, `worker/seeds.mjs`, `worker/manifest.mjs`, `worker/main.mjs`: plain Worker routes, validation, persistence and file serving.
- `scripts/check-submission.py`, `.github/workflows/manifest-check.yml`, `docs/manifest.schema.json`: trusted owner gate and optional repository support.
- `scripts/build-site.py`, `site/assets/site.css`, `site/assets/seeds.js`: three-card flow and status page, reusing the existing site shell, tokens and typography.
- `tests/worker.test.mjs`, `tests/test_site.py`, `tests/test_submission.py`, `.github/workflows/site.yml`: offline coverage and CI execution.
- `wrangler.toml`, `docs/SUBMIT.md`, `docs/PHASE-4-REPORT.md`: bindings, operator setup and contributor guidance.

The old manifest-field dump on the seeds page was replaced with the account/proof/form flow; detailed packaging guidance stays in the contributor guide. Existing catalog manifests and installer behavior were preserved.
