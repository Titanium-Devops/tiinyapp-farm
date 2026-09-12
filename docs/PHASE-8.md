# Phase 8: the locked home, catalog and app page

Jason locked the composition in docs/LOCKED-HOME-CATALOG-APP.html ("No I like it. Lock that in"). That file is
the reference: its CSS (tokens, .v1 shelf tiles, .v2 ledger rows, .v3 editorial items, .feat, .ledger,
.toolbar, .search, .cats, .catalog, the app page .band/.head/.two/.rail) and its markup are to be
reproduced on the live site with the real Fraunces/Nunito faces. Read .tastemaker/style-lock.md and
.tastemaker/reference-board.md first; they are binding (tokens, spacing scale, one icon set, motion).

## Pages
- **Home `/`**: hero as is. Then "Featured" (section head: h2 + muted line "Picked by the maintainers") as
  editorial items (.v3 .item, art alternating sides, category tag, name, pitch, first two sentences of
  the description, chips, Install + command with copy). Featured = manifests with `"featured": true`
  (add the boolean to docs/manifest.schema.json; set it on the four current manifests). Cap 6. Then
  "All apps" as ledger rows (.v2 .row: icon, category tag, name, pitch, chips, version, Install) with a
  live search box (name, pitch, maker, tags, categories; client-side, small module, textContent only)
  and a count "n of N", plus a link "Browse the catalog with filters" to /catalog/. Then the existing
  Submit band. Remove the old plot grid.
- **Catalog `/catalog/`**: h1 "Catalog", lede, search box, category chips (All + categories present),
  shelf tiles (.v1 .tile: header art with the icon overlapping, category tag, name, pitch, meta line
  "v · by maker · needs", permission chips, command with copy, Install). Filtering client-side from
  /catalog.json (already built) with the URL reflecting state (`?q=` and `?cat=`). Empty state line
  with a link to /submit/. Categories derive from tags with this map (in build-site.py and the client
  module, one source: write it to site/categories.json at build): developer-tools, coordination,
  benchmark, measurement -> Developer tools; library -> Libraries; stories, family -> Family; audio ->
  Audio; assistant, chat, voice -> Assistants. Order: Assistants, Family, Audio, Developer tools,
  Libraries. An app's first category is its tag on cards.
- **App page `/apps/<id>/`**: the locked app page: header band (media.header, 1040x300 crop, hidden when
  absent), icon 72 overlapping the band's bottom-left, h1, the meta line "v · license · review state ·
  Grown by <maker link>", pitch, then two columns (1fr + 300, one column under 760): Install (one
  command block `farm install <id> && farm start <id>` with a copy button, the "Then open
  http://localhost:<port>" line, the CLI link), What it does, Screenshots, Comments; rail: Needs card
  (Python, Port, Models, NPU, Uses chips), Release card (Version, Size in MB, SHA-256 short mono,
  Source), Maker card (avatar, name, Verified Tiiny owner chip), Thumbs up + Share buttons.
- **Header everywhere**: sprout mark + wordmark · Apps (/) · Catalog · Install · Submit an app · right
  side Sign in or avatar + first name (session.js). No tagline.
- **Media**: the three generated headers and icons are in site/assets/art/ (onelane, story-lantern,
  tiiny-bench: `<id>-icon.png`, `<id>-header.webp`). Set `media.icon` and `media.header` in those three
  manifests to their /assets/art/ paths. Titanium keeps its existing media.
- **Icons**: copy and check from design/assets/icons (Tabler), inlined as SVG with class "ic" (18 px).
  No other icon source, no emoji.
- **Motion**: the shelf tiles rise once (300 ms, staggered 50 ms, opacity + transform only, reduced
  motion drops it). Buttons transition background and transform only, 150 ms. Nothing else.

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`,
`python3 scripts/check-manifest.py manifests/*.json`. Update tests to the new home, catalog and app
page structure; add: /catalog/ exists with the chips; featured manifests appear in the Featured
section; the search module escapes text. Write docs/PHASE-8-REPORT.md (short). Never launch a browser,
wrangler, docker or any GUI. Do not commit.
