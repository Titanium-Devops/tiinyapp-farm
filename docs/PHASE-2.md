# Phase 2: the site

Jason approved the mockup at site/design/mockup-approved.html on 2026-09-12 ("We're in alignment.
I love it."). The domain is tiinyapp.farm (two i's). Build the real site from it.

1. scripts/build-site.py (stdlib only): reads manifests/*.json and writes site/dist/: index.html
   (the field: one plot per manifest, badges from `verified` and `addedAt` within 30 days = New,
   entry null = Library), one page per app at /apps/<id>/ rendering the whole manifest in plain
   words (what it does, what it needs, what it asks for, install and start commands, screenshots
   if any, author, license, repo, release with checksum and size), /plant/ (the three steps),
   /seeds/ (how to submit, the manifest fields explained, the checks), /manifests/<id>.json
   copied verbatim (the installer's catalog URL is https://tiinyapp.farm/manifests/), a sitemap
   and robots.txt, a 404 page. No JavaScript needed to read anything; a little for a search box
   on the field is fine.
2. The look: exactly the mockup's tokens (Midnight #090D14, soil, fence, hay #F2C462, cyan
   #00C8F0, mint, berry; Fraunces + Nunito from Google Fonts with system fallbacks), the hero at
   site/assets/hero.jpg (JPEG, served as a file, not a data URI), the farm voice ("plant it",
   "the field", "farmhands", "bring your seeds"), both marks in the footer ("Brought to you by
   Titanium Bot" linking https://titanium.bot; "Built for" with brand/tiiny-logo.svg linking
   https://tiiny.ai). Light theme optional; dark is the one that ships. Phone width first:
   measure nothing overflows at 390 px by static reasoning and keep every tap target 44 px.
3. Deploy target: Cloudflare Workers static assets. Write wrangler.toml for a Worker named
   tiinyapp-farm serving site/dist as assets with a custom domain tiinyapp.farm, and a
   .github/workflows/site.yml that builds and runs `wrangler deploy` on push to main using
   secrets CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID (the orchestrator sets them and does
   the first deploy by hand). Do not run wrangler yourself.
4. Tests: build-site produces every page for the four manifests, the manifest copies are
   byte-identical, every internal link resolves, the hero and the marks are referenced, no
   em dash anywhere in the copy, the words "tinyapp" (one i) appear nowhere. `python3 -m
   unittest` green. Write docs/PHASE-2-REPORT.md. No browser or GUI; commit is not possible from
   your sandbox.
