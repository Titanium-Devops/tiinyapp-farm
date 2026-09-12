# Phase 4: farm accounts, proof of a Tiiny, and the seeds page as cards

Facts, measured 2026-09-12 06:20 CDT: TiinyVerse (https://www.tiinyverse.com, "All for Tiiny
Owners") is the owners' community. Posting there requires binding the device serial to the
account. User pages are PUBLIC and server-rendered, e.g.
https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f answers 200 to a plain
fetch with the display name and the bio text ("No bio yet.") in the HTML. So control of a
TiinyVerse account can be proved by a code placed in the bio, and that control implies a bound
serial. Jason's rule: only people with a TiinyVerse account may bring seeds.

Jason's rule, 2026-09-12 06:29: a farm account is made with EITHER an email code OR Sign in with
GitHub; both are first-class and one account may have both linked. Proof of a Tiiny is the
TiinyVerse bio code in every case. GitHub is never required to bring a seed.

Build, in this order, all on the existing Cloudflare Worker (static assets stay; add routes under
/api/ with a KV namespace named FARM and an R2 bucket named farm-seeds; plain Worker JavaScript,
no framework):

1. Farm account, two doors into one account model (user:<id> {email?, github?{login,id,name,avatar}, createdAt}):
   (a) Sign in with GitHub: /api/auth/github (OAuth, scope read:user only), /api/auth/github/callback
   (exchange the code, never store the GitHub token, CSRF state), secrets GITHUB_CLIENT_ID and
   GITHUB_CLIENT_SECRET; (b) by email, no password: POST /api/auth/start {email} sends a six-digit code with
   Resend (secret RESEND_API_KEY, from "Titanium Bot <farm@tiinyapp.farm>"; the orchestrator sets
   the domain up), valid 10 minutes, rate-limited 3 per hour per address; POST /api/auth/verify
   {email, code} sets a signed HttpOnly session cookie (30 days) and stores user:<id>
   {email, createdAt}. /api/auth/logout, /api/me. Never store the code in plain form (hash it).
2. Prove a Tiiny: POST /api/tiinyverse/link {profileUrl} validates the URL shape
   (https://www.tiinyverse.com/users/<uuid>), issues a code `farm-<6 chars>` stored on the user
   with a 24 h expiry, and answers the code and the instruction. POST /api/tiinyverse/verify
   fetches the profile page server-side (User-Agent "tiinyapp-farm-verifier/1.0", 10 s timeout,
   200 KB cap), looks for the exact code in the HTML, and on success stores tiinyverse:{profileUrl,
   name, verifiedAt} on the user and the reverse index tvowner:<uuid> -> user id. A profile already
   claimed by another account is refused. The display name shown on plots comes from TiinyVerse.
3. Plant a seed, from the site, no git: POST /api/seeds (verified users only) takes the form (name,
   pitch, description, license, repo URL optional, permissions, what it needs, and EITHER a
   release URL OR an uploaded tar.gz up to 50 MB stored in R2 at seeds/<id>/<version>/<file> and
   served at https://tiinyapp.farm/seeds-files/<id>/<version>/<file>), computes the sha256 and
   size itself, builds the manifest with `author.tiinyverse` (the verified profile URL) and
   `author.name` (the TiinyVerse display name), validates it against docs/manifest.schema.json
   (port the validator's rules to JavaScript, or run the same checks), and opens a branch and a
   pull request on Titanium-Devops/tiinyapp-farm through the GitHub API with the farm's own token
   FARM_GITHUB_TOKEN (contents and pull requests on that repo only). The submitter never touches
   GitHub; they get a status page /seeds/mine/ listing their seeds and each one's check results
   and review state. A maintainer merges on GitHub; the site rebuilds.
4. The gate in CI: manifest-check.yml requires `author.tiinyverse` and calls
   https://tiinyapp.farm/api/owners?profile=<url> which answers {verified, name}; a manifest
   naming an unverified profile fails with one plain sentence. Pull requests from the farm bot
   carry a label `from-the-site`; hand-made pull requests are still allowed for people who prefer
   git, with the same gate.
5. /seeds/ redone as cards, with polish: the hero line "Bring your seeds"; three cards in a row
   (stacked on a phone): 1 "Your farm account" (email, the code, done state), 2 "Prove your
   Tiiny" (paste the profile URL, get the code, "put this in your TiinyVerse bio, then press
   Verify"; shows the verified profile when done), 3 "Plant a seed" (locked until 1 and 2 are
   done: the form, with the upload or the URL). Below the cards: what the checks do, in the farm's
   voice, and a short FAQ ("Do I need GitHub? No."). The mockup's tokens and fonts; 44 px targets;
   the page reads fully signed out.
6. Tests: the Worker routes under `node --test` with a fake Resend, a fake TiinyVerse page and a
   fake GitHub (fetch injected), the code flows, the claimed-profile refusal, the owners route,
   the manifest built from the form, the upload path with a checksum; the site tests still green.
   wrangler.toml gains the KV and R2 bindings (the orchestrator creates them). Write
   docs/PHASE-4-REPORT.md with the secret names the orchestrator must set. No browser, no
   wrangler from your sandbox; commit is not possible from your sandbox.
