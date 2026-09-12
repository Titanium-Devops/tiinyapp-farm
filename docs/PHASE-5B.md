# Phase 5b: share cards and the sprout identity

Jason's ask: "a social share for a card or for a Tiiny app. It should have an OG that's built out with our
beautiful image, as well as the seed project and the developer who owns Tiiny and added it." Plus: "there
are favicons, icons, and logos inside of our brand asset that need to be adopted by the site."

Builds on phase 5 as it stands. No framework, no dependency beyond Pillow (already used by the build;
add `pillow` to the site workflow's pip install).

## Identity
- brand/tiinyapp-farm-square-logo.png is the farm's mark (the sprout with the little chip face). The
  favicon set already exists in brand/: favicon.ico, favicon-32.png, favicon-192.png,
  apple-touch-icon.png, icon-512.png, og-image.png. Wire them: `<link rel="icon">` for .ico, 32 and 192,
  `<link rel="apple-touch-icon">`, a `site.webmanifest` (name tiinyapp.farm, icons 192 and 512, theme
  colour from the Midnight token), `<meta name="theme-color">`. Copy every brand/ file into site/dist/brand.
- The header brand mark becomes the sprout (a 36 px round crop of icon-512) instead of the Ti tile; the
  Titanium Bot "Brought to you by" footer chip keeps the Ti tile.
- Default share meta on every page: og:title, og:description (the page lede), og:image
  /brand/og-image.png, og:url, twitter:card summary_large_image.

## Share cards
- `scripts/build-site.py` renders one card per seed at `site/dist/apps/<id>/card.png` (1200x630, PNG):
  Midnight ground; the seed's header image (or icon, or the sprout when there is neither) filling the left
  half with a soft fade into the ground; on the right: the seed name in Fraunces (ship the two font files
  under `site/fonts/` as woff2 for the browser and ttf for Pillow; if a ttf cannot be found, fall back to
  DejaVu but say so in the report), the one-line pitch in Nunito, the maker line "Grown by <name>" with
  the maker's avatar in a circle and a small verified-Tiiny badge when `author.tiinyverse` is set, and
  the sprout mark plus "tiinyapp.farm" bottom right. Every seed page sets og:image to its card, with
  og:image:width/height.
- Maker pages are Worker-rendered; the Worker serves `/makers/<handle>/card.png` by composing the same
  layout at request time from the maker's avatar, name, bio line and seed count, cached in R2 under
  `cards/makers/<handle>.png` and invalidated when the maker edits their profile. Pure JS PNG encoding
  is fine (a small deflate via CompressionStream and a hand-written PNG writer), or, if that exceeds
  Cloudflare limits in your judgement, render the maker card at build time for every maker known at
  build and say so in the report.
- A **Share** button on each seed page and maker page: `navigator.share` when present (title, text, url),
  otherwise copies the URL and shows "Link copied" for two seconds. Plain button, same tokens.

## Verify
`python3 -m unittest` (add tests: the card file exists for each built seed and is 1200x630; the head
carries the favicon set, manifest and og tags; the seed page og:image points at its card),
`node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`. Write docs/PHASE-5B-REPORT.md
(short). Never launch a browser, wrangler, docker or any GUI. Do not commit.
