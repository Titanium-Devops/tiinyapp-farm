# Phase 5b report

Implemented sprout headers, the complete favicon set, manifest and Midnight theme metadata;
all brand files ship in the build. The Titanium Bot footer identity is retained.
Every HTML page has share metadata; seed pages point at their own 1200×630 PNG.
One Pillow renderer handles seed cards and maker snapshots, including bounded image loading,
header → icon → sprout fallback, circular avatars, attribution and verified-Tiiny badges.
Seed and maker Share buttons use native sharing or copy the canonical URL with a two-second status.

Changed: `scripts/build-site.py`, new `scripts/share-cards.py`, `worker/makers.mjs`,
`site/assets/{site.css,share.js}`, `site/fonts/`, `site/makers.json`, site workflow and tests.
Shared card rendering and sharing logic avoid duplicate implementations; no framework was added.
The workflow installs Pillow, the only added build dependency.

## Allowed fallbacks and limitations

- Fraunces/Nunito downloads failed under restricted networking, and neither existed locally.
  Cards use bundled, licensed DejaVu Serif Bold/Sans TTFs; matching WOFF2 files provide browser
  fallbacks. The existing Google Fonts stylesheet remains for Fraunces/Nunito when reachable.
  Font provenance and licenses are in `site/fonts/`; actual Fraunces/Nunito files are not bundled.
- Maker cards use the specification's **build-time alternative**. The Worker has no image/font
  rasterizer; adding one would exceed the dependency constraint and put decoding, shaping and
  compression in the request path. No runtime R2 card cache or profile-edit invalidation is used.
  `site/makers.json` is an array of public snapshots with `handle`, `name`, `bio`, `avatar`
  (image URL or local site path), and `tiinyverse` (profile URL). Every snapshot gets a card;
  the catalog supplies its seed count and its avatar for matching seed authors.
  The checked-in snapshot is empty because this checkout contains no known farm maker handles.
  Refresh that snapshot and rebuild after profile edits or new makers. Until then, unknown makers
  share the default farm image. The Worker checks maker identity and serves GET/HEAD PNGs,
  rejecting missing assets/HTML fallbacks, with a five-minute cache lifetime.
- Optional remote media that cannot be downloaded falls back to the next available image.
  No live services or browser UI were tested.

## Verification

- `python3 -m unittest`: 99 tests passed.
- `node --test tests/worker.test.mjs`: 29 tests passed.
- `python3 scripts/build-site.py`: four seed pages and cards built.
- Ruff, Python type checking and JavaScript syntax checks passed for changed code.
- New checks cover PNG dimensions, every page's identity/share metadata, complete brand copying,
  maker snapshot rendering, Worker card delivery and native/clipboard/cancellation/error behavior.
- Inspected the generated PNG directly; no browser, GUI, wrangler or docker was launched.
  No commit was created.
