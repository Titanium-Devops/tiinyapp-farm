# Phase 7: rebuild the inner pages to the approved v0

Jason approved docs/REDESIGN.html ("Build it"). It holds the review, the site map, the word list, and
three v0 frames whose markup and CSS are the reference: Install (section 4), Submit an app (section 5),
App page (section 6). Reproduce those frames on the live site with the site's real faces (Fraunces for
h1/h2, Nunito for text) and tokens. The hero on the home page does not change. Tests green at the end.
No framework, no dependency.

## Routes and header
- New static pages: `/install/` (from the v0 Install frame) and `/submit/` (the v0 Submit frame). The
  Worker answers `/plant/` -> 301 `/install/`, `/seeds/` -> 301 `/submit/`, `/farm/` -> 301 `/account/`,
  and serves `/account/` (the old /farm/ page, retitled "Your apps"). `/seeds/mine/` -> `/account/`.
  Keep `/apps/<id>/`, `/manifests/<id>.json`, `/makers/<handle>/`, `/media/*`, `/api/*` unchanged.
- Header on every page, exactly: sprout mark + "tiinyapp.farm" · Apps · Install · Submit an app · right
  side "Sign in" (links to /submit/ step 1) or, signed in, the avatar and first name linking to
  /account/ (session.js already swaps; make it swap this). The current page's link is white, the
  others muted. No tagline under the wordmark.
- Home page: hero as is; catalog heading "Apps"; catalog cards unchanged except the button reads
  Install and the "by <maker>" line links to the maker page.

## Install page
Exactly the v0: h1 "Install apps on your Tiiny", the intro sentence, three numbered rows (32 px
numbered circle, title, prose, command block, the two-column definition list for URL and key, and the
command list in step 3), then the one note about declared access. Single column, max width 880 px.
Rows, not cards in a grid.

## Submit page
Exactly the v0: h1 "Submit an app", the one-sentence explanation of what happens after submitting,
the three-part progress strip (1 · Sign in, 2 · Verify you own a Tiiny, 3 · Your app; done parts show
a check in mint, the current one is hay, upcoming ones muted). One part visible at a time, as now.
- Part 1: email field + "Send code", code field + "Sign in", "Sign in with GitHub", signed-in state
  with "Sign out" and "Link GitHub". Plain labels.
- Part 2: the TiinyVerse paragraph from the word list ("Paste the URL of your TiinyVerse profile. We
  give you a short code. Put that code anywhere in your TiinyVerse bio, save, then press Verify. We read
  your public profile once to confirm you own it, the same idea as a DNS TXT record. You can remove the
  code afterwards."), URL field, "Get my code", the code shown large, "Verify".
- Part 3: the form in ONE column, max width 560 px, in three fieldsets exactly as the v0: About the app
  (Name, ID with the helper line, One-line summary, Description, License), Release (radio: "I have a
  release" / "Not yet, list it as No release yet"; Version; Release URL with helper; Or upload;
  Start command with helper; "This app uses" as four checkboxes: Microphone, Files, Network, Your
  Tiiny), Links and images (all optional: Source repository, Home page, YouTube video, Icon, Header
  image, Screenshots up to 8). Button "Submit for review" with the muted line "Your draft is saved on
  this computer as you type." Choosing "Not yet" hides Version-Release URL-upload and keeps the rest.
  Errors under the field, as now. The permissions multi-select becomes the four checkboxes (same
  values sent). Labels are bold 14 px with the helper in a muted `<small>` under the label.
- After Submit: go to /account/ as now.

## App page
Exactly the v0: optional header image, icon beside the h1 with "v<version> · <license> · <review
state>" under it, the one-line summary, then a two-column layout (main 1fr, rail 300 px; one column
under 760 px): main = Install (commands, the "Then open http://localhost:<port>" line when a port is
declared, "New here? Install the farm CLI first." link), What it does, Screenshots, Comments; rail =
Needs card (Python, Port, Models, Uses chips), Release card (Version, Size, SHA-256 in small mono,
Source link), Maker card (avatar, name, Verified Tiiny owner chip), then Thumbs up and Share buttons.
No release: the Release card says "No release yet" and the Install block is replaced by one line.

## Your apps (/account/) and maker page
Same header and page width. /account/: h1 "Your apps", profile card (avatar, name, handle, bio, links,
Edit), then the list of the maker's apps with status words: Checks running · Checks failed: <reason> ·
Waiting for review · Published · Closed, each linking to its app page or pull request. Maker page:
h1 "<name>", handle, Verified Tiiny owner chip, bio, links, Share, then "Apps by <name>" as catalog
cards.

## Word list
Apply docs/REDESIGN.html section 3 everywhere, including the Worker's JSON error strings and status
words, the share cards ("Grown by" stays), farm.py's messages, README and docs/SUBMIT.md.

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`. Update
tests to the new routes and copy; add a test that /plant/, /seeds/, /farm/ redirect. Write
docs/PHASE-7-REPORT.md (short). Never launch a browser, wrangler, docker or any GUI. Do not commit.
