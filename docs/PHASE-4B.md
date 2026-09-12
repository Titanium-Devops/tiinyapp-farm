# Phase 4b: the seeds page becomes three tabs

Jason's feedback on the live /seeds/ page: three side-by-side cards make step 3 one skinny column
that stretches far below the others. Replace the three-column grid with tabs.

## Behaviour
- A tab strip above the card area: `01 Your farm account`, `02 Prove your Tiiny`, `03 Plant a seed`
  (role=tablist, buttons role=tab, aria-selected, arrow-key movement between tabs, panels role=tabpanel).
- Exactly one card is visible at a time and it takes the full content width. Step 3's form lays its
  short fields out in two columns at >= 900px (textareas, the file input, the permissions select and
  the details block span both). Below 900px everything is one column.
- The page opens on the right step for the signed-in state: no account -> 01, account without
  proof -> 02, proof done -> 03. After a successful sign-in the page moves to 02; after a successful
  Verify it moves to 03. A person can click any tab at any time to look; locked controls stay
  disabled exactly as now.
- Tabs show progress: a completed step's tab gets a small check mark and the muted style; the
  current step's tab is hay coloured; a locked step's tab is dim. No new copy beyond the tab labels.
- Keep every existing id, form, status paragraph, and the seeds.js API calls; only the layout, the
  tab strip, and the show/advance logic change. No framework, no dependency.

## Files
- scripts/build-site.py (seeds() markup), site/assets/site.css, site/assets/seeds.js,
  tests/test_site.py (update the grid/responsive assertions to the new structure; add one test that
  the tab strip and three panels are present and that only the first is not hidden in the static HTML).

## Verify
python3 -m unittest; node --test tests/worker.test.mjs; python3 scripts/build-site.py.
Never launch a browser, wrangler, docker or any GUI. Do not commit. Write docs/PHASE-4B-REPORT.md
(short) when done.
