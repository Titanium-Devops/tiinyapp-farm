# Phase 9 report

Implemented the locked account flows first, then the API publishing door.

## Part A

- Rebuilt sign-in, TiinyVerse verification, two-page app submission, release help, completion, and account/profile screens from the locked flow.
- Preserved drafts and update payloads, added catalog categories, live card previews, and live review-status polling.
- Added public-profile visibility with immediate saving and signed-in-only maker pages/share cards.

## Part B

- Added one-time `farm_` API tokens with hashed storage, listing, last-use tracking, a five-token limit, and revocation.
- Added Bearer authentication for publishing, updating, media upload, and submission status without weakening the existing ownership, validation, archive, or rate-limit checks.
- Added `farm login`, `farm publish`, `farm publish --update`, and `farm status <id>` with safe project packing and media upload.
- Added the complete assistant guide at `/docs/agents/` and `/llms.txt`.

## Verification

- `python3 -m unittest`: 126 passed, 1 skipped.
- `node --test tests/worker.test.mjs`: 40 passed.
- `python3 scripts/build-site.py`: built 4 app pages.
- JavaScript syntax checks and Python byte-compilation passed.

No browser, GUI, Wrangler, Docker, or commit was used.
