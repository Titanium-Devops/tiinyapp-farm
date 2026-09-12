# Phase 4: farm accounts, proof of a Tiiny, and the seeds page as cards

Facts, measured 2026-09-12 06:20 CDT: TiinyVerse (https://www.tiinyverse.com, "All for Tiiny
Owners") is the owners' community. Posting there requires binding the device serial to the
account. User pages are PUBLIC and server-rendered, e.g.
https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f answers 200 to a plain
fetch with the display name and the bio text ("No bio yet.") in the HTML. So control of a
TiinyVerse account can be proved by a code placed in the bio, and that control implies a bound
serial. Jason's rule: only people with a TiinyVerse account may bring seeds.

Build, in this order, all on the existing Cloudflare Worker (static assets stay; add routes
under /api/ with a KV namespace named FARM; stdlib-free Worker JavaScript, no framework):

1. Sign in with GitHub: /api/auth/github (redirect to GitHub OAuth, scope read:user only),
   /api/auth/github/callback (exchange the code, store {login, id, name, avatar} in KV under
   user:<id>, set a signed HttpOnly session cookie, 30 days), /api/auth/logout, /api/me. Secrets
   GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, SESSION_SECRET via `wrangler secret put` (the
   orchestrator sets them; document the names). CSRF state on the OAuth round trip.
2. Prove a Tiiny: POST /api/tiinyverse/link {profileUrl} validates the URL shape
   (https://www.tiinyverse.com/users/<uuid>), issues a code `farm-<6 chars>` stored on the user
   with a 24 h expiry, and answers the code and the instruction. POST /api/tiinyverse/verify
   fetches the profile page server-side (User-Agent "tiinyapp-farm-verifier/1.0", 10 s timeout,
   200 KB cap), looks for the exact code in the HTML, and on success stores
   tiinyverse:{profileUrl, name, verifiedAt} on the user and the reverse index
   owner:<github-login> -> profileUrl. A profile already claimed by another account is refused.
   GET /api/owners/<github-login> answers {verified: true|false, profileUrl} for CI.
3. The gate in CI: .github/workflows/manifest-check.yml gains a first job that calls
   https://tiinyapp.farm/api/owners/<pr author login>; a PR from an unverified login fails with
   one plain sentence pointing at https://tiinyapp.farm/seeds/. The manifest gains
   `author.tiinyverse` (the profile URL), required, and CI checks it matches the author's verified
   profile. The app page shows the TiinyVerse link on the author line and a "Tiiny owner" badge.
4. /seeds/ redone as cards, with polish: the hero line "Bring your seeds"; three cards in a row
   (stacked on a phone): 1 "Sign in with GitHub" (a button; shows the avatar and name when done),
   2 "Prove your Tiiny" (paste the profile URL, get the code, "put this in your TiinyVerse bio,
   then press Verify"; shows the verified profile when done), 3 "Plant a seed" (locked until 1 and
   2 are done: a form with name, pitch, repo URL, release URL, license, permissions checkboxes,
   what it needs; on submit the Worker validates against the manifest schema, builds the
   manifest, opens a branch and a pull request on Titanium-Devops/tiinyapp-farm through the
   GitHub API with a farm token FARM_GITHUB_TOKEN (contents and pull requests on that repo only),
   and shows the PR link). Below the cards: what the checks do, in the farm's voice, and a short
   FAQ. The mockup's tokens and fonts; 44 px targets; the page must still read fully signed out.
5. Tests: the Worker routes under `node --test` with a fake GitHub and a fake TiinyVerse page
   (the fetch is injected), the code issue and verify flow, the claimed-profile refusal, the
   owners route, the manifest built from the form; the site tests still green. Write
   docs/PHASE-4-REPORT.md and the secret names the orchestrator must set. No browser, no
   wrangler from your sandbox; commit is not possible from your sandbox.
