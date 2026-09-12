# Phase 5 report

Implemented A (maker), B (seed faces), then C (thumbs/comments), with passing
Python and Worker tests at each boundary. No dependencies added. No browser,
GUI, wrangler, Docker, deployment, or commit was run.

## Routes

- `/farm/`: authenticated maker card, bio/avatar/link editing, and private seed
  review/check status plus thumbs/comments. Signed-out requests redirect to
  `/seeds/`; authenticated responses are private/no-store. `/seeds/mine/`
  redirects here. Shared navigation swaps Bring your seeds for My farm.
- `POST /api/maker`: saves bio (600 characters), owned avatar key, and optional
  HTTPS github/website/youtube links. Account records start with maker defaults;
  proof assigns a permanent display-name slug plus four hex characters. Existing
  accounts are initialized when next accessed; unproved accounts have no handle.
- `/makers/<handle>/`: Worker-rendered public verified maker card and merged
  seeds selected from the deployed `/catalog.json` by TiinyVerse profile. No
  proof means 404. Pending seeds have review status but no premature page link.
- `POST /api/media`: raw image bytes, authenticated verified account, PNG/JPEG/WebP
  magic-byte detection, 2 MiB cap; returns `{key,url}`. `DELETE
  /api/media/<userId>/<file>` removes only the caller's image and clears a matching
  avatar. `/media/<userId>/<file>` serves GET/HEAD with the sniffed content type,
  nosniff and a one-year immutable cache. Previously cached copies can outlive deletion.
- `/apps/<id>/`: remains static. Optional icon/header/gallery and link metadata
  render at build time; gallery links open a native dialog. YouTube embeds use
  youtube-nocookie and are created only on a poster click.
- `GET /api/seeds/<id>/social`: public counts, caller's thumb state, comments and
  current author card data; `canDelete` lets the UI expose authorized controls.
- `POST /api/seeds/<id>/thumb`: authenticated account toggles its one thumb.
- `POST /api/seeds/<id>/comments`: verified account, 1–1000 plain-text characters,
  five comments per rolling hour across seeds. `DELETE
  /api/seeds/<id>/comments/<cid>` permits the author or a farm admin. Only deployed
  catalog seeds accept social actions. Client inserts names/text with textContent.

## Storage and configuration

FarmCoordinator durable storage is authoritative, with write-through FARM KV
mirrors. Added fields on `user:<id>`: `handle`, `bio`, `avatarKey`, `links`.
`maker:<handle>` maps to user ID; `social:<seedId>` stores account IDs for thumbs
and `{id,userId,text,at}` comments; `comment-rate:<userId>` retains posting times
independently of deletion. Existing seed/account/proof keys remain supported.
R2 SEEDS stores images at `media/<userId>/<32-random-hex>.<png|jpg|webp>`.

The orchestrator must set Worker var **FARM_ADMINS** after deployment to a
comma-separated list of farm user IDs, including Jason's actual `user.id` from
his authenticated `/api/me`. These are farm account IDs, not TiinyVerse IDs,
handles, or email addresses. Unset/empty means no admin override. Preserve the
var on future deployments. Existing FARM, SEEDS, FARM_COORDINATOR, ASSETS and
phase-4 auth/submission secrets are still required. Deploy Worker and rebuilt
assets together; wrangler.toml now routes maker/farm/media paths through Worker.

## Files and verification

- Worker routes: `worker/{index,main,makers,proof,seeds,social,manifest}.mjs`.
- Schema/catalog: `docs/manifest.schema.json`, all four `manifests/*.json`,
  `scripts/{build-site,check-manifest}.py` (checker now accepts multiple paths).
- UI: `site/assets/{session,farm,seeds,seed-media,social}.js`, `site.css`.
  Shared session navigation replaces duplicate account fetching; the old private
  seed list is replaced by the farm page. Existing HTTPS homepage/repo fields
  still work alongside `links`; no framework or extra dependency was introduced.
- Existing Titanium assets copied unchanged: `titanium-icon.png` from
  `assets/console/characters/titan-calm.png`, and `titanium-header.webp` from
  `assets/console/backgrounds/titan-nebula.webp` in the local titanium-bot-lite
  checkout. Other seeds have no invented images; no videos were invented.
- Tests: `tests/test_site.py` and `tests/worker.test.mjs` cover generated markup,
  safe DOM text insertion, schema parity, media/ownership, rate limiting,
  authorization and concurrent coordinator writes.

Verification: `python3 -m unittest` (92 tests), `node --test tests/worker.test.mjs`
(27 tests), `python3 scripts/build-site.py`, and
`python3 scripts/check-manifest.py manifests/*.json` pass. Ruff, mypy, JavaScript
syntax checks and diff whitespace checks pass. Live Cloudflare services and visual
layout were not exercised; tests use offline service fakes and DOM doubles.
