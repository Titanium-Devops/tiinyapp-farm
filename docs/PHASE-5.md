# Phase 5: makers have a home, seeds have faces

Jason's ask (2026-09-12): "how does the user see their profile and log in? ... From the page I don't see my
profile page, which should have my farm profile, my seeds with whether they were liked, thumbed up, or had
comments. Seeds should have a main image, a header image, a gallery, a repo link, a YouTube link. The user
should have a bio and their own icon."

Build on phase 4 as it stands (worker/*.mjs, scripts/build-site.py, site/assets/seeds.js, tests). Keep
the farm voice, the Fraunces/Nunito faces, the existing tokens. No framework, no dependency. Three parts,
in this order; each part leaves the tests green.

## Part A: the maker

- Every farm account gets a maker record on `user:<id>`: `handle` (slug of the TiinyVerse display name
  plus a 4-hex suffix, fixed once set), `bio` (plain text, 600 chars max), `avatarKey` (R2 key or null),
  `links` ({ github, website, youtube }, all optional https URLs).
- **My farm** at `/farm/`: private, needs sign-in. Shows the maker card (avatar, display name from the
  TiinyVerse proof, handle, bio, links) with an edit form (bio, avatar upload, links), and the maker's
  seeds, each with its review state (from the phase 4 /api/seeds/mine data), thumbs count, comment count,
  and a link to the seed's page. `/seeds/mine/` becomes a redirect to `/farm/`. The header nav shows
  **My farm** when signed in and **Bring your seeds** when not (client-side swap in a small shared module;
  the static HTML carries Bring your seeds).
- **Public maker page** at `/makers/<handle>/`: server-rendered by the Worker (route through the Worker,
  not a static page), shows avatar, name, bio, links, verified-Tiiny badge, and the maker's merged seeds
  as cards. Makers without proof have no public page (404).
- Avatar and every image in this phase: `POST /api/media` (signed in, verified owner), png/jpg/webp only,
  2 MiB max, stored at `media/<userId>/<random>.<ext>` in the `SEEDS` R2 bucket, served at
  `/media/<userId>/<file>` with a long cache header and nosniff. Sniff the magic bytes; refuse anything
  else. A maker can delete their own media.
- `/seeds/` tab 01, when signed in, links to My farm.

## Part B: seed faces

- Manifest schema gains optional `media` ({ icon, header, gallery[] } of https URLs on this farm's /media/
  or any https image URL, gallery max 8) and `links` ({ repo, video, homepage }); `video` must be a YouTube
  watch or youtu.be URL. `homepage` stays supported at the top level for old manifests; the site reads
  either.
- The submission form on `/seeds/` tab 03 gains: main image (icon), header image, gallery (up to 8),
  repo link (moves the existing optional source repository field here), YouTube link. Uploads go through
  /api/media first, then the manifest carries the URLs. The farm bot PR includes them.
- The catalog: the plot card on the field shows the icon; the seed page `/apps/<id>/` shows the header
  image across the top, the icon beside the name, the gallery as a row of thumbnails that open full size
  in a `<dialog>`, the repo and homepage links, and the YouTube video as a privacy-enhanced embed
  (`https://www.youtube-nocookie.com/embed/<id>`) that only loads after the person clicks its poster.
  Add `media`/`links` to the four existing manifests with sensible values where a real image exists
  (Titanium Tiiny Bot has brand assets in /Users/sem/code/titanium-bot-lite/brand and assets; leave the
  others without images rather than inventing any).
- The catalog build stays static for /apps/<id>/; the social strip below is filled by the client.

## Part C: thumbs and comments

- `POST /api/seeds/<id>/thumb` toggles one thumbs-up per account per seed; `GET /api/seeds/<id>/social`
  returns `{ thumbs, mine, comments: [{ id, author: { handle, name, avatar }, text, at }] }`.
- `POST /api/seeds/<id>/comments` (signed in, verified owner, plain text 1000 chars max, five per hour
  per account); `DELETE /api/seeds/<id>/comments/<cid>` by the author or by a farm admin. Admin is any
  user id listed in the `FARM_ADMINS` Worker var (comma separated); Jason's account is set by the
  orchestrator after deploy.
- The seed page shows the thumb button with the count, and the comments with the author's avatar and a
  link to their maker page. Signed-out people see counts and comments, and a line inviting them to sign
  in on /seeds/. Text is inserted with textContent, never HTML.
- Storage: the FarmCoordinator serialises thumbs and comments the same way it does accounts; records
  `social:<seedId>` in KV mirror.

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`,
`python3 scripts/check-manifest.py manifests/*.json`. Write short docs/PHASE-5-REPORT.md with the
routes, the storage keys, and what the orchestrator must set (FARM_ADMINS). Never launch a browser,
wrangler, docker or any GUI. Do not commit.
