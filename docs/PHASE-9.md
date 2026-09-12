# Phase 9: the account flows, and a door for AI assistants

Jason locked docs/LOCKED-FLOWS.html ("you have a go on all of this"). Reproduce its six screens and its
help modal on the live site with the site's faces and the tokens in .tastemaker/style-lock.md, then
add the API door. Tests green at the end. No framework, no dependency.

## A. The six screens (from docs/LOCKED-FLOWS.html)
- **/submit/** becomes a flow with the `.steps` strip: 1 Sign in, 2 Verify you own a Tiiny, 3 Your
  app. One panel per step, as the prototype: Sign in (email + code in one panel, "Send it again",
  GitHub as the second door, the "both doors" line), Verify (profile URL with the TiinyVerse path
  helper, the code shown large with Copy, expiry line, Verify, the verified line naming the maker
  page). The header's Sign in link lands on step 1.
- **Step 3 is two pages.** Page 1 "About and look": About panel (Name, ID with helper, One-line
  summary, What it does, Category select from site/categories.json, License) and Look panel (Icon,
  Header image, Screenshots, the "No art yet?" line). Give page 1 the feel of page 2: the same panel
  rhythm, section h2s, helper lines. Page 2 "Release and needs": Release panel with the two big radio
  cards (I have a release / Not yet) and Version, Release URL with the help link, upload; How it runs
  panel (Start command, This app uses checkboxes, Links). Right rail on page 2: "What happens next"
  with the four stages and durations. Next/Back keep the draft (localStorage, as now). Submit for
  review posts exactly what the current form posts.
- **Done screen** at /submit/done/?id=<id>: the app's icon (or sprout), "<Name> is in for review",
  the explanation, the live status list (pull request opened, checks running) polled from the
  existing status endpoint, buttons Go to Your apps / Submit another, and the card preview from
  the prototype's page 1 shown here ("This is your card in the catalog").
- **Help modal** on the Release URL helper: exactly the prototype's dialog: heading, three path
  buttons (website / terminal / AI assistant) that switch the step lists, the four-node chart, the
  footer. The AI path's prompt becomes: "Read https://tiinyapp.farm/docs/agents and publish this
  project to tiinyapp.farm. My token is: <paste yours from tiinyapp.farm/account/>" with a Copy
  button, plus the release-link version below it for people who only want the link.
- **/account/** becomes the prototype's Profile: left card (avatar, name, handle, verified chip, bio,
  links, Edit profile which opens the existing edit form inline, the Public profile switch, the
  "Signed in with" line and Sign out), right column "Your apps" rows with status words (Checks
  running, Published, Checks failed: <reason> with See why and Fix and resubmit, Waiting for review,
  Closed), Update and View. Under it, an **API tokens** card (part B).
- **Public profile**: new user field `public` (default true). When false: /makers/<handle>/ and its
  card.png answer 200 only to a signed-in session, otherwise a 200 page that says "This maker's page
  is for signed-in members. Sign in" with the sign-in link (not a 404, not a redirect loop); the
  catalog and app pages still show the name, linking to the maker page. The switch saves
  immediately (PUT /api/maker/visibility) with the two explanation texts from the prototype.

## B. The API door
- **Tokens**: `POST /api/tokens` (session, verified) creates one: name, `farm_` + 40 random chars,
  stored hashed (SHA-256), shown once; `GET /api/tokens` lists name, prefix, created, last used;
  `DELETE /api/tokens/<id>` revokes. Max five per account. The Account page card: list, Create a
  token (asks a name), the one-time reveal with Copy, Revoke.
- **Bearer auth** on POST /api/seeds, PUT /api/seeds/<id>, POST /api/media: `Authorization: Bearer
  farm_…` resolves the account like a session; the Origin check is skipped for Bearer calls; every
  other check stays (verified owner, rate limits, schema, archive rules). Errors are JSON with the
  same messages.
- **`farm publish`** in farm/farm.py: run in a project folder. Reads `farm.json` if present (the
  manifest fields a maker writes: id, name, pitch, description, version, license, category, entry,
  permissions, links; media file paths), else asks for the missing ones on the terminal. Packs the
  folder into `<id>-<version>.tar.gz` (excluding .git, node_modules, __pycache__, .venv, files over
  50 MB refused), uploads icon/header/screenshots via /api/media, then POSTs the submission with the
  archive upload. Token from `--token`, the `FARM_TOKEN` env var, or `~/.tiinyapps/token` (saved by
  `farm login`, which asks for the token once, 0600). Prints the pull request URL and the Your apps
  link. `farm publish --update` uses PUT for an existing id. `farm status <id>` prints the checks and
  review state from the same endpoint the site uses.
- **/docs/agents/** (static page, plain and complete, also served as /llms.txt in plain text): what
  the farm is, the two ways to publish (farm publish; or the HTTP API with curl examples for media
  and submission), the farm.json shape with every field and its rules, the token rule ("ask the
  person for their token; never make one up"), the checks that run, and what to tell the person at
  the end (the pull request URL and Your apps). Written so an assistant can follow it without the
  site.

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`. Add
tests: token create/list/revoke and Bearer submission (201) and revoked token (401); visibility off
hides the maker page from anonymous and shows it to a session; farm publish packs and posts against
a fake server (tests/test_farm.py style). Write docs/PHASE-9-REPORT.md (short). Never launch a
browser, wrangler, docker or any GUI. Do not commit.
